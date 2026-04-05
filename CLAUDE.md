# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Is Corvus

Corvus is operational governance for AI agent fleets. One deployment gives any agent-based system shared awareness, FMEA-informed triage, self-improving blind spot detection, and audit-grade compliance evidence.

Corvus is NOT an agent framework. It doesn't care how your agents are built. If an agent can make HTTP calls, it's a Corvus citizen.

Customer zero: TMT Homelab (NemoClaw + Claude Code, 92 services, 4 hosts, 9 GPUs).

## Repository Structure

```
corvus/
├── corvus-server/       # Single deployable — the entire platform
│   ├── src/             # FastAPI app, ops DB, OCSF transformer, runbook engine, RAG
│   │   ├── app.py               # FastAPI entry point with middleware pipeline
│   │   ├── config.py            # Environment-based configuration
│   │   ├── database.py          # SQLite schema and connection management
│   │   ├── ocsf.py              # OCSF 1.3.0 event transformer
│   │   ├── graph.py             # Neo4j graph database for CI relationships
│   │   ├── middleware/            # Auth (RBAC) and audit logging
│   │   ├── models/                # Pydantic request/response models
│   │   ├── routers/               # FastAPI route handlers
│   │   ├── runbooks/              # YAML runbook loader and triage executor
│   │   ├── siem/                  # SIEM forwarder (Splunk HEC)
│   │   └── tasks/                 # Background tasks (expiry, gap detection)
│   ├── runbooks/                # FMEA triage runbooks (12 YAML files)
│   ├── modules/                 # Extensible governance + compliance + integrations
│   ├── tests/                   # Test suite
│   └── Dockerfile
├── spec/                        # Protocol specification
│   ├── events.md              # Event type taxonomy + OCSF mappings
│   ├── incidents.md           # Incident lifecycle
│   ├── changes.md             # Change window protocol
│   ├── problems.md            # Problem management + gap detection
│   ├── cmdb.md                # Service registry schema (CIs, relationships)
│   └── runbooks.md            # Runbook YAML format
├── docs/                        # Guides, FMEA templates, architecture
└── examples/                    # Agent integration examples
    ├── claude-code/           # CC governance rules + MCP tool config
    └── crewai/                # CrewAI adapter example
```

## Development Commands

### Setup
```bash
cd corvus-server
pip install -r requirements.txt
```

### Running the Server
```bash
cd corvus-server
uvicorn src.app:app --reload --port 8000
```

### Running Tests
```bash
cd corvus-server
python -m pytest tests/ -v
```

### Running a Single Test
```bash
cd corvus-server
python -m pytest tests/test_ocsf.py -v
```

### Quality Gates (Run Before Every PR)
```bash
cd corvus-server

# Lint + Format
ruff check src/ tests/
ruff format --check src/ tests/

# SAST
bandit -r src/ -c pyproject.toml
semgrep scan --config auto src/

# Test
python -m pytest tests/ -v
```

## Core Architecture

### Event-Driven Operations
Corvus operates on an event-driven model. Every state-changing action by any agent produces an event that is:
1. Stored in SQLite ops DB
2. Transformed to OCSF 1.3.0
3. Forwarded to your SIEM

### Event Type Taxonomy

| Category | Event Types |
|----------|-------------|
| Change lifecycle | `change.started`, `change.completed`, `change.failed`, `change.expired` |
| Incident lifecycle | `incident.opened`, `incident.investigating`, `incident.resolved`, `incident.escalated` |
| Remediation | `remediation.restart`, `remediation.config_fix`, `remediation.credential_rotation` |
| Sweep/Scan | `sweep.completed`, `sweep.anomaly` |
| Actions | `action.approved`, `action.denied` |
| Sessions | `session.started`, `session.ended` |
| Correlation | `correlation.group_created`, `correlation.group_resolved` |
| Gaps | `gap:accuracy:*`, `gap:coverage:*`, `gap:autonomy:*`, `gap:efficiency:*` |

### OCSF Mapping
Every event is transformed to OCSF 1.3.0 before SIEM forwarding:

| Event Type | OCSF Class | Class UID |
|------------|-----------|-----------|
| `incident.*` | Incident Finding | 2005 |
| `change.*` | Device Config State Change | 5019 |
| `remediation.*` | Remediation Activity | 7001 |
| `sweep.*` | Scan Activity / Detection Finding | 6007/2004 |
| `action.*` | API Activity | 6003 |
| `session.*` | Application Lifecycle | 6002 |
| `gap:*` | Compliance Finding | 2003 |

### CMDB (Service Registry)
The CMDB stores services and configuration items (CIs) with typed relationships:

**Service Types**: inference, database, proxy, mcp_bridge, secrets, iot_gateway, home_automation, media, monitoring, automation, dns, utility

**CI Types**: search, index, app, model, flow, endpoint, automation, integration, library, queue, account, credential, license, subscription, cert, zone, record, vlan, firewall_rule, dataset, snapshot, backup_job, disk, nic, psu, controller, device, scene, bridge, sensor

**Relationship Types**: BELONGS_TO, CONTAINS, INSTALLED_ON, DEPENDS_ON, USES, READS_FROM, WRITES_TO, AUTHENTICATES_WITH, FEEDS, LOADED_ON, STORED_ON, HOSTED_ON, SECURES, PROXIED_BY, ROUTES_TO, MANAGED_BY, AFFECTS_CI, CHANGED_BY, MONITORED_BY, EXPIRED

### Runbook Engine
FMEA-informed triage runbooks are YAML files in `corvus-server/runbooks/`. Each runbook corresponds to a service type and provides:
- Triage questions (decision tree)
- Commands to run for diagnosis
- Remediation steps with confirmation

## Operational Protocol

### Pre-Action Conflict Check
Before ANY MODIFY+ action on an infrastructure target, call:
```
ops_check_target(target=<target_name>)
```
Returns GO/CAUTION/STOP recommendation based on active changes, incidents, and recent events.

### Event Emission
Always emit events for state-changing actions:
```
ops_emit_event(
    source="claude-code",
    type="change.completed",
    target="admin-api",
    severity="info",
    data={"summary": "Deployed OCSF transformer v2"},
    related_change_id="CHG-A1B2C3D4"
)
```

### Change Windows
For planned work:
1. Open: `ops_create_change(targets=[...], description="...", rollback_plan="...")`
2. During: Emit events for each step
3. Close: `ops_close_change(change_id, status="completed", outcome="success")`

### Session Workflow
1. **Start**: Call `ops_get_context()` for situational awareness
2. **Before modify**: Call `ops_check_target(target=...)`
3. **End**: Verify all actions have events, close open change windows

## API Endpoints

### Events
- `POST /ops/events` - Emit an event
- `GET /ops/events` - List events with filters
- `GET /ops/events/context` - Session briefing (last 24h)
- `GET /ops/events/targets/{target}/status` - Target status check

### CMDB
- `POST /ops/cmdb/register` - Register/update service
- `GET /ops/cmdb` - List services
- `GET /ops/cmdb/{name}` - Get service details
- `PATCH /ops/cmdb/{name}` - Update service
- `POST /ops/cmdb/bulk-sync` - Bulk sync services
- `POST /ops/cmdb/bulk-classify` - Bulk classify services
- `POST /ops/cmdb/ci` - Register configuration item
- `GET /ops/cmdb/ci/{name}/impact` - CI impact analysis

### Incidents, Changes, Problems
- `POST /ops/incidents` - Create incident
- `GET /ops/incidents` - List incidents
- `POST /ops/changes` - Create change window
- `GET /ops/changes` - List changes
- `POST /ops/problems` - Create problem
- `GET /ops/problems` - List problems

### Runbooks
- `GET /ops/runbooks` - List available runbooks
- `POST /ops/runbooks/triage` - Run triage for a service

### Graph Queries
- `POST /ops/graph/queries` - Run Cypher queries
- `GET /ops/graph/services/{name}` - Get service graph

## Standards

- **OCSF 1.3.0**: Every event is schema-compliant
- **ITIL**: Change/incident/problem lifecycle (core governance module)
- **FMEA**: Service types have documented failure modes

## Deployment

```bash
docker run -d -p 8000:8000 -v corvus-data:/data ghcr.io/tmttodd/corvus:latest
```

Point your agents at `http://corvus:8000`.

## Testing

Tests use pytest with pytest-asyncio. The test client uses httpx's ASGI transport to test the FastAPI app directly without starting a server.

```python
@pytest.mark.asyncio
async def test_something(client):
    resp = await client.post("/ops/events", json={...})
    assert resp.status_code == 201
```

Test fixtures clear the database between tests for isolation.

## Code Style

- Python 3.11+
- Type hints everywhere
- No unnecessary abstractions
- Tests for all new functionality
- Line length: 120 (ruff)

## Security

- API keys via `CORVUS_API_KEYS` environment variable (comma-separated)
- Audit logging on all `/ops/` and `/backup/` endpoints
- RBAC support via module system
- SAST: bandit + semgrep required before PR merge

## Design Principles

1. **Agent-agnostic** — Any agent that speaks HTTP is a citizen
2. **OCSF-native** — Standard data model, not retrofitted
3. **Extensible** — Governance and compliance modules, not hardcoded frameworks
4. **Self-aware** — Detects its own blind spots, generates its own improvement work
5. **Audit-grade** — Every action traceable, every decision provable
6. **Portable** — One container, any environment
