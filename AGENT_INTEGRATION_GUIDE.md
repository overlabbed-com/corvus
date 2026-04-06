# Agent Integration Guide - Corvus

This document describes how to connect AI agents to Corvus for operational governance.

## Overview

Corvus provides two integration methods:

1. **REST API** - Direct HTTP calls for event emission, incident creation, etc.
2. **MCP Server** - Model Context Protocol for seamless Claude Code integration

## REST API Integration

### Authentication

All `/ops/` endpoints require API key authentication via Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" https://corvus.themillertribe-int.org/ops/events
```

### API Key Roles

| Role | Permissions | Use Case |
|------|-------------|----------|
| `admin` | Full access | Human operators, emergency access |
| `ops-write` | Create changes, incidents, events | Autonomous agents (NemoClaw, Claude Code) |
| `ops-read` | Read-only | Monitoring dashboards, auditors |
| `agent` | Scoped to event emission, triage | Lightweight agent integrations |

### Core Endpoints

#### Emit an Event
```bash
POST /ops/events
{
  "source": "claude-code",
  "type": "change.started",
  "target": "vllm-primary",
  "severity": "info",
  "data": {"summary": "Deploying security patch"},
  "related_change_id": "CHG-ABC123"
}
```

#### Create an Incident
```bash
POST /ops/incidents
{
  "target": "vllm-primary",
  "title": "CUDA OOM on GPU 0",
  "severity": "high",
  "detected_by": "claude-code"
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
        "HTTP_URL": "https://corvus.themillertribe-int.org/ops/mcp/sse",
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

- `corvus_check_target(target)` - Pre-action conflict check
- `corvus_emit_event(...)` - Emit operational events
- `corvus_create_incident(...)` - Create incident records
- `corvus_create_change(...)` - Declare change windows
- `corvus_close_change(...)` - Close change windows
- `corvus_get_context()` - Session briefing (last 24h events)
- `corvus_watch_events(...)` - Watch for other agent activity
- `corvus_blast_radius(service)` - Dependency impact analysis
- `corvus_dependency_chain(service)` - Upstream dependencies
- `corvus_triage(target)` - Execute runbook triage
- `corvus_get_service(name)` - CMDB service details
- `corvus_list_services(...)` - List registered services
- `corvus_register_service(...)` - Register new service
- `corvus_correlated_gpu(host)` - GPU incident correlation
- `corvus_expiring_cis(...)` - List expiring configuration items

### Example: Using Corvus MCP Tools

```python
# Before any infrastructure action
status = corvus_check_target(target="vllm-primary")
if status.recommendation == "STOP":
    print(f"Cannot proceed: {status.reason}")
    return

# Declare change window
change = corvus_create_change(
    targets=["vllm-primary"],
    description="Deploying security patch",
    rollback_plan="Revert to previous image tag"
)

# Emit event
corvus_emit_event(
    source="claude-code",
    type="change.started",
    target="vllm-primary",
    related_change_id=change.id
)

# ... perform work ...

# Close change window
corvus_close_change(change_id=change.id, success=True, notes="Deploy successful")
```

## Agent-Specific Guides

### Claude Code

1. Generate API key: `openssl rand -hex 32`
2. Register key in Corvus: `CORVUS_API_KEYS=claude-code:agent:ops-write`
3. Add MCP server to `.claude/settings.json` (see above)
4. Verify connection: `corvus_get_context()`

### NemoClaw

NemoClaw uses the same MCP integration. Key differences:

- Role: `ops-write` (can create changes and incidents)
- Always checks `corvus_check_target()` before infrastructure actions
- Emits events for all state-changing operations
- Watches `corvus_watch_events()` for Claude Code activity

### Custom Agents

For custom agents, use the REST API:

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

## Troubleshooting

### Connection Issues

```bash
# Test endpoint
curl -H "Authorization: Bearer YOUR_KEY" https://corvus.themillertribe-int.org/health

# Check MCP connection
npx -y @modelcontextprotocol/client https://corvus.themillertribe-int.org/ops/mcp/sse
```

### Authentication Errors

- Verify API key is correct
- Check role permissions match intended actions
- Ensure `Authorization: Bearer` prefix is included

### Rate Limiting

Default: 500 requests/minute per IP. Exceeding this returns 429.

Increase limit by configuring `slowapi` in Corvus server if needed.
