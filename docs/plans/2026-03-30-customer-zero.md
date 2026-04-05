# Customer Zero: Deploy Corvus + Neo4j + Discovery Bootstrap

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deploy Corvus server and Neo4j on dockp04, bootstrap the operational graph from all 39 compose files and 4 Docker hosts, and make it consumable by any agent via HTTP API.

**Architecture:** Corvus server (FastAPI + SQLite for flat state) + Neo4j Community (graph for services, CIs, dependencies). Discovery bootstrap script parses GitOps compose files (Layer 1: Declared) and inspects running containers via admin-api (Layer 3: Inspected). Graph is populated with ~157 services, hosts, GPUs, networks, and dependency edges. All via GitOps — compose in homelab-gitops, deployed via GitHub Actions.

**Tech Stack:** Python 3.11, FastAPI, neo4j async driver, Neo4j 5 Community, Docker Compose, GitHub Actions CI/CD

---

## Task 1: Add Neo4j to Corvus Server Dependencies

**Files:**
- Modify: `corvus-server/requirements.txt`
- Modify: `corvus-server/src/config.py`
- Create: `corvus-server/src/graph.py`

**Step 1: Add neo4j driver to requirements**

In `corvus-server/requirements.txt`, add:
```
neo4j>=5.20.0
```

**Step 2: Add Neo4j config**

In `corvus-server/src/config.py`, add:
```python
# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
```

**Step 3: Create graph connection manager**

Create `corvus-server/src/graph.py`:
```python
"""Neo4j graph database connection management."""

import logging
from contextlib import asynccontextmanager

from neo4j import AsyncGraphDatabase

from src.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

logger = logging.getLogger(__name__)

_driver = None


async def init_graph():
    """Initialize the Neo4j driver and create constraints/indexes."""
    global _driver
    if not NEO4J_PASSWORD:
        logger.warning("NEO4J_PASSWORD not set — graph features disabled")
        return
    _driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    # Verify connectivity
    async with _driver.session() as session:
        result = await session.run("RETURN 1 AS n")
        await result.single()
    logger.info("Neo4j connected: %s", NEO4J_URI)
    await _create_constraints()


async def _create_constraints():
    """Create uniqueness constraints and indexes."""
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (h:Host) REQUIRE h.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (g:GPU) REQUIRE (g.host, g.index) IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Network) REQUIRE n.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:CI) REQUIRE (c.type, c.name) IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE",
        "CREATE INDEX IF NOT EXISTS FOR (c:CI) ON (c.service)",
        "CREATE INDEX IF NOT EXISTS FOR (c:CI) ON (c.type)",
    ]
    async with _driver.session() as session:
        for q in constraints:
            await session.run(q)
    logger.info("Neo4j constraints created")


async def close_graph():
    """Close the Neo4j driver."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


@asynccontextmanager
async def graph_session():
    """Get a Neo4j async session."""
    if not _driver:
        raise RuntimeError("Graph not initialized (NEO4J_PASSWORD not set?)")
    async with _driver.session() as session:
        yield session


def graph_available() -> bool:
    """Check if graph backend is available."""
    return _driver is not None
```

**Step 4: Wire into app lifespan**

In `corvus-server/src/app.py`, add to lifespan:
```python
from src.graph import init_graph, close_graph

# Inside lifespan, after init_db():
await init_graph()

# In the finally/shutdown:
await close_graph()
```

**Step 5: Commit**
```bash
cd ~/git/corvus && git add corvus-server/requirements.txt corvus-server/src/config.py corvus-server/src/graph.py corvus-server/src/app.py
git commit -m "feat: add Neo4j async driver and graph connection manager"
```

---

## Task 2: Create Graph Discovery Router

**Files:**
- Create: `corvus-server/src/routers/discovery.py`
- Create: `corvus-server/src/routers/graph.py`
- Modify: `corvus-server/src/app.py` (mount new routers)

**Step 1: Create discovery router**

Create `corvus-server/src/routers/discovery.py` — endpoints to trigger discovery,
check status, view suggestions, and get coverage reports.

Key endpoints:
```
POST /ops/discovery/bootstrap    — parse compose files, populate graph
GET  /ops/discovery/status       — last scan per layer, coverage stats
GET  /ops/discovery/coverage     — services with no deps, stale edges
GET  /ops/discovery/suggestions  — inferred edges awaiting validation
POST /ops/discovery/suggestions/{id}/validate — promote/reject inferred edge
```

**Step 2: Create graph query router**

Create `corvus-server/src/routers/graph.py` — endpoints for graph traversal queries.

Key endpoints:
```
GET  /ops/graph/blast-radius/{service}     — what breaks if this goes down
GET  /ops/graph/dependency-chain/{service} — upstream dependency path
GET  /ops/graph/expiring?days=30           — CIs expiring within N days
GET  /ops/graph/correlated/{host}/{gpu}    — services sharing a GPU
POST /ops/graph/query                      — raw Cypher query (admin only)
```

**Step 3: Mount routers in app.py**
```python
from src.routers import discovery, graph
app.include_router(discovery.router, prefix="/ops/discovery", tags=["discovery"])
app.include_router(graph.router, prefix="/ops/graph", tags=["graph"])
```

**Step 4: Commit**
```bash
git add corvus-server/src/routers/discovery.py corvus-server/src/routers/graph.py corvus-server/src/app.py
git commit -m "feat: discovery and graph query routers"
```

---

## Task 3: Build Compose Parser (Layer 1: Declared Discovery)

**Files:**
- Create: `corvus-server/src/discovery/declared.py`
- Create: `corvus-server/src/discovery/__init__.py`

**Step 1: Build compose file parser**

Create `corvus-server/src/discovery/declared.py`:

Parses docker-compose.yml files and extracts:
- Service nodes (container name, image, healthcheck presence)
- `depends_on` → DEPENDS_ON edges (hard dependency)
- Network membership → CONNECTS_TO edges
- Volume mounts → MOUNTS edges
- Environment variable URLs → DEPENDS_ON edges (soft, inferred from env)
  Pattern match: `*_URL`, `*_HOST`, `*_ENDPOINT`, `*_DSN` values containing
  other service names
- `NVIDIA_VISIBLE_DEVICES` → USES_GPU edges
- Image tags → declared_image for drift detection

Input: directory of compose files (homelab-gitops/stacks/)
Output: list of nodes and edges ready for Neo4j ingestion

**Step 2: Build env var dependency extractor**

Within declared.py, a function that parses env var values for service references:
- `http://litellm:4000` → depends on litellm
- `postgres://user:pass@postgres:5432/db` → depends on postgres
- `192.168.20.15` → runs on tmtdockp01 (IP-to-host mapping)

**Step 3: Commit**
```bash
git add corvus-server/src/discovery/
git commit -m "feat: compose parser for Layer 1 declared discovery"
```

---

## Task 4: Build Runtime Inspector (Layer 3: Inspected Discovery)

**Files:**
- Create: `corvus-server/src/discovery/inspected.py`

**Step 1: Build container inspector**

Create `corvus-server/src/discovery/inspected.py`:

Calls admin-api `/containers` (or Docker API directly) and extracts:
- Running container state (status, health, image, restart count)
- Environment variables → dependency extraction (same as Task 3 Step 2)
- Actual image vs declared image → drift detection
- Healthcheck presence → declared vs actual comparison
- GPU assignments from container config
- Network memberships from container inspect
- Exit code (if exited)

Input: admin-api URL or Docker API URL
Output: list of runtime state records, dependency edges, drift flags

**Step 2: Commit**
```bash
git add corvus-server/src/discovery/inspected.py
git commit -m "feat: runtime inspector for Layer 3 inspected discovery"
```

---

## Task 5: Build Graph Populator

**Files:**
- Create: `corvus-server/src/discovery/populator.py`

**Step 1: Build the Neo4j graph populator**

Create `corvus-server/src/discovery/populator.py`:

Takes output from declared + inspected discovery and writes to Neo4j:
- MERGE Host nodes (4 hosts with IPs, roles)
- MERGE GPU nodes (9 GPUs with model, VRAM, host+index)
- MERGE Network nodes (from compose networks)
- MERGE Service nodes (from compose + running containers)
- MERGE CI nodes (certs, models, endpoints, accounts as discovered)
- CREATE edges: RUNS_ON, USES_GPU, DEPENDS_ON, CONNECTS_TO, MOUNTS, etc.
- Set edge provenance: `layers`, `confidence`, `first_discovered`, `last_confirmed`

Uses MERGE (not CREATE) so re-running bootstrap is idempotent.

Includes static infrastructure data:
- 4 hosts (dockp01-04) with IPs and roles
- 9 GPUs with models and VRAM from CLAUDE.md reference
- Key CIs: Let's Encrypt wildcard cert, NFS model mount, 1Password Connect tokens

**Step 2: Commit**
```bash
git add corvus-server/src/discovery/populator.py
git commit -m "feat: Neo4j graph populator with edge provenance"
```

---

## Task 6: Create GitOps Stack for Corvus + Neo4j

**Files:**
- Create: `homelab-gitops/stacks/dockp04-corvus/docker-compose.yml`
- Create: `homelab-gitops/stacks/dockp04-corvus/.env.template`
- Create: `homelab-gitops/.github/workflows/deploy-dockp04-corvus.yml`

**Step 1: Create the compose file**

```yaml
services:
  corvus:
    container_name: corvus
    build:
      context: /opt/corvus/corvus-server
      dockerfile: Dockerfile
    image: corvus-server:latest
    restart: unless-stopped
    ports:
      - "8100:8000"
    environment:
      - CORVUS_DATA_DIR=/data
      - CORVUS_API_KEYS=${CORVUS_API_KEYS}
      - NEO4J_URI=bolt://corvus-neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - CORVUS_SIEM_URL=${CORVUS_SIEM_URL:-}
      - CORVUS_SIEM_TOKEN=${CORVUS_SIEM_TOKEN:-}
      - CORVUS_LLM_URL=${CORVUS_LLM_URL:-}
    volumes:
      - corvus-data:/data
    networks:
      - infra-services
    depends_on:
      corvus-neo4j:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

  corvus-neo4j:
    container_name: corvus-neo4j
    image: neo4j:5-community
    restart: unless-stopped
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_server_memory_heap_initial__size=256m
      - NEO4J_server_memory_heap_max__size=512m
    volumes:
      - corvus-neo4j-data:/data
    ports:
      - "7474:7474"
      - "7687:7687"
    networks:
      - infra-services
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

volumes:
  corvus-data:
  corvus-neo4j-data:

networks:
  infra-services:
    external: true
```

**Step 2: Create .env.template**
```
CORVUS_API_KEYS=?required
NEO4J_PASSWORD=?required
CORVUS_SIEM_URL=
CORVUS_SIEM_TOKEN=
CORVUS_LLM_URL=
```

**Step 3: Create GitHub Actions deployment workflow**

Based on existing `deploy-dockp04-automation.yml` pattern:
- Trigger: push to main, path filter `stacks/dockp04-corvus/**`
- Checkout, load secrets from 1Password Connect
- rsync to dockp04
- Clone/pull corvus repo for build context
- docker compose build + up -d
- Health check verification

**Step 4: Commit to homelab-gitops (feature branch)**
```bash
cd ~/Documents/Claude/repos/homelab-gitops
git checkout -b feature/corvus-customer-zero
git add stacks/dockp04-corvus/ .github/workflows/deploy-dockp04-corvus.yml
git commit -m "feat: add Corvus + Neo4j stack for dockp04"
```

---

## Task 7: Deploy Corvus + Neo4j on dockp04

**Step 1: Create 1Password secrets**

Via admin-api, create secrets at `services/corvus`:
- `api_keys`: `admin:<generated-key>,nemoclaw:<generated-key>,claude:<generated-key>`
- `neo4j_password`: `<generated>`

**Step 2: Clone corvus repo on dockp04**
```bash
ssh tmiller@192.168.20.14 "sudo git clone https://github.com/tmttodd/corvus.git /opt/corvus"
```

**Step 3: Create stack directory and deploy**
```bash
ssh tmiller@192.168.20.14 "sudo mkdir -p /mnt/docker/stacks/dockp04-corvus"
# rsync compose + env from gitops
# docker compose build && docker compose up -d
```

**Step 4: Verify health**
```bash
curl -s http://192.168.20.14:8100/health
# Neo4j browser: http://192.168.20.14:7474
```

**Step 5: Add Caddy reverse proxy route**

In `stacks/dockp04-core/Caddyfile`, add:
```
corvus.themillertribe-int.org {
    tls /etc/letsencrypt/live/themillertribe-int.org/fullchain.pem /etc/letsencrypt/live/themillertribe-int.org/privkey.pem
    reverse_proxy corvus:8000 {
        lb_policy first
        transport http {
            dial_timeout 5s
        }
    }
}
```

---

## Task 8: Run Discovery Bootstrap

**Step 1: Copy compose files to corvus data volume**

The bootstrap needs access to all compose files. Two options:
a) Mount homelab-gitops repo read-only into corvus container
b) API endpoint accepts compose YAML via POST

Option (a) for bootstrap, option (b) for ongoing CI/CD integration.

**Step 2: Run bootstrap via API**
```bash
CORVUS_TOKEN="admin:<key>"
curl -X POST http://192.168.20.14:8100/ops/discovery/bootstrap \
  -H "Authorization: Bearer $CORVUS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"compose_dir": "/gitops/stacks", "admin_api_url": "http://admin-api:8000"}'
```

**Step 3: Verify graph population**
```bash
# Count nodes
curl http://192.168.20.14:7474 # Neo4j browser
# Or via Corvus API:
curl http://192.168.20.14:8100/ops/discovery/status
```

Expected: ~157 Service nodes, 4 Host nodes, 9 GPU nodes, 200+ edges

**Step 4: Verify key queries work**
```bash
# Blast radius for caddy
curl http://192.168.20.14:8100/ops/graph/blast-radius/caddy

# Expiring CIs
curl http://192.168.20.14:8100/ops/graph/expiring?days=30

# GPU 0 services on dockp03
curl http://192.168.20.14:8100/ops/graph/correlated/tmtdockp03/0
```

**Step 5: Commit any discovery fixes**

---

## Task 9: Add DNS Record for Corvus

**Step 1: Create PowerDNS A record**
```bash
# Via admin-api or powerdns MCP
corvus.themillertribe-int.org → 192.168.20.14 (ipvlan) or via Caddy proxy
```

**Step 2: Verify**
```bash
dig corvus.themillertribe-int.org @192.168.20.250
curl -s https://corvus.themillertribe-int.org/health
```

---

## Task 10: Register Corvus in CMDB + NemoClaw

**Step 1: Register corvus and corvus-neo4j in CMDB**
```bash
curl -X POST http://192.168.20.14:8100/ops/cmdb/register \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"corvus","host":"tmtdockp04","service_type":"automation","critical":true}'
curl -X POST http://192.168.20.14:8100/ops/cmdb/register \
  -d '{"name":"corvus-neo4j","host":"tmtdockp04","service_type":"database","critical":true}'
```

**Step 2: Add to NemoClaw infrastructure registry**

In `homelab-gitops/stacks/dockp04-automation/nemoclaw/config/infrastructure-registry.yaml`,
add corvus and corvus-neo4j to the critical sweep tier.

**Step 3: Commit**

---

## Task 11: Push homelab-gitops PR and Deploy

**Step 1: Push feature branch and create PR**
```bash
cd ~/Documents/Claude/repos/homelab-gitops
git push -u origin feature/corvus-customer-zero
gh pr create --title "feat: Corvus + Neo4j customer zero deployment" --body "..."
```

**Step 2: Get Todd approval and merge**

**Step 3: Verify CI/CD deployment**

**Step 4: Run post-deploy validation**

---

## Task 12: Verify Agent-Agnostic Access

**Step 1: Test from Mac (any HTTP client)**
```bash
# Any agent or tool can call these
curl -s https://corvus.themillertribe-int.org/ops/graph/blast-radius/caddy \
  -H "Authorization: Bearer $TOKEN"
curl -s https://corvus.themillertribe-int.org/ops/discovery/coverage \
  -H "Authorization: Bearer $TOKEN"
curl -s https://corvus.themillertribe-int.org/ops/cmdb \
  -H "Authorization: Bearer $TOKEN"
```

**Step 2: Verify NemoClaw can reach Corvus**
```bash
ssh tmiller@192.168.20.14 "sudo docker exec nemoclaw curl -s http://corvus:8000/health"
```

**Step 3: Document the API contract**

Create a one-page "Agent Integration Guide" showing:
- Base URL: `https://corvus.themillertribe-int.org`
- Auth: `Authorization: Bearer <key>`
- Key endpoints for any agent: CMDB, graph queries, incident creation, triage
- Example: how to call blast-radius before a restart

---

## Execution Order & Parallelism

```
Sequential: Task 1 → 2 → 3 → 4 → 5 (corvus-server code)
Parallel:   Task 6 (gitops stack) can run alongside Tasks 3-5
Sequential: Task 7 depends on Task 1-6
Sequential: Task 8 depends on Task 7
Parallel:   Task 9 + 10 after Task 7
Sequential: Task 11 → 12 (deploy + verify)
```

**Estimated time:** 3-4 hours of focused build work.

**Checkpoint:** After Task 7 (deploy), verify health before proceeding to bootstrap.
After Task 8 (bootstrap), verify graph before proceeding to agent integration.
