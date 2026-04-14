#!/usr/bin/env python3
"""Corvus CLI — command-line interface for the operational governance API.

Usage:
    corvus status <target>         Check target status (GO/CAUTION/STOP)
    corvus blast-radius <service>  Show affected services if this one fails
    corvus deps <service>          Show upstream dependency chain
    corvus context                 Session briefing (24h summary)
    corvus metrics                 Operational metrics dashboard
    corvus incidents list          List open incidents
    corvus incidents create        Create an incident
    corvus changes list            List change windows
    corvus changes create          Declare a change window
    corvus changes close <id>      Close a change window
    corvus events emit             Emit an operational event
    corvus events watch            Watch recent events
    corvus cmdb list               List CMDB services
    corvus cmdb get <name>         Get service details
    corvus problems list           List open problems
    corvus gaps sweep              Run gap detection sweep
    corvus triage <target>         Run triage against a target
    corvus trust list              Show trust ledger
    corvus drift                   Check config drift
    corvus collect                 Trigger connection collection
    corvus graph stats             Graph node/edge counts
    corvus instructions            Print agent instructions

Config:
    CORVUS_URL    Base URL (default: http://localhost:8000)
    CORVUS_TOKEN  API bearer token
    ~/.corvus.yaml  Alternative config file
"""

import json
import os
import sys
from pathlib import Path

try:
    import httpx
    import typer
    import yaml
except ImportError:
    print("Install dependencies: pip install typer httpx pyyaml", file=sys.stderr)
    sys.exit(1)

app = typer.Typer(name="corvus", help="Corvus operational governance CLI.", no_args_is_help=True)
incidents_app = typer.Typer(help="Incident management.")
changes_app = typer.Typer(help="Change window management.")
events_app = typer.Typer(help="Event stream.")
cmdb_app = typer.Typer(help="Configuration management database.")
problems_app = typer.Typer(help="Problem management.")
trust_app = typer.Typer(help="Trust ledger.")

app.add_typer(incidents_app, name="incidents")
app.add_typer(changes_app, name="changes")
app.add_typer(events_app, name="events")
app.add_typer(cmdb_app, name="cmdb")
app.add_typer(problems_app, name="problems")
app.add_typer(trust_app, name="trust")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config() -> dict:
    """Load config from ~/.corvus.yaml or env vars."""
    config = {"url": "http://localhost:8000", "token": ""}

    config_path = Path.home() / ".corvus.yaml"
    if config_path.exists():
        with open(config_path) as f:
            file_cfg = yaml.safe_load(f) or {}
        config["url"] = file_cfg.get("url", config["url"])
        config["token"] = file_cfg.get("token", config["token"])

    # Env vars override file
    config["url"] = os.environ.get("CORVUS_URL", config["url"]).rstrip("/")
    config["token"] = os.environ.get("CORVUS_TOKEN", config["token"])

    return config


def _client() -> httpx.Client:
    """Create an httpx client with auth headers."""
    cfg = _load_config()
    headers = {}
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    return httpx.Client(base_url=cfg["url"], headers=headers, timeout=30)


def _print_json(data, compact: bool = False):
    """Pretty-print JSON response."""
    if compact:
        typer.echo(json.dumps(data, default=str))
    else:
        typer.echo(json.dumps(data, indent=2, default=str))


def _get(path: str, params: dict | None = None):
    """GET request, handle errors."""
    with _client() as c:
        resp = c.get(path, params=params)
        if resp.status_code >= 400:
            typer.echo(f"Error {resp.status_code}: {resp.text}", err=True)
            raise typer.Exit(1)
        return resp.json()


def _post(path: str, json_data: dict | None = None):
    """POST request, handle errors."""
    with _client() as c:
        resp = c.post(path, json=json_data)
        if resp.status_code >= 400:
            typer.echo(f"Error {resp.status_code}: {resp.text}", err=True)
            raise typer.Exit(1)
        return resp.json()


def _patch(path: str, json_data: dict | None = None):
    """PATCH request, handle errors."""
    with _client() as c:
        resp = c.patch(path, json=json_data)
        if resp.status_code >= 400:
            typer.echo(f"Error {resp.status_code}: {resp.text}", err=True)
            raise typer.Exit(1)
        return resp.json()


# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


@app.command()
def status(target: str):
    """Check target status — GO / CAUTION / STOP."""
    data = _get(f"/ops/events/targets/{target}/status")
    signal = data.get("signal", "UNKNOWN")
    color = {"GO": typer.colors.GREEN, "CAUTION": typer.colors.YELLOW, "STOP": typer.colors.RED}
    typer.secho(f"  {signal}", fg=color.get(signal, typer.colors.WHITE), bold=True)

    if data.get("active_changes"):
        typer.echo(f"  Active changes: {len(data['active_changes'])}")
    if data.get("open_incidents"):
        typer.echo(f"  Open incidents: {len(data['open_incidents'])}")
    if data.get("reasons"):
        for reason in data["reasons"]:
            typer.echo(f"  - {reason}")


@app.command("blast-radius")
def blast_radius(service: str):
    """Show downstream services affected if this service fails."""
    data = _get(f"/ops/graph/blast-radius/{service}")
    affected = data.get("affected", [])
    if not affected:
        typer.echo(f"  No downstream dependents for {service}")
        return
    typer.echo(f"  {len(affected)} services affected:")
    for svc in affected:
        depth = svc.get("depth", "?")
        host = svc.get("host", "")
        typer.echo(f"    [{depth}] {svc['name']}" + (f" ({host})" if host else ""))


@app.command()
def deps(service: str):
    """Show upstream dependency chain."""
    data = _get(f"/ops/graph/dependencies/{service}")
    chain = data.get("chain", [])
    if not chain:
        typer.echo(f"  No upstream dependencies for {service}")
        return
    typer.echo(f"  Dependency chain for {service}:")
    for dep in chain:
        depth = dep.get("depth", "?")
        typer.echo(f"    [{depth}] {dep['name']}")


@app.command()
def context():
    """Session briefing — 24h operational summary."""
    data = _get("/ops/events/context")
    typer.secho("=== Corvus Session Briefing ===", bold=True)

    if data.get("active_changes"):
        typer.secho(f"\n  Active Changes: {len(data['active_changes'])}", fg=typer.colors.YELLOW)
        for c in data["active_changes"]:
            typer.echo(f"    {c['id']}: {c.get('description', '')[:60]}")

    if data.get("open_incidents"):
        typer.secho(f"\n  Open Incidents: {len(data['open_incidents'])}", fg=typer.colors.RED)
        for inc in data["open_incidents"]:
            typer.echo(f"    {inc['id']}: {inc.get('title', '')} [{inc.get('severity', '')}]")

    events = data.get("recent_events", [])
    if events:
        typer.echo(f"\n  Recent Events: {len(events)}")
        for evt in events[:10]:
            typer.echo(f"    {evt.get('timestamp', '')[:19]} {evt.get('type', '')} → {evt.get('target', '')}")

    gap_summary = data.get("gap_summary", {})
    if gap_summary.get("total_open_gaps", 0) > 0:
        typer.secho(f"\n  Open Gaps: {gap_summary['total_open_gaps']}", fg=typer.colors.YELLOW)
        for ws, count in gap_summary.get("by_workstream", {}).items():
            typer.echo(f"    {ws}: {count}")

    if not any([data.get("active_changes"), data.get("open_incidents"), events]):
        typer.secho("  All clear. No active incidents or changes.", fg=typer.colors.GREEN)


@app.command()
def metrics():
    """Operational metrics dashboard."""
    data = _get("/ops/metrics")
    _print_json(data)


@app.command()
def triage(
    target: str,
    host: str = typer.Option("", help="Host where target runs"),
    service_type: str = typer.Option("", help="Service type hint"),
):
    """Run triage diagnosis on a target."""
    payload = {"target": target}
    if host:
        payload["host"] = host
    if service_type:
        payload["service_type"] = service_type
    data = _post("/ops/runbooks/steps/triage", json_data=payload)
    _print_json(data)


@app.command()
def drift():
    """Check config drift — declared vs running state."""
    data = _get("/ops/discovery/drift")
    drifts = data.get("drifts", [])
    if not drifts:
        typer.secho("  No config drift detected.", fg=typer.colors.GREEN)
        return
    typer.secho(f"  {len(drifts)} drift(s) detected:", fg=typer.colors.YELLOW)
    for d in drifts:
        typer.echo(f"    {d.get('service', '?')}: {d.get('description', '')}")


@app.command()
def collect():
    """Trigger on-demand connection collection."""
    data = _post("/ops/discovery/collect")
    status_val = data.get("status", "unknown")
    if status_val == "skipped":
        typer.echo(f"  Skipped: {data.get('message', '')}")
    else:
        typer.secho("  Collection complete:", fg=typer.colors.GREEN)
        typer.echo(f"    Hosts: {data.get('hosts', 0)}")
        typer.echo(f"    Resolved: {data.get('resolved', 0)}")
        typer.echo(f"    Edges: {data.get('edges', 0)}")


@app.command()
def instructions():
    """Print agent instructions (Markdown)."""
    cfg = _load_config()
    headers = {}
    if cfg["token"]:
        headers["Authorization"] = f"Bearer {cfg['token']}"
    with httpx.Client(base_url=cfg["url"], headers=headers, timeout=30) as c:
        resp = c.get("/agent-instructions")
        if resp.status_code >= 400:
            typer.echo(f"Error {resp.status_code}: {resp.text}", err=True)
            raise typer.Exit(1)
        typer.echo(resp.text)


@app.command("graph")
def graph_stats():
    """Graph node and edge counts."""
    data = _get("/ops/graph/stats")
    _print_json(data)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@incidents_app.command("list")
def incidents_list(
    status_filter: str = typer.Option("open", "--status", help="Filter: open, resolved, all"),
):
    """List incidents."""
    params = {} if status_filter == "all" else {"status": status_filter}
    data = _get("/ops/incidents", params=params)
    if not data:
        typer.echo("  No incidents.")
        return
    for inc in data:
        sev = inc.get("severity", "?")
        color = typer.colors.RED if sev == "critical" else typer.colors.YELLOW
        typer.secho(f"  {inc['id']}  ", fg=color, nl=False)
        typer.echo(f"{inc.get('title', '')} [{sev}] → {inc.get('target', '')} ({inc.get('status', '')})")


@incidents_app.command("create")
def incidents_create(
    target: str = typer.Option(..., help="Affected target"),
    title: str = typer.Option(..., help="Short incident title"),
    severity: str = typer.Option("warning", help="warning or critical"),
    detected_by: str = typer.Option("corvus-cli", help="Who detected it"),
):
    """Create an incident."""
    data = _post(
        "/ops/incidents",
        json_data={
            "target": target,
            "title": title,
            "severity": severity,
            "detected_by": detected_by,
        },
    )
    typer.secho(f"  Created: {data.get('id', '?')}", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


@changes_app.command("list")
def changes_list(
    status_filter: str = typer.Option("active", "--status", help="Filter: active, completed, all"),
):
    """List change windows."""
    params = {} if status_filter == "all" else {"status": status_filter}
    data = _get("/ops/changes", params=params)
    if not data:
        typer.echo("  No change windows.")
        return
    for ch in data:
        typer.echo(f"  {ch['id']}  {ch.get('description', '')[:60]}  [{ch.get('status', '')}]")
        if ch.get("targets"):
            typer.echo(f"    Targets: {', '.join(ch['targets'])}")


@changes_app.command("create")
def changes_create(
    targets: str = typer.Option(..., help="Comma-separated target names"),
    description: str = typer.Option(..., help="Change description"),
    created_by: str = typer.Option("corvus-cli", help="Who is making the change"),
    duration_minutes: int = typer.Option(60, help="Window duration in minutes"),
):
    """Declare a change window."""
    target_list = [t.strip() for t in targets.split(",")]
    data = _post(
        "/ops/changes",
        json_data={
            "targets": target_list,
            "description": description,
            "created_by": created_by,
            "duration_minutes": duration_minutes,
        },
    )
    typer.secho(f"  Created: {data.get('id', '?')}", fg=typer.colors.GREEN)
    typer.echo(f"  Expires: {data.get('expires_at', '?')}")


@changes_app.command("close")
def changes_close(change_id: str):
    """Close a change window."""
    _patch(f"/ops/changes/{change_id}", json_data={"status": "completed"})
    typer.secho(f"  Closed: {change_id}", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@events_app.command("emit")
def events_emit(
    event_type: str = typer.Option(..., "--type", help="Event type (e.g., change.completed)"),
    target: str = typer.Option(..., help="Target name"),
    source: str = typer.Option("corvus-cli", help="Event source"),
    severity: str = typer.Option("info", help="Event severity"),
    data_json: str = typer.Option("{}", "--data", help="JSON data payload"),
):
    """Emit an operational event."""
    try:
        extra_data = json.loads(data_json)
    except json.JSONDecodeError as err:
        typer.echo("Error: --data must be valid JSON", err=True)
        raise typer.Exit(1) from err

    result = _post(
        "/ops/events",
        json_data={
            "type": event_type,
            "target": target,
            "source": source,
            "severity": severity,
            "data": extra_data,
        },
    )
    typer.secho(f"  Emitted: {result.get('id', '?')}", fg=typer.colors.GREEN)


@events_app.command("watch")
def events_watch(
    since: str = typer.Option("24h", help="Time window (e.g., 1h, 24h, 7d)"),
    severity: str = typer.Option("", help="Minimum severity filter"),
    limit: int = typer.Option(20, help="Max events to show"),
):
    """Watch recent events."""
    params = {"limit": limit}
    if severity:
        params["min_severity"] = severity
    data = _get("/ops/events", params=params)
    if not data:
        typer.echo("  No events.")
        return
    for evt in data[:limit]:
        ts = evt.get("timestamp", "")[:19]
        typer.echo(f"  {ts}  {evt.get('type', '?'):30s}  {evt.get('target', ''):20s}  [{evt.get('severity', '')}]")


# ---------------------------------------------------------------------------
# CMDB
# ---------------------------------------------------------------------------


@cmdb_app.command("list")
def cmdb_list(
    service_type: str = typer.Option("", "--type", help="Filter by service type"),
    host: str = typer.Option("", help="Filter by host"),
):
    """List CMDB services."""
    params = {}
    if service_type:
        params["service_type"] = service_type
    if host:
        params["host"] = host
    data = _get("/ops/cmdb", params=params)
    if not data:
        typer.echo("  No services.")
        return
    typer.echo(f"  {len(data)} services:")
    for svc in data:
        critical = " *" if svc.get("critical") else ""
        typer.echo(f"    {svc['name']:30s}  {svc.get('service_type', '?'):12s}  {svc.get('host', ''):15s}{critical}")


@cmdb_app.command("get")
def cmdb_get(name: str):
    """Get service details from CMDB."""
    data = _get(f"/ops/cmdb/{name}")
    _print_json(data)


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------


@problems_app.command("list")
def problems_list(
    status_filter: str = typer.Option("identified", "--status", help="Filter: identified, resolved, all"),
):
    """List problems."""
    params = {} if status_filter == "all" else {"status": status_filter}
    data = _get("/ops/problems", params=params)
    if not data:
        typer.echo("  No problems.")
        return
    for p in data:
        ws = p.get("workstream", "?")
        typer.echo(f"  {p['id']}  [{ws}]  {p.get('title', '')[:60]}")


# ---------------------------------------------------------------------------
# Gaps
# ---------------------------------------------------------------------------


@app.command("gaps")
def gaps_sweep():
    """Run gap detection sweep."""
    data = _post("/ops/gaps/sweep")
    total = data.get("total_new_gaps", 0)
    if total == 0:
        typer.secho("  No new gaps detected.", fg=typer.colors.GREEN)
    else:
        typer.secho(f"  {total} new gap(s) detected:", fg=typer.colors.YELLOW)
    for key, val in data.items():
        if key not in ("total_new_gaps",):
            typer.echo(f"    {key}: {val}")


# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------


@trust_app.command("list")
def trust_list():
    """Show trust ledger."""
    data = _get("/ops/trust")
    if not data:
        typer.echo("  Trust ledger empty.")
        return
    typer.echo(f"  {'Action Type':40s}  {'Tier':12s}  {'Total':>6s}  {'Success':>8s}  {'Rate':>6s}")
    typer.echo(f"  {'─' * 40}  {'─' * 12}  {'─' * 6}  {'─' * 8}  {'─' * 6}")
    for entry in data:
        total = entry.get("total_count", 0)
        success = entry.get("success_count", 0)
        rate = f"{success / total * 100:.0f}%" if total > 0 else "N/A"
        tier = entry.get("trust_tier", "?")
        color = {"AUTO": typer.colors.GREEN, "SUPERVISED": typer.colors.YELLOW}.get(tier, typer.colors.WHITE)
        typer.echo(f"  {entry['action_type']:40s}  ", nl=False)
        typer.secho(f"{tier:12s}", fg=color, nl=False)
        typer.echo(f"  {total:>6d}  {success:>8d}  {rate:>6s}")


@trust_app.command("get")
def trust_get(action_type: str):
    """Get trust tier for a specific action type."""
    data = _get(f"/ops/trust/{action_type}")
    _print_json(data)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
