"""Web dashboard — lightweight HTMX-powered operational status UI.

Serves HTML views for humans who want a quick glance at fleet status
without using the API directly or opening Splunk. All data comes from
the same internal API endpoints used by MCP tools.

No build step. No npm. No node_modules. Just Jinja2 + HTMX + Pico CSS.
"""

import json
import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Base template with HTMX + Pico CSS (CDN)
# ---------------------------------------------------------------------------
BASE_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Corvus — {title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <style>
        :root {{ --pico-font-size: 87.5%; }}
        nav {{ padding: 0.5rem 1rem; background: var(--pico-card-background-color); margin-bottom: 1rem; }}
        nav ul {{ margin: 0; }}
        .stat-card {{ text-align: center; padding: 1rem; }}
        .stat-card h2 {{ margin: 0; font-size: 2.5rem; }}
        .stat-card small {{ color: var(--pico-muted-color); }}
        .severity-critical {{ color: #dc4e41; font-weight: bold; }}
        .severity-warning {{ color: #f8be34; }}
        .severity-info {{ color: #53a051; }}
        .status-open {{ color: #dc4e41; }}
        .status-investigating {{ color: #f8be34; }}
        .status-resolved {{ color: #53a051; }}
        .status-active {{ color: #0877a6; }}
        table {{ font-size: 0.85rem; }}
        td, th {{ padding: 0.4rem 0.6rem; }}
        .auto-refresh {{ font-size: 0.75rem; color: var(--pico-muted-color); }}
        .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px;
                  font-size: 0.75rem; font-weight: 600; }}
        .badge-critical {{ background: #dc4e41; color: white; }}
        .badge-warning {{ background: #f8be34; color: black; }}
        .badge-info {{ background: #53a051; color: white; }}
        .badge-open {{ background: #dc4e41; color: white; }}
        .badge-investigating {{ background: #f8be34; color: black; }}
        .badge-resolved {{ background: #53a051; color: white; }}
        .badge-active {{ background: #0877a6; color: white; }}
        .badge-completed {{ background: #53a051; color: white; }}
    </style>
</head>
<body>
    <nav>
        <ul>
            <li><strong>Corvus</strong></li>
        </ul>
        <ul>
            <li><a href="/dashboard">Overview</a></li>
            <li><a href="/dashboard/incidents">Incidents</a></li>
            <li><a href="/dashboard/changes">Changes</a></li>
            <li><a href="/dashboard/services">Services</a></li>
            <li><a href="/dashboard/events">Events</a></li>
            <li><a href="/dashboard/knowledge">Knowledge</a></li>
        </ul>
    </nav>
    <main class="container">
        {content}
    </main>
    <footer class="container">
        <small class="auto-refresh">
            Auto-refreshes every 30s via HTMX |
            <a href="/docs">API Docs</a> |
            <a href="/health">Health</a>
        </small>
    </footer>
</body>
</html>"""


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(BASE_TEMPLATE.format(title=title, content=content))


def _severity_badge(severity: str) -> str:
    cls = f"badge-{severity}" if severity in ("critical", "warning", "info") else "badge-info"
    return f'<span class="badge {cls}">{severity}</span>'


def _status_badge(status: str) -> str:
    cls = f"badge-{status}" if status in ("open", "investigating", "resolved", "active", "completed") else ""
    return f'<span class="badge {cls}">{status}</span>'


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
async def overview():
    """Fleet overview dashboard."""
    db = await get_db()
    try:
        # Counts
        events_24h = (
            await db.execute_fetchall("SELECT COUNT(*) FROM ops_events WHERE timestamp > datetime('now', '-1 day')")
        )[0][0]

        open_incidents = (
            await db.execute_fetchall("SELECT COUNT(*) FROM ops_incidents WHERE status IN ('open', 'investigating')")
        )[0][0]

        active_changes = (await db.execute_fetchall("SELECT COUNT(*) FROM ops_changes WHERE status = 'active'"))[0][0]

        total_services = (await db.execute_fetchall("SELECT COUNT(*) FROM ops_cmdb"))[0][0]

        # Recent incidents
        recent_incidents = await db.execute_fetchall(
            "SELECT id, target, title, severity, status, created_at FROM ops_incidents ORDER BY created_at DESC LIMIT 5"
        )

        # Recent events
        recent_events = await db.execute_fetchall(
            "SELECT id, type, target, severity, source, timestamp FROM ops_events ORDER BY timestamp DESC LIMIT 10"
        )

        incidents_html = ""
        for row in recent_incidents:
            incidents_html += (
                f"<tr><td><code>{row[0]}</code></td><td>{row[1]}</td>"
                f"<td>{row[2]}</td><td>{_severity_badge(row[3])}</td>"
                f"<td>{_status_badge(row[4])}</td></tr>"
            )

        events_html = ""
        for row in recent_events:
            ts = row[5][:19] if row[5] else ""
            events_html += (
                f"<tr><td>{ts}</td><td>{row[1]}</td><td>{row[2]}</td>"
                f"<td>{_severity_badge(row[3])}</td><td>{row[4]}</td></tr>"
            )

        content = f"""
        <hgroup>
            <h1>Fleet Overview</h1>
            <p>Operational governance at a glance</p>
        </hgroup>

        <div class="grid" hx-get="/dashboard/fragment/stats" hx-trigger="every 30s" hx-swap="outerHTML">
            <article class="stat-card"><h2>{events_24h}</h2><small>Events (24h)</small></article>
            <article class="stat-card"><h2>{open_incidents}</h2><small>Open Incidents</small></article>
            <article class="stat-card"><h2>{active_changes}</h2><small>Active Changes</small></article>
            <article class="stat-card"><h2>{total_services}</h2><small>CMDB Services</small></article>
        </div>

        <h3>Recent Incidents</h3>
        <div hx-get="/dashboard/fragment/incidents" hx-trigger="every 30s" hx-swap="innerHTML">
        <table>
            <thead><tr><th>ID</th><th>Target</th><th>Title</th><th>Severity</th><th>Status</th></tr></thead>
            <tbody>{incidents_html if incidents_html else '<tr><td colspan="5">No incidents</td></tr>'}</tbody>
        </table>
        </div>

        <h3>Recent Events</h3>
        <div hx-get="/dashboard/fragment/events" hx-trigger="every 30s" hx-swap="innerHTML">
        <table>
            <thead><tr><th>Time</th><th>Type</th><th>Target</th><th>Severity</th><th>Source</th></tr></thead>
            <tbody>{events_html if events_html else '<tr><td colspan="5">No events</td></tr>'}</tbody>
        </table>
        </div>
        """
        return _page("Overview", content)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# HTMX fragments (partial HTML for live updates)
# ---------------------------------------------------------------------------
@router.get("/fragment/stats", response_class=HTMLResponse)
async def fragment_stats():
    """Stats cards fragment — polled by HTMX."""
    db = await get_db()
    try:
        events_24h = (
            await db.execute_fetchall("SELECT COUNT(*) FROM ops_events WHERE timestamp > datetime('now', '-1 day')")
        )[0][0]
        open_incidents = (
            await db.execute_fetchall("SELECT COUNT(*) FROM ops_incidents WHERE status IN ('open', 'investigating')")
        )[0][0]
        active_changes = (await db.execute_fetchall("SELECT COUNT(*) FROM ops_changes WHERE status = 'active'"))[0][0]
        total_services = (await db.execute_fetchall("SELECT COUNT(*) FROM ops_cmdb"))[0][0]

        return HTMLResponse(f"""
        <div class="grid" hx-get="/dashboard/fragment/stats" hx-trigger="every 30s" hx-swap="outerHTML">
            <article class="stat-card"><h2>{events_24h}</h2><small>Events (24h)</small></article>
            <article class="stat-card"><h2>{open_incidents}</h2><small>Open Incidents</small></article>
            <article class="stat-card"><h2>{active_changes}</h2><small>Active Changes</small></article>
            <article class="stat-card"><h2>{total_services}</h2><small>CMDB Services</small></article>
        </div>""")
    finally:
        await db.close()


@router.get("/fragment/incidents", response_class=HTMLResponse)
async def fragment_incidents():
    """Incidents table fragment."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, target, title, severity, status, created_at FROM ops_incidents ORDER BY created_at DESC LIMIT 5"
        )
        html = (
            "<table><thead><tr><th>ID</th><th>Target</th><th>Title</th>"
            "<th>Severity</th><th>Status</th></tr></thead><tbody>"
        )
        for row in rows:
            html += (
                f"<tr><td><code>{row[0]}</code></td><td>{row[1]}</td>"
                f"<td>{row[2]}</td><td>{_severity_badge(row[3])}</td>"
                f"<td>{_status_badge(row[4])}</td></tr>"
            )
        if not rows:
            html += '<tr><td colspan="5">No incidents</td></tr>'
        html += "</tbody></table>"
        return HTMLResponse(html)
    finally:
        await db.close()


@router.get("/fragment/events", response_class=HTMLResponse)
async def fragment_events():
    """Events table fragment."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, type, target, severity, source, timestamp FROM ops_events ORDER BY timestamp DESC LIMIT 10"
        )
        html = (
            "<table><thead><tr><th>Time</th><th>Type</th><th>Target</th>"
            "<th>Severity</th><th>Source</th></tr></thead><tbody>"
        )
        for row in rows:
            ts = row[5][:19] if row[5] else ""
            html += (
                f"<tr><td>{ts}</td><td>{row[1]}</td><td>{row[2]}</td>"
                f"<td>{_severity_badge(row[3])}</td><td>{row[4]}</td></tr>"
            )
        if not rows:
            html += '<tr><td colspan="5">No events</td></tr>'
        html += "</tbody></table>"
        return HTMLResponse(html)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Incidents page
# ---------------------------------------------------------------------------
@router.get("/incidents", response_class=HTMLResponse)
async def incidents_page():
    """Incident board."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, target, title, severity, status, detected_by, created_at, resolved_at, "
            "resolution_time_minutes FROM ops_incidents ORDER BY created_at DESC LIMIT 50"
        )
        tbody = ""
        for row in rows:
            created = row[6][:16] if row[6] else ""
            resolved = row[7][:16] if row[7] else "-"
            mttr = f"{row[8]}m" if row[8] else "-"
            tbody += (
                f"<tr><td><code>{row[0]}</code></td><td>{row[1]}</td><td>{row[2]}</td>"
                f"<td>{_severity_badge(row[3])}</td><td>{_status_badge(row[4])}</td>"
                f"<td>{row[5]}</td><td>{created}</td><td>{resolved}</td><td>{mttr}</td></tr>"
            )
        if not rows:
            tbody = '<tr><td colspan="9">No incidents recorded</td></tr>'

        content = f"""
        <hgroup><h1>Incidents</h1><p>Detection, investigation, and resolution tracking</p></hgroup>
        <div hx-get="/dashboard/incidents" hx-trigger="every 30s"
             hx-select="table" hx-swap="outerHTML" hx-target="table">
        <table>
            <thead><tr><th>ID</th><th>Target</th><th>Title</th><th>Severity</th><th>Status</th>
            <th>Detected By</th><th>Created</th><th>Resolved</th><th>MTTR</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        </div>"""
        return _page("Incidents", content)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Changes page
# ---------------------------------------------------------------------------
@router.get("/changes", response_class=HTMLResponse)
async def changes_page():
    """Active and recent change windows."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, created_by, status, targets, description, created_at, expires_at, outcome "
            "FROM ops_changes ORDER BY created_at DESC LIMIT 50"
        )
        tbody = ""
        for row in rows:
            targets = ", ".join(json.loads(row[3])) if row[3] else ""
            created = row[5][:16] if row[5] else ""
            expires = row[6][:16] if row[6] else "-"
            tbody += (
                f"<tr><td><code>{row[0][:12]}</code></td><td>{row[1]}</td>"
                f"<td>{_status_badge(row[2])}</td><td>{targets}</td>"
                f"<td>{row[4][:80]}</td><td>{created}</td><td>{expires}</td>"
                f"<td>{row[7] or '-'}</td></tr>"
            )
        if not rows:
            tbody = '<tr><td colspan="8">No changes recorded</td></tr>'

        content = f"""
        <hgroup><h1>Change Windows</h1><p>Active and recent change management records</p></hgroup>
        <table>
            <thead><tr><th>ID</th><th>Created By</th><th>Status</th><th>Targets</th>
            <th>Description</th><th>Created</th><th>Expires</th><th>Outcome</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>"""
        return _page("Changes", content)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Services (CMDB) page
# ---------------------------------------------------------------------------
@router.get("/services", response_class=HTMLResponse)
async def services_page():
    """CMDB service catalog."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT name, host, service_type, critical, dependencies, alert_policy, last_seen "
            "FROM ops_cmdb ORDER BY critical DESC, name"
        )
        tbody = ""
        for row in rows:
            deps = ", ".join(json.loads(row[4])) if row[4] and row[4] != "[]" else "-"
            critical = "Yes" if row[3] else "No"
            last_seen = row[6][:16] if row[6] else "-"
            tbody += (
                f"<tr><td><strong>{row[0]}</strong></td><td>{row[1] or '-'}</td>"
                f"<td>{row[2] or '-'}</td><td>{critical}</td>"
                f"<td>{deps}</td><td>{row[5]}</td><td>{last_seen}</td></tr>"
            )
        if not rows:
            tbody = '<tr><td colspan="7">No services in CMDB</td></tr>'

        content = f"""
        <hgroup><h1>CMDB Services</h1><p>{len(rows)} services registered</p></hgroup>
        <table>
            <thead><tr><th>Name</th><th>Host</th><th>Type</th><th>Critical</th>
            <th>Dependencies</th><th>Alert Policy</th><th>Last Seen</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>"""
        return _page("Services", content)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Events page
# ---------------------------------------------------------------------------
@router.get("/events", response_class=HTMLResponse)
async def events_page():
    """Event stream view."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, timestamp, source, type, target, severity, data "
            "FROM ops_events ORDER BY timestamp DESC LIMIT 100"
        )
        tbody = ""
        for row in rows:
            ts = row[1][:19] if row[1] else ""
            tbody += (
                f"<tr><td>{ts}</td><td>{row[3]}</td><td>{row[4]}</td>"
                f"<td>{_severity_badge(row[5])}</td><td>{row[2]}</td>"
                f"<td><code>{row[0][:12]}</code></td></tr>"
            )
        if not rows:
            tbody = '<tr><td colspan="6">No events</td></tr>'

        content = f"""
        <hgroup><h1>Event Stream</h1><p>Recent operational events</p></hgroup>
        <div hx-get="/dashboard/fragment/events-full" hx-trigger="every 15s" hx-swap="innerHTML">
        <table>
            <thead><tr><th>Time</th><th>Type</th><th>Target</th><th>Severity</th>
            <th>Source</th><th>Event ID</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        </div>"""
        return _page("Events", content)
    finally:
        await db.close()


@router.get("/fragment/events-full", response_class=HTMLResponse)
async def fragment_events_full():
    """Full events table fragment."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, timestamp, source, type, target, severity FROM ops_events ORDER BY timestamp DESC LIMIT 100"
        )
        html = (
            "<table><thead><tr><th>Time</th><th>Type</th><th>Target</th>"
            "<th>Severity</th><th>Source</th><th>Event ID</th></tr></thead><tbody>"
        )
        for row in rows:
            ts = row[1][:19] if row[1] else ""
            html += (
                f"<tr><td>{ts}</td><td>{row[3]}</td><td>{row[4]}</td>"
                f"<td>{_severity_badge(row[5])}</td><td>{row[2]}</td>"
                f"<td><code>{row[0][:12]}</code></td></tr>"
            )
        if not rows:
            html += '<tr><td colspan="6">No events</td></tr>'
        html += "</tbody></table>"
        return HTMLResponse(html)
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Knowledge page
# ---------------------------------------------------------------------------
@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page():
    """Knowledge base browser with search."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, title, source_type, service_type, target, created_at "
            "FROM ops_knowledge ORDER BY created_at DESC LIMIT 50"
        )
        tbody = ""
        for row in rows:
            created = row[5][:16] if row[5] else ""
            tbody += (
                f"<tr><td><code>{row[0]}</code></td><td>{row[1]}</td>"
                f"<td>{row[2]}</td><td>{row[3] or '-'}</td>"
                f"<td>{row[4] or '-'}</td><td>{created}</td></tr>"
            )
        if not rows:
            tbody = '<tr><td colspan="6">No knowledge entries</td></tr>'

        content = f"""
        <hgroup><h1>Knowledge Base</h1><p>Operational memory — past resolutions and patterns</p></hgroup>

        <form hx-get="/dashboard/fragment/knowledge-search" hx-target="#search-results" hx-swap="innerHTML">
            <div class="grid">
                <input type="search" name="q" placeholder="Search knowledge base..." required>
                <button type="submit">Search</button>
            </div>
        </form>
        <div id="search-results"></div>

        <h3>Recent Entries</h3>
        <table>
            <thead><tr><th>ID</th><th>Title</th><th>Source</th><th>Service Type</th>
            <th>Target</th><th>Created</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>"""
        return _page("Knowledge", content)
    finally:
        await db.close()


@router.get("/fragment/knowledge-search", response_class=HTMLResponse)
async def fragment_knowledge_search(q: str = ""):
    """Knowledge search results fragment."""
    if not q.strip():
        return HTMLResponse("<p>Enter a search query above.</p>")

    db = await get_db()
    try:
        # Escape FTS query
        terms = q.replace('"', " ").replace("'", " ").split()
        fts_query = " ".join(terms)
        if not fts_query:
            return HTMLResponse("<p>Invalid query.</p>")

        rows = await db.execute_fetchall(
            """SELECT k.id, k.title, k.content, k.source_type, k.service_type, k.target
               FROM ops_knowledge_fts fts
               JOIN ops_knowledge k ON k.id = fts.knowledge_id
               WHERE ops_knowledge_fts MATCH ?
               ORDER BY fts.rank LIMIT 10""",
            (fts_query,),
        )

        if not rows:
            return HTMLResponse(f"<p>No results for <em>{q}</em></p>")

        html = f"<h4>Results for &ldquo;{q}&rdquo;</h4>"
        for row in rows:
            content_preview = (row[2][:200] + "...") if len(row[2]) > 200 else row[2]
            html += (
                f"<article><header><strong>{row[1]}</strong> "
                f"<small>({row[3]} | {row[4] or 'any'} | {row[5] or 'any'})</small></header>"
                f"<p>{content_preview}</p></article>"
            )
        return HTMLResponse(html)
    finally:
        await db.close()
