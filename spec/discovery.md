# Service Discovery & Dependency Mapping

This is the hardest problem in operational intelligence. Every CMDB dies the same
death: manual population, stale by day two, trust collapses, shelfware.

Corvus solves this with **6 discovery layers** that reinforce each other. No single
layer catches everything — but together they build and maintain a living operational
graph that stays accurate without manual upkeep.

## The 6 Discovery Layers

```
Layer 1: DECLARED    — what SHOULD exist (GitOps, IaC)
Layer 2: OBSERVED    — what IS talking to what (network traffic)
Layer 3: INSPECTED   — what IS running right now (runtime state)
Layer 4: REPORTED    — what agents and services TELL us (self-registration)
Layer 5: INFERRED    — what history IMPLIES (temporal correlation)
Layer 6: ELICITED    — what humans KNOW (tribal knowledge capture)
```

Each layer has a **confidence level** and a **staleness model**. Edges from
multiple layers reinforce each other — a dependency seen in both declared
(compose `depends_on`) and observed (TCP connection) has higher confidence
than either alone.

### Layer 1: Declared (GitOps / IaC)

**What**: Parse version-controlled infrastructure definitions for services,
dependencies, networks, volumes, and configuration.

**Sources by platform**:

| Platform | Source | What It Reveals |
|----------|--------|----------------|
| Docker Compose | `docker-compose.yml` | Services, depends_on, networks, volumes, images, env vars, healthchecks |
| Kubernetes | Manifests, Helm charts | Deployments, Services, Ingress, ConfigMaps, PVCs, ServiceAccounts |
| Bare Metal | Ansible playbooks, systemd units | Packages, services, ports, mount points, user accounts |
| Terraform | `.tf` state files | Cloud resources, security groups, DNS, load balancers |
| CI/CD | Workflow definitions | Build → deploy → verify chains, runner → host mappings |

**Discovery method**:
- Parse compose files: extract `depends_on`, `networks`, `volumes`, `image`, env var references
- Parse K8s manifests: extract service selectors, ingress rules, PVC bindings
- Parse Ansible: extract host groups, package lists, service enablement, file templates
- Watch Git for changes: re-parse on commit, track what changed

**Confidence**: HIGH (it's in version control)
**Staleness**: LOW (updated on every Git commit)
**Limitation**: Only covers what's declared. Misses runtime-only dependencies,
cowboy deploys, and implicit service-to-service API calls not in `depends_on`.

**Adapter interface**:
```python
class DeclaredDiscoveryAdapter:
    async def discover_services(self) -> list[ServiceCI]
    async def discover_dependencies(self) -> list[DependencyEdge]
    async def discover_config(self) -> list[ConfigCI]
    async def watch_changes(self, callback: Callable) -> None
```

### Layer 2: Observed (Network)

**What**: Watch actual network traffic between services to discover dependencies
that nobody declared. If sonarr makes HTTP calls to prowlarr:9696, that's a
dependency — even if no `depends_on` exists.

**Sources by platform**:

| Platform | Source | What It Reveals |
|----------|--------|----------------|
| Docker | Docker network conntrack, eBPF | Container-to-container TCP connections |
| Kubernetes | eBPF, service mesh (Istio/Linkerd) | Pod-to-pod, pod-to-service, external calls |
| Bare Metal | eBPF, conntrack, netstat/ss | Process-to-process TCP/UDP connections |
| Any | DNS query logs | Service name resolution patterns |
| Any | Reverse proxy access logs | HTTP routing, upstream health, request patterns |

**Discovery method**:
- **eBPF/Tetragon** (preferred): Kernel-level network event capture. Zero overhead,
  sees every TCP connect/accept. Already deployed in the homelab.
- **conntrack**: Parse `/proc/net/nf_conntrack` or `conntrack -L` for active connections.
  Maps source container → destination container by IP.
- **DNS logs**: Parse resolver query logs. If `sonarr` resolves `prowlarr`, that's
  a dependency signal.
- **Proxy logs**: Parse Caddy/Nginx access logs. Every request reveals a client →
  proxy → upstream chain.

**Confidence**: HIGH (observed in production traffic)
**Staleness**: Connection map refreshed every sweep cycle (5-15 min)
**Limitation**: Only sees active connections. Dormant dependencies (cron-triggered,
event-driven) may not appear during observation windows. Encrypted traffic is
opaque without proxy or eBPF.

**Adapter interface**:
```python
class ObservedDiscoveryAdapter:
    async def discover_connections(self) -> list[ConnectionEdge]
    async def discover_dns_queries(self) -> list[DNSQueryEdge]
    async def discover_proxy_routes(self) -> list[ProxyRouteEdge]
    async def stream_connections(self, callback: Callable) -> None
```

### Layer 3: Inspected (Runtime)

**What**: Examine the actual running state of services — processes, environment
variables, mounted volumes, GPU assignments, open file handles.

**Sources by platform**:

| Platform | Source | What It Reveals |
|----------|--------|----------------|
| Docker | `docker inspect`, `docker stats` | Image, env vars, mounts, networks, health, resource usage |
| Kubernetes | `kubectl describe`, kubelet API | Pod spec, mounted secrets, node placement, resource limits |
| Bare Metal | `/proc`, `ss -tlnp`, `lsof` | Listening ports, open files, mount points, process trees |
| Any | Environment variables | Dependency URLs (`DATABASE_URL=postgres://...`), API keys, feature flags |
| Any | Config files inside containers | Application-level dependencies not visible externally |

**Discovery method**:
- **Environment variable parsing**: Extract URLs, hostnames, ports from env vars.
  `PROWLARR_URL=http://prowlarr:9696` → dependency edge: service → prowlarr.
  Pattern match: `*_URL`, `*_HOST`, `*_PORT`, `*_ENDPOINT`, `*_DSN`, `*_CONNECTION_STRING`.
- **Volume mount analysis**: Shared volumes imply data dependencies.
  Two containers mounting the same volume share a data coupling.
- **GPU assignment**: `NVIDIA_VISIBLE_DEVICES` → maps services to GPU resources.
- **Network membership**: Containers on the same Docker network can reach each other.
  Containers NOT on a shared network cannot (isolation boundary).
- **Image ancestry**: Same base image may share failure modes.

**Confidence**: MEDIUM-HIGH (point-in-time snapshot, may miss transient state)
**Staleness**: Refreshed on discovery sweep (15 min default)
**Limitation**: Snapshot, not stream. May miss short-lived processes or
transient connections. Config files inside containers may require exec access.

**Adapter interface**:
```python
class InspectedDiscoveryAdapter:
    async def inspect_services(self) -> list[ServiceState]
    async def inspect_env_dependencies(self) -> list[EnvDependencyEdge]
    async def inspect_volume_sharing(self) -> list[VolumeShareEdge]
    async def inspect_gpu_assignments(self) -> list[GPUAssignmentEdge]
```

### Layer 4: Reported (Agent / Self-Registration)

**What**: Services and agents actively report their CIs and dependencies to
Corvus. This catches things no passive discovery can see: external accounts,
subscriptions, licenses, business relationships, application-internal state.

**Sources**:

| Reporter | What It Reports |
|----------|----------------|
| NemoClaw | Container health, discovered services, restart events |
| Claude Code | Session discoveries ("certbot must be healthy before caddy"), design knowledge |
| Application health endpoints | Internal dependency state, feature flags, connection pool stats |
| CI/CD pipelines | Deploy events, image versions, config changes |
| Startup hooks | "I depend on X, Y, Z" declared at boot |
| Manual registration | Accounts, subscriptions, licenses, vendor relationships |

**Discovery method**:
- **Corvus API**: `POST /ops/cmdb/ci` and `POST /ops/cmdb/register`
- **Health endpoint convention**: Services expose `/corvus/ci` returning their CIs
  and dependencies in a standard JSON schema. Corvus periodically scrapes these.
- **Agent event stream**: Parse events for implicit CI discovery. A `remediation.restart`
  event on a service implies the service exists. A `change.completed` event with
  target details implies CIs were modified.
- **Startup registration**: Container entrypoint calls Corvus to register itself
  and its dependencies. Lightweight — single HTTP POST at boot.

**Confidence**: VARIES (depends on reporter accuracy and freshness)
**Staleness**: Real-time for agents, periodic for health endpoint scraping
**Limitation**: Requires cooperation from services (health endpoints) or agents.
External CIs (accounts, licenses) require manual initial registration.

**Adapter interface**:
```python
class ReportedDiscoveryAdapter:
    async def scrape_health_endpoints(self) -> list[HealthCI]
    async def process_event_stream(self, events: list[Event]) -> list[CI]
    async def register_ci(self, ci: CI) -> None
```

### Layer 5: Inferred (Historical / Temporal)

**What**: Mine the operational graph's history for implicit dependencies and
causal relationships. If two services always fail together, they're coupled —
even if no one declared or observed a direct connection.

**Sources**:

| Signal | What It Reveals |
|--------|----------------|
| Incident co-occurrence | Services that fail within N minutes of each other |
| Change cascade | Changes to A consistently cause incidents on B |
| Restart correlation | Services that restart in predictable sequence |
| Performance coupling | Latency in A correlates with throughput drop in B |
| Resolution patterns | Fixing A consistently resolves incidents on B |

**Discovery method**:
- **Temporal correlation**: For each incident, find other incidents on the same
  host or network within a time window (e.g., 15 min). Repeated co-occurrence
  → inferred edge. Neo4j temporal queries make this natural.
- **Change impact analysis**: For each change, track incidents in the following
  24 hours on related services. Repeated patterns → inferred causal edge.
- **Restart sequence mining**: Log the order of container restarts. Sequences
  that repeat (A restarts, then B restarts, then C restarts) imply dependency.
- **Statistical correlation**: Correlate time-series metrics (if available)
  across services. High correlation → coupling signal.

**Confidence**: LOW-MEDIUM (correlation is not causation, requires threshold tuning)
**Staleness**: Improves over time as more history accumulates
**Limitation**: Requires sufficient operational history. New deployments have no
history. False positives from coincidental timing. Needs human validation.

**Graph queries**:
```cypher
// Find services that always fail together (co-occurrence)
MATCH (i1:Incident)-[:AFFECTS]->(s1:Service)
MATCH (i2:Incident)-[:AFFECTS]->(s2:Service)
WHERE s1 <> s2
  AND abs(duration.between(i1.created_at, i2.created_at).minutes) < 15
WITH s1, s2, count(*) AS co_occurrences
WHERE co_occurrences >= 3
MERGE (s1)-[r:INFERRED_DEPENDENCY]->(s2)
SET r.confidence = co_occurrences / 10.0,
    r.evidence = "incident_co_occurrence",
    r.last_observed = datetime()

// Find changes that cause downstream incidents
MATCH (ch:Change)-[:TARGETS]->(target:Service)
MATCH (i:Incident)-[:AFFECTS]->(victim:Service)
WHERE victim <> target
  AND i.created_at > ch.closed_at
  AND i.created_at < ch.closed_at + duration({hours: 24})
WITH target, victim, count(*) AS cascades
WHERE cascades >= 2
MERGE (victim)-[r:INFERRED_DEPENDENCY]->(target)
SET r.confidence = cascades / 5.0,
    r.evidence = "change_cascade",
    r.last_observed = datetime()
```

**Adapter interface**:
```python
class InferredDiscoveryAdapter:
    async def analyze_co_occurrence(self, window_days: int = 30) -> list[InferredEdge]
    async def analyze_change_cascades(self, window_days: int = 30) -> list[InferredEdge]
    async def analyze_restart_sequences(self) -> list[InferredEdge]
```

### Layer 6: Elicited (Knowledge Capture)

**What**: Capture tribal knowledge — dependencies and operational facts that
exist only in people's heads — at the moments when that knowledge surfaces.

**Sources**:

| Moment | Knowledge Captured |
|--------|-------------------|
| Incident resolution | "This broke because X depends on Y" |
| CC session discovery | "Certbot must be healthy before caddy starts" |
| Slack conversation | "@norbit that's because prowlarr feeds sonarr" |
| Post-mortem review | "The root cause was an expired Astraweb account" |
| Onboarding / documentation | "This service has an undocumented dependency on NFS" |

**Discovery method**:
- **Incident resolution prompt**: When an incident is resolved, Corvus asks:
  "Did this incident reveal any dependencies we didn't know about?" If yes,
  create the edge with `layer: "elicited"` and high confidence.
- **Agent session capture**: CC and NemoClaw record discovered dependencies
  during normal operations via `POST /ops/cmdb/ci` with
  `discovered_by: "claude-code:session"`.
- **Conversational capture**: NemoClaw's Slack bot recognizes dependency
  statements in conversation ("X depends on Y", "X feeds Y", "X needs Y")
  and proposes CI registration.
- **Knowledge base integration**: RAG pipeline ingests post-mortems, runbooks,
  and documentation. Dependency statements are extracted and proposed as edges.

**Confidence**: HIGH (human-validated knowledge)
**Staleness**: Never auto-expires (human knowledge is deliberately added)
**Limitation**: Requires a moment of capture. Knowledge that never surfaces
in an incident, session, or conversation remains hidden. Biased toward
failure-path knowledge (we learn dependencies when they break).

**Adapter interface**:
```python
class ElicitedDiscoveryAdapter:
    async def prompt_on_resolution(self, incident: Incident) -> list[CI]
    async def capture_from_conversation(self, message: str) -> list[CI]
    async def extract_from_document(self, doc: str) -> list[CI]
```

---

## Edge Provenance

Every edge in the graph carries provenance metadata — where it came from,
when it was last confirmed, and how confident we are.

```cypher
// Every relationship has provenance properties
(:Service)-[:DEPENDS_ON {
  layers: ["declared", "observed"],     // Which layers confirmed this
  confidence: 0.95,                     // Combined confidence
  first_discovered: datetime(),         // When first seen
  last_confirmed: datetime(),           // When last validated
  discovered_by: "docker-compose",      // Discovery source
  stale_after: duration({days: 30})     // When to re-validate
}]->(:Service)
```

### Confidence Aggregation

When multiple layers discover the same edge, confidence increases:

| Layers Confirming | Confidence |
|-------------------|-----------|
| 1 layer (declared only) | 0.7 |
| 1 layer (observed only) | 0.8 |
| 1 layer (elicited only) | 0.9 |
| 2 layers (declared + observed) | 0.95 |
| 3+ layers | 0.99 |
| 1 layer (inferred only) | 0.4-0.6 (depends on co-occurrence count) |

Inferred edges below 0.5 confidence are stored but flagged for human validation.
They appear in a "Suggested Dependencies" queue — not in production traversals
until confirmed by another layer or a human.

### Staleness Model

Every edge has a `stale_after` duration based on its discovery layer:

| Layer | Default Staleness | Refresh Method |
|-------|-------------------|----------------|
| Declared | Never (Git is authoritative) | Re-parse on Git commit |
| Observed | 24 hours | Connection map refresh |
| Inspected | 1 hour | Discovery sweep |
| Reported | 7 days | Re-scrape health endpoints |
| Inferred | 30 days | Re-run correlation analysis |
| Elicited | Never (explicit human knowledge) | Manual invalidation only |

Stale edges are not deleted — they're marked `stale: true` and excluded from
production traversals. A `gap:coverage:stale-dependency` problem is generated
for edges that go stale without refresh.

---

## Discovery Orchestration

Discovery runs as a continuous process, not a one-time scan.

### Discovery Sweep Cycle

```
Every 5 minutes:   Layer 3 (Inspected) — container health, GPU state
Every 15 minutes:  Layer 2 (Observed) — connection map, DNS queries
Every hour:        Layer 3 (Inspected) — full env var + volume scan
On Git commit:     Layer 1 (Declared) — re-parse changed compose/manifests
On incident close: Layer 6 (Elicited) — prompt for dependency knowledge
Daily:             Layer 5 (Inferred) — run temporal correlation analysis
Continuous:        Layer 4 (Reported) — process agent events as they arrive
```

### Bootstrap Protocol

For a new environment (first Corvus deployment):

1. **Layer 1**: Parse all GitOps/IaC files → populate services and declared dependencies
2. **Layer 3**: Inspect all running containers → populate runtime state, env var dependencies
3. **Layer 2**: Observe network for 1 hour → populate connection map
4. **Layer 4**: Accept agent registrations as they come online
5. **Layer 5**: Skip (no history yet — starts accumulating from day one)
6. **Layer 6**: Skip (no incidents yet — prompts activate when incidents occur)

Bootstrap produces a usable graph in **under 2 hours** for any Docker/K8s/bare metal
environment. The graph improves continuously from there.

### New Service Detection

When a discovery sweep finds a service not in the graph:

1. Create `Service` node with `status: "discovered"`, `discovered_by: "<layer>"`
2. Run all applicable discovery layers against the new service
3. Generate `gap:coverage:unclassified-service` problem if no service_type can be inferred
4. Agent or human classifies → runbook selection becomes available
5. Over the next 24 hours, observed + inspected layers fill in dependencies

---

## Platform Adapters

Each deployment platform implements the discovery adapter interfaces.
The graph schema is universal — adapters translate platform-specific primitives
into Corvus nodes and edges.

### Docker Adapter (customer zero)

```yaml
adapter: docker
sources:
  declared: docker-compose.yml (GitOps repo)
  observed: Docker network conntrack, Tetragon eBPF, Caddy access logs
  inspected: Docker API (inspect, stats, exec)
  reported: Admin API events, NemoClaw registration, health endpoint scraping

service_mapping:
  container → Service node
  env var URL → DEPENDS_ON edge
  docker network membership → CONNECTS_TO edge
  depends_on → DEPENDS_ON edge (hard)
  shared volume → data coupling signal
  NVIDIA_VISIBLE_DEVICES → USES_GPU edge
```

### Kubernetes Adapter (planned)

```yaml
adapter: kubernetes
sources:
  declared: Manifests, Helm charts, Kustomize
  observed: eBPF (Cilium/Tetragon), service mesh sidecar
  inspected: kubelet API, kubectl describe
  reported: Operator CRDs, admission webhooks

service_mapping:
  Deployment → Service node
  Service selector → DEPENDS_ON edge
  Ingress rule → PROXIED_BY edge
  PVC binding → STORED_ON edge
  Node affinity → RUNS_ON edge
  ServiceAccount → AUTHENTICATES_WITH edge
```

### Bare Metal Adapter (planned)

```yaml
adapter: bare_metal
sources:
  declared: Ansible playbooks, systemd units, /etc configs
  observed: eBPF, ss/netstat, /proc/net
  inspected: /proc filesystem, systemctl, lsof
  reported: Agent registration, monitoring APIs

service_mapping:
  systemd unit → Service node
  listening port → EndpointCI
  /etc config references → DEPENDS_ON edge
  NFS mount → STORED_ON edge
  process tree → parent/child relationship
```

---

## API

### Trigger Discovery
```
POST /ops/discovery/scan
```
```json
{
  "layers": ["declared", "inspected"],
  "target": "tmtdockp01",
  "full": false
}
```
Triggers an on-demand discovery scan. `full: true` runs all layers.

### Discovery Status
```
GET /ops/discovery/status
```
Returns last scan time per layer, coverage stats, and pending gaps.

### Suggested Dependencies
```
GET /ops/discovery/suggestions
```
Returns inferred edges below confidence threshold awaiting human validation.

### Validate Suggestion
```
POST /ops/discovery/suggestions/{edge_id}/validate
```
```json
{
  "valid": true,
  "notes": "Confirmed: Sonarr depends on Prowlarr for indexer search"
}
```
Promotes an inferred edge to elicited (human-validated).

### Coverage Report
```
GET /ops/discovery/coverage
```
Returns: services with no dependencies, CIs with no parent service,
edges confirmed by only one layer, stale edges past their refresh window.

---

## Success Metrics

A discovery system is working when:

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Service coverage** | 100% of running services in graph | `discovered / running` |
| **Dependency accuracy** | <10% false positive edges | Validated sample quarterly |
| **Staleness** | <5% of edges stale at any time | `stale_edges / total_edges` |
| **Bootstrap time** | <2 hours for new environment | Time from first scan to 80% coverage |
| **New service detection** | <15 minutes from deploy to graph | Time from container start to Service node |
| **Knowledge capture rate** | >50% of incidents add >=1 edge | `incidents_with_discovery / total_incidents` |
| **Layer diversity** | >60% of edges confirmed by 2+ layers | `multi_layer_edges / total_edges` |
