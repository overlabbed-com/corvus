# Corvus Agent Integration Layer — Architect Design

> **Date**: 2026-03-30
> **Agent**: Architect
> **Status**: Approved
> **Trigger**: Agent hooks not in place -- need agent-agnostic integration layer

## Problem Statement

Corvus is live with Neo4j graph (157 nodes, 346 edges) and ops-agent consuming it.
But Claude Code still uses static markdown governance rules and admin-api MCP tools.
OpenCode, Aider, and future agents have no integration path at all.

Corvus is the agentic operational intelligence layer. Every agent should consume it
through the same contract — not agent-specific integrations maintained separately.

## Design Principle

**One OpenAPI spec, auto-generate everything.** Add an endpoint to Corvus, all
integration layers update automatically. No per-agent maintenance.

## Architecture

Corvus server becomes a polyglot endpoint — one container serves four protocols:

```
                    ┌─────────────────────────┐
                    │     Corvus Server        │
                    │                          │
  MCP agents ─────► │  /mcp (SSE transport)    │ ◄── MCP protocol
                    │                          │
  Any HTTP agent ──►│  /ops/* (REST API)       │ ◄── HTTP/JSON
                    │                          │
  Shell/CLI ──────► │  corvus CLI              │ ◄── Generated from OpenAPI
                    │                          │
  Any LLM agent ──► │  /agent-instructions     │ ◄── Self-describing docs
                    │                          │
                    │  /openapi.json            │ ◄── Source of truth
                    └─────────────────────────┘
```

### Output 1: Built-in MCP Server

Corvus serves MCP tools via SSE transport from the same FastAPI process.
No separate container, no bridge. Any MCP-capable agent connects by adding Corvus to its
MCP config -- same as any other MCP server.

**MCP Tool Mapping:**

| MCP Tool | API Endpoint | Purpose |
|----------|-------------|---------|
| `corvus_blast_radius` | `GET /ops/graph/blast-radius/{svc}` | What breaks if this goes down |
| `corvus_dependency_chain` | `GET /ops/graph/dependency-chain/{svc}` | Full upstream dependency path |
| `corvus_triage` | `POST /ops/runbooks/triage` | Submit evidence, get runbook diagnosis |
| `corvus_check_target` | `GET /ops/events/targets/{target}/status` | GO/CAUTION/STOP recommendation |
| `corvus_create_incident` | `POST /ops/incidents` | Create incident record |
| `corvus_emit_event` | `POST /ops/events` | Emit operational event |
| `corvus_get_service` | `GET /ops/cmdb/{name}` | Service metadata (type, deps, baselines) |
| `corvus_expiring_cis` | `GET /ops/graph/expiring` | CIs expiring within N days |
| `corvus_correlated_gpu` | `GET /ops/graph/correlated/{host}/{gpu}` | Services sharing a GPU |
| `corvus_graph_stats` | `GET /ops/graph/stats` | Node/edge counts |
| `corvus_discovery_bootstrap` | `POST /ops/discovery/bootstrap` | Trigger full discovery |
| `corvus_discovery_coverage` | `GET /ops/discovery/coverage` | Coverage gaps report |
| `corvus_create_change` | `POST /ops/changes` | Declare change window |
| `corvus_close_change` | `PATCH /ops/changes/{id}` | Close change window |
| `corvus_watch_events` | `GET /ops/events` | Recent events (with filters) |
| `corvus_list_incidents` | `GET /ops/incidents` | List incidents (with filters) |
| `corvus_get_context` | `GET /ops/events/context` | Session briefing (last 24h) |

Implementation: Use the `mcp` Python library (already in requirements.txt).
FastAPI serves the MCP SSE endpoint at `/mcp`. Tool definitions auto-generated
from a registry that maps API endpoints to MCP tool schemas.

### Output 2: CLI Tool

Generated from OpenAPI spec. Installable via pip.

```bash
# Examples
corvus blast-radius caddy
corvus triage vllm-primary --host host-01 --evidence '{"exit_code": 137}'
corvus check-target litellm
corvus incidents --status open
corvus graph stats
corvus expiring --days 30
corvus discovery coverage
```

Implementation: `corvus-cli/` directory in the repo. Uses `typer` (already
common in the ecosystem). Commands generated from OpenAPI operation IDs.
Config via `~/.corvus.yaml` or env vars (`CORVUS_URL`, `CORVUS_API_KEY`).

### Output 3: Python SDK

What ops-agent's `corvus_client.py` already is -- but auto-generated, published,
and version-tracked.

```python
from corvus import CorvusClient

async with CorvusClient("https://corvus.example.com", api_key="...") as client:
    # Graph queries
    blast = await client.blast_radius("caddy")
    chain = await client.dependency_chain("sonarr")
    expiring = await client.expiring_cis(days=30)

    # Triage
    diagnosis = await client.triage(
        target="vllm-primary",
        host="host-01",
        service_type="inference",
        evidence={"exit_code": 137, "error_lines": ["CUDA OOM..."]}
    )

    # SOP
    await client.create_incident(target="caddy", title="502s", severity="high")
    await client.emit_event(source="my-agent", type="change.started", target="caddy")
```

Implementation: `corvus-sdk/` directory. Dataclasses generated from OpenAPI
schemas. Async httpx client. Publishable to PyPI as `corvus-sdk`.

### Output 4: Agent Instructions Endpoint

`GET /agent-instructions` returns a markdown document that any LLM can read
at session start to learn how to operate Corvus.

```markdown
# Corvus Operational Intelligence — Agent Instructions

You have access to Corvus at {base_url}. Use these endpoints for operational
decisions. Always include `Authorization: Bearer {token}` header.

## Before Making Changes
Call `GET /ops/events/targets/{target}/status` to check for conflicts.
Response: {"recommendation": "GO|CAUTION|STOP", "reason": "..."}

## Before Restarting Services
Call `GET /ops/graph/blast-radius/{service}` to understand impact.
Response: {"affected_count": N, "affected": [...]}

## When Investigating Failures
Call `POST /ops/runbooks/triage` with evidence:
{example request/response}

## Available Operations
{auto-generated from OpenAPI}
```

The instructions are dynamic — they reflect the current OpenAPI spec. Add an
endpoint, the instructions update.

### Code Generation Pipeline

```
corvus-server/src/app.py
    │
    ▼
FastAPI auto-generates /openapi.json
    │
    ▼
corvus-codegen (Python script)
    ├── reads /openapi.json
    ├── generates: corvus-server/src/mcp_tools.py (MCP tool definitions)
    ├── generates: corvus-cli/corvus_cli/commands.py (CLI commands)
    ├── generates: corvus-sdk/corvus/client.py (Python SDK)
    └── generates: corvus-server/templates/agent_instructions.md (instruction doc)
```

Run `python corvus-codegen.py` after adding/modifying endpoints. CI can
verify generated code matches the spec (fail if drift detected).

## Migration Path

### Phase 1: MCP Server (embedded in Corvus)
- Add MCP SSE endpoint to Corvus FastAPI app
- Register all existing API endpoints as MCP tools
- Agent adds Corvus to MCP config
- Agent governance rules updated to prefer `corvus_*` tools over `admin_api_ops_*`

### Phase 2: CLI
- Generate CLI from OpenAPI
- Publish as `corvus-cli` (pip installable)
- Shell-based agents and humans get quick access

### Phase 3: SDK + Agent Instructions
- Extract ops-agent's CorvusClient into published SDK
- Build agent-instructions endpoint
- Update agent governance rules to reference Corvus instructions

### Phase 4: Codegen Pipeline
- Build `corvus-codegen` script
- Add CI check: generated code matches spec
- Add to developer workflow: new endpoint → run codegen → commit

## Risk Assessment

| Risk | Blast Radius | Reversibility | Mitigation |
|------|-------------|---------------|------------|
| MCP server adds complexity to Corvus | Contained | Easy (disable MCP route) | Feature flag: `CORVUS_MCP_ENABLED` |
| Codegen drift | None (CI catches it) | Trivial | CI check on every PR |
| Agent instructions stale | Contained | Auto (regenerated from spec) | Dynamic endpoint, not static file |

## Rollback Plan

Each phase is independently reversible:
- Phase 1: Remove `/mcp` route, agents fall back to admin-api tools
- Phase 2: CLI is a separate package, uninstall to remove
- Phase 3: SDK is a separate package; agent instructions endpoint returns 404 if disabled
- Phase 4: Codegen is a dev tool, not runtime — removing it just means manual updates
