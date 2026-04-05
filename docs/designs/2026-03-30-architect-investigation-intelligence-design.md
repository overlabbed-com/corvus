# Corvus Investigation Intelligence — Architect Design

> **Date**: 2026-03-30
> **Agent**: Architect
> **Status**: Pending Advocate challenge
> **Trigger**: NemoClaw gap analysis — 7 investigation gaps found during live incident triage

## Problem Statement

NemoClaw escalated three alerts on 2026-03-30 that it should have investigated and
(in two cases) resolved autonomously:

1. **docling "auth_failure"** — false positive. Greedy regex matched "401" in clean
   200 OK health check logs. Actual cause: CUDA OOM on co-located ace-step took out
   all 4 GPU 0 services. Norbit filed 4 independent alerts instead of 1 correlated group.

2. **Deploy dockp04-core failed** — passthrough. Norbit reported "Step 'Deploy stack'
   failed" with a link. Actual cause: certbot container created before healthcheck was
   added to compose. Norbit could have pulled the workflow logs, identified the root
   cause, and suggested `docker compose up -d --force-recreate certbot`.

3. **Deploy dockp04-security failed** — passthrough. Splunk first boot takes ~6 min;
   dependency timeout was shorter. Splunk was already healthy by the time anyone looked.
   Norbit could have checked current health and reported "transient — already resolved."

**Root cause of all three**: operational intelligence definitions live in NemoClaw's
hardcoded Python, not in Corvus's governed spec. No feedback loop, no quality gate,
no cross-agent benefit.

**Todd's directive**: "Corvus should be the single place I make these changes so they're
respected by all agents and code assistants."

## Design Principle

**Corvus owns the operational intelligence contract. Agents are consumers.**

Every definition an agent needs to investigate, diagnose, correlate, or remediate lives
in Corvus — not in agent-specific code. Agents call Corvus APIs to get investigation
standards, runbook procedures, diagnosis rules, and correlation data. They do not
maintain their own copies.

This isn't just a code organization choice. It's what makes the feedback loops work:
- **Standards** produce consistent evidence → consistent evidence enables **correlation**
- **Correlation** reveals shared root causes → shared root causes drive **problem management**
- **Problem management** identifies gaps → gaps feed back into **standards improvements**
- ITIL, Lean, PMP, SAFe — all of these frameworks exist to operate and improve.
  The operational graph is the substrate that makes improvement measurable.

## Proposed Solution

Four spec additions backed by a Neo4j graph database.

### 1. Investigation Standards (`spec/investigation.md` — new file)

Defines how agents collect and classify evidence. Every agent's investigation
becomes comparable and composable.

#### Log Collection Standard

```yaml
log_collection:
  minimum_lines: 200
  categories:
    error_lines:
      grep: "error|fatal|exception|panic|traceback|oom|killed|refused|timeout|fail"
      purpose: "Diagnosis runs against these only"
    health_lines:
      grep: "health|ready|alive|200 OK|GET /health"
      purpose: "Excluded from diagnosis. Used for uptime calculation"
    app_lines:
      purpose: "Everything else. Available for context but not auto-diagnosed"
  agent_contract:
    - "Agents MUST separate log lines into these 3 categories before diagnosis"
    - "Diagnosis hints MUST only match against error_lines"
    - "Health check noise MUST NOT trigger pattern matching"
```

#### Exit Code Semantics (mandatory)

```yaml
exit_code_semantics:
  0: { class: "clean_shutdown", is_failure: false, action: "log_only" }
  1: { class: "app_error", is_failure: true, action: "investigate" }
  2: { class: "misuse", is_failure: true, action: "investigate_config" }
  137: { class: "sigkill", is_failure: true, action: "investigate_oom_or_external" }
  139: { class: "segfault", is_failure: true, action: "investigate_crash" }
  143: { class: "sigterm", is_failure: false, action: "log_only" }

agent_contract:
  - "Exit code MUST be included in every investigation report"
  - "Exit code 0 or 143 MUST NOT be classified as a failure"
  - "Exit code MUST be checked BEFORE log pattern matching"
  - "If exit code is 0 and container status is 'exited', diagnosis is 'clean_shutdown'"
```

#### Pattern Quality Requirements

```yaml
pattern_quality:
  rules:
    - "All patterns MUST use word boundaries (\\b) for short tokens"
    - "Numeric patterns (401, 403, 500) MUST require HTTP response context"
    - "Each pattern SHOULD include a false_positive_filter regex"
    - "Patterns MUST be tested against a false-positive corpus before shipping"

  example_good:
    name: "auth_failure"
    match: "\\bHTTP[/ ]\\d+\\.?\\d*\"?\\s+401\\b|\\b(?:unauthorized|authentication failed|invalid.token)\\b"
    false_positive_filter: "health.*200|GET /health.*OK"

  example_bad:
    name: "auth_failure"
    match: "(?i)401|403|unauthorized"
    why_bad: "Matches port numbers, version strings, request IDs containing '401'"
```

#### Evidence Schema

```yaml
investigation_report:
  required_fields:
    - target: string           # Container/service name
    - host: string             # Host where target runs
    - exit_code: integer|null  # Container exit code (null if still running)
    - uptime_seconds: integer  # Seconds since container started
    - restart_count: integer   # Docker restart count
    - error_lines: string[]    # Filtered error log lines
    - health_lines: string[]   # Filtered health check lines
    - resource_state:          # Host resource snapshot
        ram_percent: float
        disk_percent: float
        gpu_vram_percent: float|null
        gpu_temperature: float|null
    - dependency_health: map   # {dep_name: "healthy"|"unhealthy"|"missing"}
    - correlation_group: string|null  # Group ID if part of correlated failure
```

**Fixes**: GAP 1 (false positive patterns), GAP 2 (exit code analysis), GAP 6 (log window).

---

### 2. Neo4j Operational Graph

#### Why a Graph Database

The operational model is inherently a graph:
- Services depend on other services (dependency chains)
- Services run on hosts, use GPUs, mount volumes (resource sharing)
- Incidents correlate with other incidents (shared root cause)
- Events cause other events (causal chains)
- Problems aggregate incidents (pattern detection)
- Changes affect targets that have dependencies (blast radius)

SQLite handles flat CRUD well, but every interesting operational question is a
traversal: "What breaks if I restart caddy?" "Why did 4 containers die together?"
"What's the blast radius of this change?" These are graph queries.

#### Node Types

```cypher
// Infrastructure — container level
(:Service {name, host, service_type, critical, alert_policy, declared_image,
           declared_healthcheck, baseline_behavior, last_seen})
(:Host {name, ip, role, ram_gb, disk_tb})
(:GPU {host, index, model, vram_gb})
(:Network {name, subnet, vlan})
(:Volume {name, host, mount_path})

// Configuration Items — sub-service granularity
// A CI is anything with an operational lifecycle that can fail, expire,
// degrade, or cause impact. ITIL CI definition taken literally and deeply.
// See spec/cmdb.md for the full taxonomy (30+ CI types across 5 categories).
//
// All CIs share a common base: {name, type, service, properties, status}
// Type-specific fields live in properties (schemaless for extensibility).
// Relationships are first-class edges, not embedded fields.
(:CI {name, type, service, properties, status, created_at, last_seen})
// type: search | index | app | model | flow | endpoint | automation |
//       integration | library | queue | account | credential | license |
//       subscription | cert | zone | record | vlan | firewall_rule |
//       dataset | snapshot | backup_job | disk | nic | psu | controller |
//       device | scene | bridge | sensor

// Operations
(:Incident {id, title, severity, status, root_cause, detected_by,
            exit_code, investigation_summary, remediation_applied,
            created_at, resolved_at})
(:Problem {id, title, pattern, status, workstream, root_cause_analysis})
(:Change {id, description, operator, status, targets, created_at, closed_at})
(:Event {id, source, type, target, severity, data, timestamp})

// Intelligence
(:Runbook {name, service_type, version, failure_modes})
(:DiagnosisPattern {name, match_regex, false_positive_filter, confidence,
                    restart_safe, explanation})
(:CorrelationGroup {id, root_cause, created_at})
```

#### Edge Types

```cypher
// Infrastructure relationships
(:Service)-[:RUNS_ON]->(:Host)
(:Service)-[:USES_GPU {device_index}]->(:GPU)
(:Service)-[:DEPENDS_ON {type: "hard"|"soft"}]->(:Service)
(:Service)-[:CONNECTS_TO]->(:Network)
(:Service)-[:MOUNTS]->(:Volume)
(:GPU)-[:INSTALLED_ON]->(:Host)

// CI relationships — full taxonomy (see spec/cmdb.md for definitions)
// Structural
(:CI)-[:BELONGS_TO]->(:Service)
(:CI)-[:CONTAINS]->(:CI)                     // dataset contains snapshots
(:CI)-[:INSTALLED_ON]->(:Service|:GPU)

// Dependency (cross-service traversal paths)
(:CI)-[:DEPENDS_ON]->(:CI)                   // hard dependency
(:CI)-[:USES]->(:CI)                         // soft dependency
(:CI)-[:READS_FROM]->(:CI)                   // search reads index
(:CI)-[:WRITES_TO]->(:CI)                    // service writes to queue
(:CI)-[:AUTHENTICATES_WITH]->(:CI)           // service uses account/credential
(:CI)-[:FEEDS]->(:Service)                   // prowlarr feeds sonarr

// Infrastructure
(:CI)-[:LOADED_ON]->(:GPU)                   // model on GPU
(:CI)-[:STORED_ON]->(:Volume)                // data on storage
(:CI)-[:HOSTED_ON]->(:Host|:Network)         // runs on host/VLAN
(:CI)-[:SECURES]->(:CI)                      // cert secures endpoint
(:CI)-[:PROXIED_BY]->(:Service)              // endpoint behind proxy
(:CI)-[:ROUTES_TO]->(:Service|:CI)           // DNS/firewall routing
(:CI)-[:MANAGED_BY]->(:Service)              // lifecycle owner

// Operational
(:Incident)-[:AFFECTS_CI]->(:CI)             // CI-level incidents
(:Change)-[:CHANGED_CI]->(:CI)               // change touched this CI
(:CI)-[:MONITORED_BY]->(:CI)                 // monitoring relationship

// Operational relationships
(:Incident)-[:AFFECTS]->(:Service)
(:Incident)-[:DETECTED_ON]->(:Host)
(:Incident)-[:CAUSED_BY]->(:Incident)        // Causal chain
(:Incident)-[:MEMBER_OF]->(:CorrelationGroup)  // Shared root cause
(:Incident)-[:ESCALATED_TO]->(:Change)        // Incident drove a change
(:Problem)-[:CORRELATES]->(:Incident)         // Problem aggregates incidents
(:Change)-[:TARGETS]->(:Service)
(:Event)-[:TRIGGERED]->(:Incident)
(:Event)-[:PART_OF]->(:Change)
(:Incident)-[:RESOLVED_BY]->(:Event)

// Intelligence relationships
(:Service)-[:CLASSIFIED_AS {service_type}]->(:Runbook)
(:Runbook)-[:CONTAINS]->(:DiagnosisPattern)
(:DiagnosisPattern)-[:MATCHED_IN]->(:Incident)  // Pattern hit tracking

// Config drift
(:Service)-[:DECLARED_CONFIG {image, healthcheck, env_hash}]->(:Service)
// Self-edge with declared vs running state. Or:
(:Service)-[:DRIFT_DETECTED {field, declared, actual, detected_at}]->(:Service)
```

#### Key Queries This Enables

```cypher
// GAP 3: Correlated failure detection
// "Find all services that share GPU 0 on dockp03 and are currently down"
MATCH (s:Service)-[:USES_GPU]->(g:GPU {host: "tmtdockp03", index: 0})
MATCH (i:Incident {status: "open"})-[:AFFECTS]->(s)
RETURN g, collect(s.name) AS affected_services, collect(i) AS incidents

// Blast radius: "What breaks if caddy goes down?"
MATCH path = (s:Service)-[:DEPENDS_ON*1..5]->(target:Service {name: "caddy"})
RETURN s.name, s.critical, length(path) AS depth
ORDER BY depth

// Deploy impact: "What did this change touch and what depends on it?"
MATCH (c:Change {id: "CHG-xxx"})-[:TARGETS]->(t:Service)
OPTIONAL MATCH (dep:Service)-[:DEPENDS_ON*1..3]->(t)
RETURN t.name, collect(DISTINCT dep.name) AS downstream

// Pattern quality: "Which diagnosis patterns have the most false positives?"
MATCH (p:DiagnosisPattern)-[:MATCHED_IN]->(i:Incident)
WHERE i.root_cause <> p.name  // Pattern matched but wasn't the actual root cause
RETURN p.name, count(i) AS false_positives
ORDER BY false_positives DESC

// Gap analysis: "Which service types have no incidents resolved autonomously?"
MATCH (s:Service)-[:CLASSIFIED_AS]->(r:Runbook)
OPTIONAL MATCH (i:Incident)-[:AFFECTS]->(s)
WHERE i.remediation_applied IS NOT NULL
WITH r.service_type AS type, count(i) AS auto_resolved
WHERE auto_resolved = 0
RETURN type

// Config drift: "Which services have running config that doesn't match declared?"
MATCH (s:Service)
WHERE s.declared_image IS NOT NULL AND s.declared_image <> s.running_image
RETURN s.name, s.declared_image, s.running_image

// --- CI-Level Operational Intelligence ---

// "Search → Incident": Which saved search is causing this indexer incident?
MATCH (i:Incident)-[:AFFECTS_CI]->(idx:IndexCI)<-[:READS_FROM]-(s:SearchCI)
WHERE i.status = "open"
RETURN s.name, s.schedule, s.avg_runtime_ms, idx.name, i.title

// "Model → GPU → Incident": Which model caused the OOM?
MATCH (i:Incident)-[:AFFECTS]->(svc:Service)-[:USES_GPU]->(g:GPU)
MATCH (m:ModelCI)-[:LOADED_ON]->(g)
WHERE i.root_cause = "gpu_oom"
RETURN m.name, m.size_gb, g.vram_gb, svc.name, i.title

// "Cert → Endpoint → Proxy → Incident": Full TLS chain to failure
MATCH (c:CertCI)-[:SECURES]->(e:EndpointCI)-[:PROXIED_BY]->(proxy:Service)
WHERE c.expires_at < datetime() + duration({days: 30})
RETURN c.domain, c.expires_at, e.url, proxy.name AS proxy

// "Flow → Service → Change": What Prefect flow touched what during this change?
MATCH (f:FlowCI)-[:OPERATES_ON]->(s:Service)<-[:TARGETS]-(ch:Change)
WHERE ch.status = "in-progress"
RETURN f.name, s.name, ch.description

// "Search performance → Index pressure → Host resources"
MATCH (s:SearchCI)-[:READS_FROM]->(idx:IndexCI)-[:BELONGS_TO]->(svc:Service)-[:RUNS_ON]->(h:Host)
WHERE s.avg_runtime_ms > 30000  // searches taking >30s
RETURN s.name, s.avg_runtime_ms, idx.name, idx.current_size_gb, h.name
ORDER BY s.avg_runtime_ms DESC

// "What changed before this CI started failing?"
MATCH (i:Incident)-[:AFFECTS_CI]->(ci:CI)
MATCH (ch:Change)-[:CHANGED_CI]->(ci)
WHERE ch.closed_at > i.created_at - duration({hours: 24})
  AND ch.closed_at < i.created_at
RETURN ci.name, i.title, ch.description, ch.closed_at AS changed_at
ORDER BY ch.closed_at DESC

// --- Cross-Service CI Dependency Chains ---

// "Sonarr can't download — what's the root cause?"
// Traverse: sonarr → prowlarr indexer → sabnzbd → astraweb account
MATCH path = (svc:Service {name: "sonarr"})-[:DEPENDS_ON|FEEDS|AUTHENTICATES_WITH*1..5]->(root:CI)
WHERE root.status <> "healthy"
RETURN [n IN nodes(path) | n.name] AS chain, root.type AS root_type,
       root.name AS root_cause, root.properties.expires_at AS expires

// "What services break if this account expires?"
MATCH (acct:CI {type: "account", name: "astraweb-primary"})
MATCH path = (svc:Service)-[:DEPENDS_ON|FEEDS|AUTHENTICATES_WITH*1..5]->(acct)
RETURN svc.name, svc.critical, length(path) AS depth
ORDER BY svc.critical DESC, depth

// "Show me everything expiring in the next 30 days"
MATCH (ci:CI)
WHERE ci.properties.expires_at IS NOT NULL
  AND ci.properties.expires_at < datetime() + duration({days: 30})
OPTIONAL MATCH (svc:Service)-[:DEPENDS_ON|AUTHENTICATES_WITH*1..3]->(ci)
RETURN ci.type, ci.name, ci.properties.expires_at,
       collect(DISTINCT svc.name) AS affected_services
ORDER BY ci.properties.expires_at

// "What's the full dependency tree for Plex content delivery?"
MATCH path = (plex:Service {name: "plex"})<-[:FEEDS*1..6]-(upstream)
RETURN [n IN nodes(path) | coalesce(n.name, "?")] AS pipeline
// Returns: plex ← sonarr ← prowlarr ← indexer-ci ← account-ci

// "Which credential CIs have the most downstream dependents?"
MATCH (cred:CI {type: "credential"})<-[:AUTHENTICATES_WITH]-(consumer)
WITH cred, count(consumer) AS dependents
ORDER BY dependents DESC
RETURN cred.name, cred.properties.secret_path, dependents, cred.properties.expires_at
```

#### Deployment

```yaml
# Neo4j Community Edition — added to dockp04-automation stack
neo4j:
  container_name: corvus-neo4j
  image: neo4j:5-community
  restart: unless-stopped
  environment:
    NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
    NEO4J_PLUGINS: '["apoc"]'
    NEO4J_server_memory_heap_initial__size: 256m
    NEO4J_server_memory_heap_max__size: 512m
  volumes:
    - corvus-neo4j-data:/data
  ports:
    - "7474:7474"   # Browser UI (internal only)
    - "7687:7687"   # Bolt protocol
  networks:
    - infra-services
  healthcheck:
    test: ["CMD", "neo4j", "status"]
    interval: 30s
    timeout: 10s
    retries: 5
    start_period: 60s
```

Resource footprint: ~512MB RAM, minimal CPU. Community Edition is free, Apache 2.0 licensed.

**Fixes**: GAP 3 (correlated failures via graph traversal), GAP 7 (config drift as graph edges),
plus unlocks IQ-3 (cross-service correlation), BS-5 (cross-host cascade detection).

---

### 3. Correlation Groups (event model extension)

#### New Event Type

```yaml
event_types:
  correlation.group_created:
    when: "2+ incidents share a resource (GPU, network, volume, dependency)"
    severity: warning
    data:
      group_id: string
      root_cause: string
      member_incidents: string[]
      shared_resource: string        # "gpu:tmtdockp03:0" or "dependency:caddy"
      shared_resource_type: string   # "gpu", "network", "volume", "dependency"
```

#### Correlation Rules (evaluated during health sweep)

```yaml
correlation_rules:
  - name: "shared_gpu_failure"
    trigger: "2+ incidents on same host+gpu_index within same sweep"
    action: "Create CorrelationGroup, link incidents, single alert"
    root_cause_hint: "Check GPU state (VRAM, temperature, driver)"

  - name: "shared_dependency_failure"
    trigger: "2+ incidents where targets share a DEPENDS_ON edge to a common unhealthy service"
    action: "Create CorrelationGroup, investigate the dependency first"
    root_cause_hint: "Fix the dependency, dependents will likely recover"

  - name: "shared_host_failure"
    trigger: "5+ incidents on same host within same sweep"
    action: "Create CorrelationGroup, check host-level resources"
    root_cause_hint: "Host resource exhaustion (disk, RAM, network)"

  - name: "shared_volume_failure"
    trigger: "2+ incidents on services sharing a MOUNTS edge to the same volume"
    action: "Create CorrelationGroup, check volume/NFS health"
    root_cause_hint: "Storage failure (NFS timeout, disk full, mount lost)"
```

#### Agent Contract

```yaml
agent_contract:
  - "When creating multiple incidents in the same sweep, agents MUST check for
     correlation group eligibility via POST /ops/correlations/check"
  - "Agents MUST send a single Slack alert for a correlation group, not per-member"
  - "The group alert MUST include the shared resource and root cause hint"
  - "Individual member incidents are still created (for tracking) but are NOT
     separately alerted"
```

**Fixes**: GAP 3 directly. The docling scenario becomes one alert:
"GPU 0 failure group: ace-step (OOM), docling (clean shutdown), qwen3-asr, qwen3-tts."

---

### 4. Deploy Runbook (`runbooks/triage-deploy.yaml` — new runbook type)

```yaml
name: Deployment Failure Triage
type: triage
service_type: deploy
version: 1
description: >
  FMEA-informed investigation for CI/CD deployment failures.
  Covers GitHub Actions workflow failures with root cause analysis.

investigation:
  - name: Pull workflow logs
    type: deploy.workflow_logs
    params:
      run_id: "{{ run_id }}"
      repo: "{{ repo }}"
    outputs:
      workflow_logs: "{{ result }}"
    timeout: 30

  - name: Check target container health
    type: containers.inspect
    params:
      target: "{{ inferred_target }}"
    outputs:
      container_state: "{{ result }}"

  - name: Check config drift
    type: containers.drift_check
    params:
      target: "{{ inferred_target }}"
    outputs:
      drift_report: "{{ result }}"

diagnosis_hints:
  - pattern: "has no healthcheck configured"
    root_cause: stale_container_config
    restart_safe: false
    explanation: >
      Container was created before healthcheck was added to compose file.
      Docker Compose only recreates containers with changed config.
      Fix: docker compose up -d --force-recreate <target>

  - pattern: "dependency failed to start.*is unhealthy"
    root_cause: slow_startup
    restart_safe: false
    explanation: >
      Dependency health check timed out. Service may still be starting.
      Check current health status — if healthy now, re-run deploy.

  - pattern: "connection refused|ECONNREFUSED"
    root_cause: dependency_down
    restart_safe: false
    explanation: >
      A dependency is not accepting connections. Check upstream services.

  - pattern: "permission denied|EACCES"
    root_cause: auth_failure
    restart_safe: false
    explanation: >
      Runner or container lacks permissions. Check GitHub runner service
      account and Docker socket access.

  - pattern: "no space left on device|ENOSPC"
    root_cause: disk_full
    restart_safe: false
    explanation: >
      Host disk is full. Check Docker image cache and unused volumes.

remediation:
  restart_safe: false  # Deploys are never "just restart"
  escalation_triggers:
    - "data loss risk"
    - "rollback needed"
  auto_actions:
    stale_container_config:
      action: "force_recreate"
      command: "docker compose up -d --force-recreate {{ target }}"
      requires_approval: false  # Safe — just picks up new config
    slow_startup:
      action: "check_and_retry"
      steps:
        - "Check if target is currently healthy"
        - "If healthy: re-run workflow"
        - "If unhealthy: escalate with current logs"
      requires_approval: true
```

#### New Investigation Step Type

```yaml
investigation_step_types:
  deploy.workflow_logs:
    description: "Pull GitHub Actions workflow run logs and parse failure details"
    execution: agent-side
    params:
      run_id: "GitHub Actions run ID"
      repo: "Repository (owner/repo)"
    returns:
      failed_steps: "List of failed step names"
      error_messages: "Parsed error messages from step logs"
      deploy_target: "Inferred target stack/service"
      workflow_url: "Link to workflow run"
```

**Fixes**: GAP 4 directly. Deploy failures get the same FMEA treatment as container failures.

---

### 5. Config Drift Detection (CMDB extension)

#### New CMDB Fields

```yaml
cmdb_extension:
  declared_state:
    declared_image: string|null      # e.g., "caddy:2-alpine"
    declared_healthcheck: boolean    # Whether compose defines a healthcheck
    declared_env_hash: string|null   # SHA256 of env var names (not values)
    declared_networks: string[]      # Network memberships from compose
    last_declared_at: datetime       # When declared state was last updated

  runtime_state:
    running_image: string|null       # Actual image the container is running
    running_healthcheck: boolean     # Whether running container has healthcheck
    running_env_hash: string|null    # SHA256 of actual env var names
    last_checked_at: datetime
```

#### New Investigation Step Type

```yaml
investigation_step_types:
  containers.drift_check:
    description: "Compare running container config against CMDB declared state"
    execution: agent-side
    params:
      target: "Container name"
    returns:
      has_drift: boolean
      drift_fields: list    # ["healthcheck", "image", "env"]
      declared: map         # {image: "caddy:2-alpine", healthcheck: true}
      actual: map           # {image: "caddy:2-alpine", healthcheck: false}
```

#### New Gap Pattern

```yaml
gap_patterns:
  "gap:coverage:config-drift:{target}":
    trigger: "drift_check finds declared != running"
    workstream: NFI  # Needs further investigation
    severity: warning
    auto_problem: true
```

#### Population Strategy

Declared state gets populated from two sources:
1. **GitOps pipeline**: On deploy, CI/CD parses compose file and POSTs declared
   state to Corvus CMDB. This is the authoritative source.
2. **Discovery sweep**: NemoClaw periodically compares running containers against
   CMDB declared state and flags drift.

**Fixes**: GAP 7 directly. The certbot scenario would have been caught by drift detection
before it caused a deploy failure.

---

## Migration Path

### Phase 1: Spec + Data Model (this session)
- Write `spec/investigation.md`
- Extend `spec/events.md` with correlation group event type
- Extend `spec/cmdb.md` with drift detection fields
- Add `runbooks/triage-deploy.yaml`
- Update PRODUCT_VISION.md — Neo4j moves from "long-term" to "next sprint"

### Phase 2: Neo4j Foundation (next session)
- Deploy Neo4j Community on dockp04
- Implement graph schema (nodes + edges)
- Migrate CMDB data from SQLite → Neo4j
- Add Corvus server Neo4j driver (async neo4j-python-driver)
- Dual-write: SQLite for backward compat, Neo4j as primary for graph queries

### Phase 3: NemoClaw Migration (following session)
- NemoClaw drops hardcoded log patterns → calls Corvus `POST /ops/runbooks/triage`
- NemoClaw drops independent alerting per container → calls Corvus correlation check
- NemoClaw drops deploy passthrough → uses deploy runbook
- NemoClaw adds exit code to all investigation reports
- NemoClaw adds log category separation (error/health/app)

### Phase 4: CC Integration
- CC governance rules updated to call Corvus investigation standards
- CC ops protocol uses Corvus correlation groups
- CC gets blast radius queries via Neo4j traversal

## Risk Assessment

| Risk | Blast Radius | Reversibility | Mitigation |
|------|-------------|---------------|------------|
| Neo4j container on dockp04 | Contained | Easy (remove container) | Non-critical — Corvus falls back to SQLite |
| CMDB schema extension | None (additive) | Trivial | New fields are nullable |
| Pattern quality migration | Multi-service | Moderate | Dual-run: old patterns + new, compare results before cutover |
| NemoClaw consuming Corvus | Multi-service | Easy (revert to local patterns) | Feature flag per capability |

## Rollback Plan

Every phase is independently reversible:
- Phase 1: Spec docs are additive — no existing behavior changes
- Phase 2: Neo4j is additive — SQLite continues to work. Remove container to rollback
- Phase 3: NemoClaw feature flags per capability. Flip flag to revert to local patterns
- Phase 4: CC rules are additive — can be reverted by editing governance.md

## Advocate Challenge Resolution

6 findings raised (1 BLOCKING, 3 HIGH, 2 ADVISORY). All resolved.

### Finding 1 (BLOCKING): Neo4j over-engineering for 92 services
**Resolution**: Accepted — proceed with Neo4j. Todd's directive: "design for where
we're going, not where we are." This is a product, not a script. Graph queries are
the natural model for operational intelligence. 92 services today, but the product
vision targets organizations with 500+ services across multiple agent fleets.
Learning Neo4j patterns now with a small graph is cheaper than migrating later.

### Finding 2 (HIGH): Dual-write has no exit criteria
**Resolution**: Added concrete cutover. Phase 3 completion = SQLite becomes read-only
backup. 30-day validation window where both are checked. After validation:
SQLite drops operational tables, keeps only simple key-value state (API keys, config).

### Finding 3 (HIGH): Auto force-recreate without config validation
**Resolution**: Auto force-recreate only for non-critical services. Critical services
(per CMDB `critical: true`) require human approval even for stale_container_config.
Pre-flight check added: verify compose file parses without error before executing.

### Finding 4 (HIGH): Agent contracts are documentation, not enforcement
**Resolution**: Corvus server adds validation on `POST /ops/runbooks/triage`:
- Missing `exit_code` → 422 with message "exit_code is required per investigation standard"
- Unseparated log lines (no `error_lines` key) → 422 with message
- Missing `resource_state` → warning header (not rejection — graceful degradation)
This makes the spec enforceable, not aspirational.

### Finding 5 (ADVISORY): Pattern quality enforcement is manual
**Resolution**: Accepted for Phase 1. Add pattern validation endpoint
(`POST /ops/patterns/validate`) in Phase 3 that checks word boundaries and
runs against a false-positive test corpus.

### Finding 6 (ADVISORY): Dependency data accuracy
**Resolution**: Accepted. Phase 2 populates DEPENDS_ON edges from compose
`depends_on` fields (authoritative) and Docker network co-membership (heuristic,
marked as `type: "inferred"`). Agents can distinguish hard vs inferred dependencies.

## Dependency Map

```
spec/investigation.md ──► NemoClaw log collection
                      ──► NemoClaw exit code handling
                      ──► NemoClaw pattern matching
spec/events.md (ext)  ──► Corvus server correlation endpoint
                      ──► NemoClaw sweep correlation
spec/cmdb.md (ext)    ──► GitOps pipeline (declared state)
                      ──► NemoClaw drift detection
runbooks/triage-deploy ──► NemoClaw deploy_manager
Neo4j                  ──► Corvus server graph queries
                      ──► CC blast radius queries
                      ──► Correlation group detection
```
