"""Corvus CLI — operational governance from the terminal.

Usage:
    corvus check-target caddy
    corvus blast-radius caddy
    corvus context
    corvus incidents --status open
    corvus emit-event --source my-agent --type change.started --target proxy
    corvus triage my-service --service-type inference
"""

from __future__ import annotations

import json
from typing import Annotated, Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from corvus_cli.config import get_base_url, get_token

app = typer.Typer(name="corvus", help="Corvus operational governance CLI")
console = Console()


def _client() -> httpx.Client:
    """Create an HTTP client with auth."""
    token = get_token()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=get_base_url(), headers=headers, timeout=30)


def _request(method: str, path: str, **kwargs) -> dict:
    """Make a request and handle errors."""
    with _client() as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            console.print(f"[red]Error {resp.status_code}[/red]: {resp.text}")
            raise typer.Exit(1)
        return resp.json()


def _print_json(data) -> None:
    """Pretty-print JSON data."""
    console.print_json(json.dumps(data, indent=2, default=str))


# -- Pre-action checks --


@app.command()
def check_target(target: str):
    """Check target for conflicts before modifying (GO/CAUTION/STOP)."""
    data = _request("GET", f"/ops/events/targets/{target}/status")
    rec = data.get("recommendation", "UNKNOWN")
    color = {"GO": "green", "CAUTION": "yellow", "STOP": "red"}.get(rec, "white")
    console.print(f"[{color} bold]{rec}[/{color} bold] — {target}")
    if data.get("active_changes"):
        console.print(f"  Active changes: {len(data['active_changes'])}")
    if data.get("recent_incidents"):
        console.print(f"  Recent incidents: {len(data['recent_incidents'])}")


@app.command()
def blast_radius(service: str):
    """Show blast radius — what breaks if this service goes down."""
    data = _request("GET", f"/ops/graph/blast-radius/{service}")
    affected = data.get("affected", [])
    if not affected:
        console.print(f"[green]{service}[/green]: No downstream dependencies found")
        return
    table = Table(title=f"Blast Radius: {service}")
    table.add_column("Service")
    table.add_column("Host")
    table.add_column("Depth")
    for svc in affected:
        table.add_row(svc.get("name", "?"), svc.get("host", "?"), str(svc.get("depth", "?")))
    console.print(table)


@app.command()
def dependency_chain(service: str):
    """Show upstream dependency chain for a service."""
    data = _request("GET", f"/ops/graph/dependency-chain/{service}")
    _print_json(data)


# -- Context / Briefing --


@app.command()
def context():
    """Get 24h session briefing — events, incidents, changes, gaps."""
    data = _request("GET", "/ops/events/context")
    events = data.get("events_24h", [])
    incidents = data.get("active_incidents", [])
    changes = data.get("active_changes", [])
    gaps = data.get("gaps", {})

    console.print(f"[bold]Events (24h):[/bold] {len(events)}")
    console.print(f"[bold]Active incidents:[/bold] {len(incidents)}")
    console.print(f"[bold]Active changes:[/bold] {len(changes)}")
    console.print(f"[bold]Open gaps:[/bold] {gaps.get('total_open_gaps', 0)}")

    if incidents:
        table = Table(title="Active Incidents")
        table.add_column("ID")
        table.add_column("Target")
        table.add_column("Severity")
        table.add_column("Title")
        for inc in incidents:
            table.add_row(inc["id"], inc["target"], inc["severity"], inc["title"])
        console.print(table)


# -- Changes --


@app.command()
def create_change(
    targets: Annotated[str, typer.Argument(help="Comma-separated target names")],
    description: Annotated[str, typer.Option("--desc", "-d")],
    operator: str = "corvus-cli",
    rollback: str = "",
    project: str = "",
):
    """Declare a change window."""
    target_list = [t.strip() for t in targets.split(",")]
    data = _request(
        "POST",
        "/ops/changes",
        json={
            "targets": target_list,
            "description": description,
            "created_by": operator,
            "rollback_plan": rollback,
            "project": project,
        },
    )
    console.print(f"[green]Change created:[/green] {data['id']}")


@app.command()
def close_change(
    change_id: str,
    outcome: str = "completed",
):
    """Close a change window."""
    _request("PATCH", f"/ops/changes/{change_id}", json={"status": "completed", "outcome": outcome})
    console.print(f"[green]Change closed:[/green] {change_id}")


@app.command()
def changes():
    """List active change windows."""
    data = _request("GET", "/ops/changes/active")
    if not data:
        console.print("No active changes")
        return
    table = Table(title="Active Changes")
    table.add_column("ID")
    table.add_column("Targets")
    table.add_column("Description")
    table.add_column("Created By")
    for c in data:
        targets = c.get("targets", "[]")
        if isinstance(targets, str):
            targets = json.loads(targets)
        table.add_row(c["id"], ", ".join(targets), c["description"][:50], c["created_by"])
    console.print(table)


# -- Events --


@app.command()
def emit_event(
    source: Annotated[str, typer.Option("--source", "-s")],
    event_type: Annotated[str, typer.Option("--type", "-t")],
    target: str = "",
    severity: str = "info",
):
    """Emit an operational event."""
    data = _request(
        "POST",
        "/ops/events",
        json={"source": source, "type": event_type, "target": target, "severity": severity, "data": {}},
    )
    console.print(f"[green]Event emitted:[/green] {data['id']}")


# -- Incidents --


@app.command()
def incidents(
    status: Optional[str] = None,
    target: Optional[str] = None,
    severity: Optional[str] = None,
):
    """List incidents."""
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    if target:
        params["target"] = target
    if severity:
        params["severity"] = severity
    data = _request("GET", "/ops/incidents", params=params)
    if not data:
        console.print("No incidents found")
        return
    table = Table(title="Incidents")
    table.add_column("ID")
    table.add_column("Target")
    table.add_column("Severity")
    table.add_column("Status")
    table.add_column("Title")
    for inc in data:
        table.add_row(inc["id"], inc["target"], inc["severity"], inc["status"], inc["title"][:50])
    console.print(table)


@app.command()
def create_incident(
    target: str,
    title: Annotated[str, typer.Option("--title", "-t")],
    description: str = "",
    severity: str = "warning",
    detected_by: str = "corvus-cli",
):
    """Create an incident record."""
    data = _request(
        "POST",
        "/ops/incidents",
        json={
            "target": target,
            "title": title,
            "description": description,
            "severity": severity,
            "detected_by": detected_by,
        },
    )
    console.print(f"[green]Incident created:[/green] {data['id']}")


# -- CMDB --


@app.command()
def services(
    service_type: Optional[str] = None,
    host: Optional[str] = None,
):
    """List CMDB services."""
    params: dict[str, str] = {}
    if service_type:
        params["service_type"] = service_type
    if host:
        params["host"] = host
    data = _request("GET", "/ops/cmdb", params=params)
    if not data:
        console.print("No services found")
        return
    table = Table(title="Services")
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Host")
    table.add_column("Critical")
    for svc in data:
        crit = "🔴" if svc.get("critical") else ""
        table.add_row(svc["name"], svc.get("service_type", "-"), svc.get("host", "-"), crit)
    console.print(table)


@app.command()
def service(name: str):
    """Get details for a specific service."""
    data = _request("GET", f"/ops/cmdb/{name}")
    _print_json(data)


# -- Triage --


@app.command()
def triage(
    target: str,
    host: str = "",
    service_type: Optional[str] = None,
):
    """Run triage for a target."""
    data = _request(
        "POST",
        "/ops/runbooks/triage",
        json={"target": target, "host": host, "service_type": service_type},
    )
    status = data.get("status", "unknown")
    color = "green" if status == "triaged" else "yellow"
    console.print(f"[{color}]{status}[/{color}] — {data.get('triage_id', '?')}")
    if data.get("diagnosis"):
        console.print(f"  Diagnosis: {data['diagnosis']}")
    if data.get("confidence"):
        console.print(f"  Confidence: {data['confidence']:.0%}")
    if data.get("escalation_required"):
        console.print("[red]  ⚠ Escalation required[/red]")


# -- Metrics --


@app.command()
def metrics():
    """Show operational dashboard metrics."""
    data = _request("GET", "/ops/metrics")
    console.print(f"Events (24h): {data.get('events_24h', 0)}")
    console.print(f"Open incidents: {data.get('open_incidents', 0)}")
    console.print(f"Active changes: {data.get('active_changes', 0)}")
    console.print(f"FP rate: {data.get('false_positive_rate', 0)}%")
    console.print(f"Compliance rate: {data.get('compliance_rate', 0)}%")
    console.print(f"Total services: {data.get('total_services', 0)}")


@app.command()
def gaps():
    """Show open operational gaps."""
    data = _request("GET", "/ops/gaps")
    total = data.get("total_open_gaps", 0)
    console.print(f"[bold]Open gaps:[/bold] {total}")
    by_ws = data.get("by_workstream", {})
    if by_ws:
        for ws, count in by_ws.items():
            console.print(f"  {ws}: {count}")


@app.command()
def signal_quality(days: int = 7):
    """Show signal quality / false positive stats."""
    data = _request("GET", "/ops/signal-quality", params={"days": days})
    console.print(f"Total resolved ({days}d): {data.get('total_resolved', 0)}")
    console.print(f"False positives: {data.get('false_positives', 0)}")
    console.print(f"FP rate: {data.get('false_positive_rate', 0)}%")


if __name__ == "__main__":
    app()
