# Corvus

**Operational governance for AI agent fleets.**

Corvus gives your AI agents a shared operational picture. When one agent acts, the others know. When something breaks, the right investigation fires. When an auditor asks "what happened?" the evidence chain is already there.

## The Problem

AI agents operating infrastructure have no shared awareness. Agent A restarts a container. Agent B detects the restart as a failure and alerts. The human becomes the message bus between their own AI tools.

Corvus solves this with a single deployment that provides shared state, structured events, service-aware triage, and operational memory for any agent that speaks HTTP.

## What's In the Box

### Core

| Capability | What It Does |
|-----------|--------------|
| **Shared Ops State** | Changes, incidents, problems, CMDB. One source of truth for all agents |
| **Event Protocol** | OCSF 1.3.0 native. Every action is structured, timestamped, and SIEM-portable |
| **FMEA Runbooks** | Service-type-aware triage via failure mode analysis. 13 service types covered |
| **Knowledge Management** | FTS-backed operational memory. Agents learn from every resolution |
| **Blind Spot Detection** | The system knows what it doesn't know and generates its own improvement backlog |
| **Conflict Check** | Before any agent acts, check if another agent is already working on the same target |
| **Dependency Graph** | Neo4j-backed service topology. Blast radius and dependency chain queries |
| **Trust Ledger** | Track agent reliability per action type. Promote/demote autonomy based on outcomes |

### SIEM Forwarding

Every event is transformed to OCSF 1.3.0 and forwarded to your SIEM:

| Adapter | Status |
|---------|--------|
| **Splunk HEC** | Tested in production |
| Azure Sentinel | Implemented, not yet production-tested |
| Google Chronicle | Implemented, not yet production-tested |
| Elasticsearch | Implemented, not yet production-tested |

### Extensible Modules

Corvus has a module system for governance frameworks and compliance controls. A SOC 2 module ships as a reference implementation. Additional modules (ITIL, NIST CSF, ISO 27001) are on the roadmap.

## Architecture

```
               Your Agents
  ┌─────────┐  ┌─────────┐  ┌─────────┐
  │ Claude  │  │ CrewAI  │  │ Custom  │
  │  Code   │  │  Agent  │  │  Agent  │
  └────┬────┘  └────┬────┘  └────┬────┘
       │            │            │
       └────────────┴─────┬──────┘
                          │ REST API + MCP
                   ┌──────┴──────┐
                   │   Corvus    │
                   │   Server    │
                   │             │
                   │  Ops State  │  Changes, incidents, CMDB
                   │  OCSF       │  Event transformation
                   │  Runbooks   │  FMEA triage engine
                   │  Knowledge  │  Operational memory
                   │  Graph      │  Service topology (Neo4j)
                   └──────┬──────┘
                          │
             ┌────────────┼────────────┐
             │            │            │
        ┌────┴────┐  ┌───┴───┐  ┌────┴─────┐
        │  Your   │  │ Your  │  │  Your    │
        │  SIEM   │  │ LLM   │  │ Tickets  │
        └─────────┘  └───────┘  └──────────┘
```

## Quick Start

### Docker Compose (recommended)

```yaml
services:
  corvus:
    build: ./corvus-server
    ports:
      - "8000:8000"
    environment:
      - CORVUS_API_KEYS=my-agent:$(openssl rand -hex 32)
      - NEO4J_URI=bolt://corvus-neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=changeme
    volumes:
      - corvus-data:/data
    depends_on:
      corvus-neo4j:
        condition: service_healthy

  corvus-neo4j:
    image: neo4j:5-community
    environment:
      - NEO4J_AUTH=neo4j/changeme
    volumes:
      - neo4j-data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://127.0.0.1:7474 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

volumes:
  corvus-data:
  neo4j-data:
```

### Local Development

```bash
cd corvus-server
pip install -r requirements.txt
CORVUS_DEV_MODE=true uvicorn src.app:app --reload --port 8000
```

Dev mode disables authentication for local testing. Never use it in production.

### Connect an Agent

```bash
# Emit an event
curl -X POST http://localhost:8000/ops/events \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "my-agent",
    "type": "change.started",
    "target": "my-service",
    "severity": "info",
    "data": {"summary": "Deploying update"}
  }'

# Check for conflicts before acting
curl "http://localhost:8000/ops/events/targets/my-service/status" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

See [AGENT_INTEGRATION_GUIDE.md](AGENT_INTEGRATION_GUIDE.md) for full integration docs.

## API Surface

| Area | Key Endpoints |
|------|---------------|
| Events | `POST /ops/events`, `GET /ops/events`, `GET /ops/events/context` |
| Incidents | `POST /ops/incidents`, `GET /ops/incidents` |
| Changes | `POST /ops/changes`, `GET /ops/changes` |
| Problems | `POST /ops/problems`, `GET /ops/problems` |
| CMDB | `POST /ops/cmdb/register`, `GET /ops/cmdb`, `POST /ops/cmdb/bulk-sync` |
| Runbooks | `GET /ops/runbooks`, `POST /ops/runbooks/triage` |
| Discovery | `POST /ops/discovery/bootstrap`, `GET /ops/discovery/status` |
| Knowledge | `POST /ops/knowledge`, `GET /ops/knowledge/search` |
| Graph | `POST /ops/graph/queries`, `GET /ops/graph/services/{name}` |
| Metrics | `GET /ops/metrics` |
| Health | `GET /health` |

Full OpenAPI spec available at `/docs` when running.

## Project Structure

```
corvus/
├── corvus-server/        # The server (FastAPI)
│   ├── src/              # Application code
│   ├── runbooks/         # FMEA triage runbooks (13 service types)
│   ├── tests/            # 470 tests
│   └── Dockerfile
├── corvus-sdk/           # Python SDK (early)
├── corvus-cli/           # CLI tool (early)
├── corvus-splunk/        # Splunk app for OCSF dashboards
├── spec/                 # Protocol specifications
├── docs/                 # Design documents
└── examples/             # Agent integration examples
```

## Standards

| Standard | How It's Used |
|----------|--------------|
| **OCSF 1.3.0** | Every event is schema-compliant and SIEM-portable |
| **FMEA** | Service types have documented failure modes for triage |

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CORVUS_API_KEYS` | Yes* | — | Comma-separated `name:key` pairs |
| `CORVUS_DEV_MODE` | No | `false` | Bypass auth for local development |
| `NEO4J_URI` | No | — | Neo4j connection URI (enables graph features) |
| `NEO4J_USER` | No | — | Neo4j username |
| `NEO4J_PASSWORD` | No | — | Neo4j password |
| `CORVUS_SIEM_URL` | No | — | SIEM endpoint URL |
| `CORVUS_SIEM_TOKEN` | No | — | SIEM authentication token |
| `CORVUS_SIEM_TYPE` | No | `splunk` | SIEM adapter: `splunk`, `sentinel`, `chronicle`, `elastic` |
| `CORVUS_SIEM_VERIFY_TLS` | No | `true` | Verify SIEM TLS certificates |
| `CORVUS_LLM_URL` | No | — | OpenAI-compatible LLM for triage diagnosis |
| `CORVUS_INFRA_CONFIG` | No | — | Path to infrastructure YAML (hosts, GPUs, stacks) |
| `CORVUS_DATA_DIR` | No | `/data` | SQLite database directory |

*Required unless `CORVUS_DEV_MODE=true`.

## Status

Active development. Core is production-tested. SDK, CLI, and module ecosystem are early.

| Component | Maturity |
|-----------|----------|
| Server (ops state, events, CMDB) | Production |
| FMEA runbook engine | Production |
| OCSF transformation | Production |
| Splunk SIEM forwarding | Production |
| Neo4j dependency graph | Production |
| Knowledge management | Production |
| Trust ledger | Production |
| Blind spot detection | Production |
| Module system | Early (SOC 2 reference module) |
| Python SDK | Early |
| CLI | Early |
| Other SIEM adapters | Implemented, untested |

## License

Apache License 2.0 — see [LICENSE](LICENSE).
