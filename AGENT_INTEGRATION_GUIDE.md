# Agent Integration Guide

How to connect AI agents to Corvus for operational governance.

## Overview

Corvus provides two integration methods:

1. **REST API** — Direct HTTP calls for any agent that speaks HTTP
2. **MCP Server** — Model Context Protocol for Claude Code and compatible agents

## REST API Integration

### Authentication

All `/ops/` endpoints require API key authentication via Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" http://corvus:8000/ops/events
```

### API Key Roles

| Role | Permissions | Use Case |
|------|-------------|----------|
| `admin` | Full access | Human operators, emergency access |
| `ops-write` | Create changes, incidents, events | Autonomous agents |
| `ops-read` | Read-only | Monitoring dashboards, auditors |
| `agent` | Scoped to event emission, triage | Lightweight integrations |

### Core Endpoints

#### Emit an Event
```bash
POST /ops/events
{
  "source": "my-agent",
  "type": "change.started",
  "target": "web-server",
  "severity": "info",
  "data": {"summary": "Deploying security patch"},
  "related_change_id": "CHG-ABC123"
}
```

#### Create an Incident
```bash
POST /ops/incidents
{
  "target": "web-server",
  "title": "Service unhealthy after deploy",
  "severity": "high",
  "detected_by": "my-agent"
}
```

#### Pre-Action Conflict Check
```bash
GET /ops/events/targets/{target}/status
# Returns: GO, CAUTION, or STOP
```

#### List Services (CMDB)
```bash
GET /ops/cmdb?service_type=inference
```

## MCP Server Integration

### For Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "corvus": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-http"],
      "env": {
        "HTTP_URL": "http://corvus:8000/ops/mcp/sse",
        "HTTP_HEADERS": {
          "Authorization": "Bearer YOUR_CORVUS_API_KEY"
        }
      }
    }
  }
}
```

### Available MCP Tools

Once connected, agents have access to:

| Tool | Purpose |
|------|---------|
| `corvus_check_target(target)` | Pre-action conflict check |
| `corvus_emit_event(...)` | Emit operational events |
| `corvus_create_incident(...)` | Create incident records |
| `corvus_create_change(...)` | Declare change windows |
| `corvus_close_change(...)` | Close change windows |
| `corvus_get_context()` | Session briefing (last 24h events) |
| `corvus_watch_events(...)` | Watch for other agent activity |
| `corvus_blast_radius(service)` | Dependency impact analysis |
| `corvus_dependency_chain(service)` | Upstream dependencies |
| `corvus_triage(target)` | Execute runbook triage |
| `corvus_get_service(name)` | CMDB service details |
| `corvus_list_services(...)` | List registered services |
| `corvus_register_service(...)` | Register new service |
| `corvus_correlated_gpu(host)` | GPU incident correlation |
| `corvus_expiring_cis(...)` | List expiring configuration items |

### Example: Agent Workflow

```python
# Before any infrastructure action
status = corvus_check_target(target="web-server")
if status.recommendation == "STOP":
    print(f"Cannot proceed: {status.reason}")
    return

# Declare change window
change = corvus_create_change(
    targets=["web-server"],
    description="Deploying security patch",
    rollback_plan="Revert to previous image tag"
)

# Emit event
corvus_emit_event(
    source="my-agent",
    type="change.started",
    target="web-server",
    related_change_id=change.id
)

# ... perform work ...

# Close change window
corvus_close_change(change_id=change.id, success=True, notes="Deploy successful")
```

## Custom Agent Integration

For agents that don't support MCP, use the REST API directly:

```python
import httpx

class CorvusClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def emit_event(self, event: dict):
        response = httpx.post(
            f"{self.base_url}/ops/events",
            json=event,
            headers=self.headers
        )
        return response.json()

    def check_target(self, target: str):
        response = httpx.get(
            f"{self.base_url}/ops/events/targets/{target}/status",
            headers=self.headers
        )
        return response.json()
```

Or use the [Python SDK](corvus-sdk/) (early stage).

## Troubleshooting

### Connection Issues

```bash
# Test endpoint
curl -H "Authorization: Bearer YOUR_KEY" http://corvus:8000/health

# Check MCP connection
npx -y @modelcontextprotocol/client http://corvus:8000/ops/mcp/sse
```

### Authentication Errors

- Verify API key is correct
- Check role permissions match intended actions
- Ensure `Authorization: Bearer` prefix is included

### Rate Limiting

Default: 500 requests/minute per IP. Exceeding this returns 429.
