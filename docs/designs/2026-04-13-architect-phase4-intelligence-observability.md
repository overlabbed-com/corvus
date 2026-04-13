# Corvus Phase 4: Intelligence & Observability — Architect Design

> **Date**: 2026-04-13
> **Agent**: Architect
> **Status**: Pending
> **Trigger**: Phase 3 completion — foundation is solid, now unlock operational intelligence

## Executive Summary

Phase 4 transforms Corvus from an **event collector** into an **operational intelligence platform**. The foundation built in Phases 1-3 (event protocol, CMDB, runbooks, Neo4j graph) is now complete. Phase 4 activates the full power of that foundation:

1. **Correlation Groups** — Multi-incident root cause detection
2. **CI-Level Intelligence** — Sub-service operational visibility
3. **Deploy Runbook Integration** — CI/CD failure triage
4. **Config Drift Detection** — GitOps state validation
5. **Graph-Powered Queries** — Blast radius, dependency chains, expiry alerts
6. **Pattern Quality Management** — Self-improving diagnosis rules

This is not incremental improvement. This is the difference between "Corvus saw 4 alerts" and "Corvus identified GPU 0 OOM as the shared root cause affecting 4 services."

## Current State Assessment

### What's Already Built (Phases 1-3)

✅ **Event Protocol** — Full event taxonomy, OCSF transformation, SIEM forwarding
✅ **CMDB** — Service registry with 12 service types, basic CI support
✅ **Runbooks** — 13 FMEA triage runbooks loaded and executable
✅ **Neo4j Graph** — Driver, schema, health tracking, safe mode
✅ **Investigation Standards** — Spec defined, exit code semantics, pattern quality rules
✅ **Graph Queries API** — Blast radius, dependency chains, drift detection endpoints

### What's Missing (Phase 4 Gaps)

❌ **Correlation Groups** — No `correlation.group_created` event type implemented
❌ **CI Operational Model** — CIs registered but no incident/problem relationships
❌ **Deploy Triage Integration** — Runbook exists but not consumed by ops-agent
❌ **Config Drift Enforcement** — Fields exist but no automated detection loop
❌ **Pattern Quality API** — No validation endpoint for diagnosis patterns
❌ **Cross-Service Intelligence** — Graph queries exist but not integrated into triage

## Design Principle

**Corvus doesn't just collect events — it understands operational causality.**

Every operational question should be answerable via graph traversal:
- "Why did these 4 services fail together?" → Shared GPU correlation
- "What breaks if I restart caddy?" → Blast radius query
- "What changed before this incident?" → Change-incident CI linkage
- "What's expiring soon?" → Expiry query across all CI types
- "Why is this search slow?" → Search → Index → Host resource chain

## Proposed Solution

### 1. Correlation Groups (Spec + Implementation)

#### Event Type Extension

Already defined in `spec/events.md`, but not implemented in server:

```yaml
event_types:
  correlation.group_created:
    when: "2+ incidents share a resource (GPU, network, volume, dependency)"
    severity: warning
    data:
      group_id: string
      root_cause: string
      member_incidents: string[]
      shared_resource: string
      shared_resource_type: string  # "gpu", "network", "volume", "dependency"
```

#### Implementation Requirements

**New Router**: `src/routers/correlations.py`

```python
@router.post("/correlations/check")
async def check_correlation(request: CorrelationCheckRequest):
    """Check if incidents share a resource and should be grouped."""
    # Query Neo4j for shared resources
    # Return correlation group if eligible
```

**New Background Task**: `src/tasks/correlation.py`

```python
async def sweep_for_correlations():
    """Run after every health sweep to detect correlation opportunities."""
    # Find open incidents from last sweep
    # Group by shared GPU, network, volume, dependency
    # Create correlation.group_created events
```

**Neo4j Schema Additions**:

```cypher
// Correlation group node
(:CorrelationGroup {id, root_cause, shared_resource, shared_resource_type, created_at})

// Relationships
(:Incident)-[:MEMBER_OF]->(:CorrelationGroup)
(:CorrelationGroup)-[:ROOT_CAUSED_BY]->(:Service|:CI|:GPU)
```

**Agent Contract**:

- When creating multiple incidents in the same sweep, agents MUST call
  `POST /ops/correlations/check` before alerting
- Agents MUST send a single Slack alert for a correlation group, not per-member
- Individual incidents are still created (for tracking) but are NOT separately alerted

**Fixes**: GAP 3 (correlated failures), docling scenario (4 independent alerts → 1 group alert)

---

### 2. CI-Level Operational Intelligence

#### Problem Statement

Current incident model: "Service X is down"
Missing model: "The Astraweb account expired, which broke sabnzbd, which starved Sonarr"

The CI layer bridges this gap. Every operational record (incident, problem, change)
should be linkable to specific CIs, not just services.

#### Implementation Requirements

**Spec Extension**: `spec/cmdb.md` already defines CI types and relationships
**Database Extension**: Add CI operational fields to `ops_cmdb` table or create `ops_ci` table

```sql
-- Option 1: Extend ops_cmdb (simpler, recommended for Phase 4)
ALTER TABLE ops_cmdb ADD COLUMN ci_type TEXT;  -- search, index, model, account, etc.
ALTER TABLE ops_cmdb ADD COLUMN ci_properties TEXT;  -- JSON blob for type-specific fields
ALTER TABLE ops_cmdb ADD COLUMN ci_status TEXT;  -- healthy, degraded, expired

-- Option 2: Separate ops_ci table (cleaner, better for Phase 5)
CREATE TABLE ops_ci (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    service TEXT NOT NULL,
    properties TEXT,
    status TEXT,
    created_at TEXT,
    last_seen TEXT,
    FOREIGN KEY (service) REFERENCES ops_cmdb(name)
);
```

**Neo4j Schema**: Already defined in graph.py constraints

**API Endpoints**:

```python
# Existing: POST /ops/cmdb/ci — register CI
# Add: GET /ops/cmdb/ci/{name}/impact — CI impact analysis
# Add: GET /ops/cmdb/ci/expiring?days=30 — CI expiry query
# Add: POST /ops/cmdb/ci/bulk-sync — bulk CI registration
```

**Graph Query Examples** (to be implemented):

```cypher
// "Search → Incident": Which saved search is causing this indexer incident?
MATCH (i:Incident)-[:AFFECTS_CI]->(idx:CI {type: "index"})<-[:READS_FROM]-(s:CI {type: "search"})
WHERE i.status = "open"
RETURN s.name, s.properties.schedule, i.title

// "Model → GPU → Incident": Which model caused the OOM?
MATCH (i:Incident)-[:AFFECTS]->(svc:Service)-[:USES_GPU]->(g:GPU)
MATCH (m:CI {type: "model"})-[:LOADED_ON]->(g)
WHERE i.root_cause = "gpu_oom"
RETURN m.name, m.properties.size_gb, g.vram_gb, i.title

// "Cert → Endpoint → Proxy → Incident": Full TLS chain to failure
MATCH (c:CI {type: "cert"})-[:SECURES]->(e:CI {type: "endpoint"})-[:PROXIED_BY]->(proxy:Service)
WHERE c.properties.expires_at < datetime() + duration({days: 30})
RETURN c.properties.domain, c.properties.expires_at, e.properties.url, proxy.name
```

**Fixes**: Cross-service root cause analysis, CI-level incident tracking

---

### 3. Deploy Runbook Integration

#### Problem Statement

Deploy runbook exists (`runbooks/triage-deploy.yaml`) but ops-agent still does
"passthrough" — reports "Step 'Deploy stack' failed" without root cause analysis.

#### Implementation Requirements

**New Investigation Step Type**: Add to runbook executor

```python
INVESTIGATION_STEP_TYPES = {
    "deploy.workflow_logs": {
        "description": "Pull GitHub Actions workflow run logs",
        "execution": "agent-side",  # Agent fetches logs, sends to Corvus
        "params": {"run_id": str, "repo": str},
        "returns": {"failed_steps": list, "error_messages": list, "deploy_target": str}
    },
    "containers.drift_check": {
        "description": "Compare running container config against CMDB declared state",
        "execution": "agent-side",
        "params": {"target": str},
        "returns": {"has_drift": bool, "drift_fields": list, "declared": dict, "actual": dict}
    }
}
```

**Runbook Executor Enhancement**:

```python
async def execute_investigation_step(step: InvestigationStep, context: dict):
    """Execute investigation step based on type."""
    step_type = step.type
    
    if step_type == "deploy.workflow_logs":
        # Agent-side: caller already fetched logs, just parse
        return parse_workflow_logs(step.params, context["investigation_data"])
    
    elif step_type == "containers.drift_check":
        # Agent-side: caller already inspected container, just compare
        return compare_drift(step.params, context["investigation_data"])
    
    # ... existing container inspection logic
```

**Deploy Manager Integration**:

ops-agent's deploy_manager must:
1. Before deploy: `POST /ops/changes` to open change window
2. On deploy failure: `POST /ops/runbooks/triage` with `service_type: "deploy"`
3. Pass workflow logs and container state as `investigation_data`
4. Use diagnosis hints to suggest remediation
5. On success: `POST /ops/changes/{id}/close`

**Fixes**: GAP 4 (deploy passthrough), certbot scenario (would have detected drift before failure)

---

### 4. Config Drift Detection Loop

#### Problem Statement

CMDB has `declared_image`, `runtime_image`, `drift_detected` fields but no
automated detection loop. Drift is only flagged when an agent manually checks.

#### Implementation Requirements

**New Background Task**: `src/tasks/drift_detection.py`

```python
async def sweep_for_drift():
    """Compare running containers against CMDB declared state."""
    # For each service in CMDB:
    #   1. Inspect running container (Docker API)
    #   2. Compare image, healthcheck, env vars against declared state
    #   3. If drift detected: update CMDB, create gap problem
    #   4. Emit gap:coverage:config-drift:{target} event
```

**CMDB Update Logic**:

```python
async def update_service_drift_status(service_name: str, drift_report: dict):
    """Update CMDB with drift detection results."""
    db = await get_db()
    try:
        await db.execute(
            """UPDATE ops_cmdb SET
               runtime_image = ?,
               runtime_healthcheck = ?,
               drift_detected = ?,
               drift_fields = ?,
               last_drift_check = ?
               WHERE name = ?""",
            (
                drift_report["runtime_image"],
                drift_report["runtime_healthcheck"],
                drift_report["has_drift"],
                json.dumps(drift_report["drift_fields"]),
                datetime.now(UTC).isoformat(),
                service_name,
            ),
        )
        await db.commit()
    finally:
        await db.close()
```

**Gap Problem Creation**:

```python
async def create_drift_gap(service_name: str, drift_fields: list):
    """Create gap problem for config drift."""
    problem = {
        "status": "identified",
        "title": f"Config drift detected on {service_name}",
        "pattern": f"gap:coverage:config-drift:{service_name}",
        "root_cause": f"Running config diverges from declared state: {', '.join(drift_fields)}",
        "recommended_fix": "Run: docker compose up -d --force-recreate " + service_name,
        "workaround": "Service may behave unexpectedly until drift is resolved"
    }
    await problems.create(problem)
```

**GitOps Pipeline Integration** (external to Corvus, but documented):

On every deploy, CI/CD must:
1. Parse compose file
2. Extract declared state (image, healthcheck, env vars)
3. `PATCH /ops/cmdb/{service}` with declared state

**Fixes**: GAP 7 (config drift), prevents stale_container_config failures

---

### 5. Pattern Quality Management

#### Problem Statement

Diagnosis patterns in runbooks are not validated. A pattern like `(?i)401` can
trigger false positives on port numbers, version strings, etc.

#### Implementation Requirements

**New Router**: `src/routers/patterns.py`

```python
@router.post("/patterns/validate")
async def validate_pattern(request: PatternValidationRequest):
    """Validate a diagnosis pattern against quality rules and test corpus."""
    # Check word boundary requirements
    # Run against false-positive corpus
    # Return validation result with suggestions
```

**Pattern Quality Rules**:

```python
PATTERN_QUALITY_RULES = {
    "word_boundaries": {
        "rule": "Tokens shorter than 6 characters MUST use \\b boundaries",
        "example_bad": r"(?i)401",
        "example_good": r"\bHTTP[/ ]\d+\.?\d*"?\s+401\b",
    },
    "http_context": {
        "rule": "HTTP status codes MUST require HTTP response context",
        "example_bad": r"(?i)unauthorized",
        "example_good": r"\bHTTP[/ ]\d+\.?\d*"?\s+401\b|\\b(unauthorized|authentication failed)\b",
    },
    "false_positive_filter": {
        "rule": "Each pattern SHOULD include a false_positive_filter regex",
        "example": r"health.*200|GET /health.*OK",
    }
}
```

**False-Positive Corpus**:

```python
FALSE_POSITIVE_CORPUS = [
    "2026-03-30 08:09:00 INFO Health check returned 200 OK",
    "2026-03-30 08:09:01 INFO Port 4010 is listening",
    "2026-03-30 08:09:02 INFO Version 4.0.1 deployed",
    "2026-03-30 08:09:03 INFO Request ID: 401abc-def",
    # ... 100+ test cases
]
```

**Pattern Hit Tracking**:

```cypher
// Track which patterns match which incidents
(:DiagnosisPattern)-[:MATCHED_IN {timestamp, was_root_cause: boolean}]->(:Incident)

// Query: "Which patterns have the most false positives?"
MATCH (p:DiagnosisPattern)-[:MATCHED_IN]->(i:Incident)
WHERE i.root_cause <> p.name
RETURN p.name, count(i) AS false_positives
ORDER BY false_positives DESC
```

**Fixes**: Pattern quality enforcement, reduces false positive alerts

---

### 6. Graph-Powered Triage Enhancement

#### Problem Statement

Triage currently runs diagnosis hints against error logs. It doesn't leverage
the graph to understand blast radius, dependency health, or shared resources.

#### Implementation Requirements

**Triage Executor Enhancement**:

```python
async def execute_triage(runbook: Runbook, target: str, host: str, investigation_data: dict):
    """Execute triage with graph-powered context."""
    
    # 1. Get service dependency health from graph
    dependency_health = await get_dependency_health(target)
    
    # 2. Check if target is part of a correlation group
    correlation_group = await get_correlation_group(target)
    
    # 3. Get blast radius for escalation context
    blast_radius = await get_blast_radius(target)
    
    # 4. Run diagnosis hints with graph context
    diagnosis = await run_diagnosis(runbook, investigation_data, {
        "dependency_health": dependency_health,
        "correlation_group": correlation_group,
        "blast_radius": blast_radius,
    })
    
    return diagnosis
```

**Graph Context Functions**:

```python
async def get_dependency_health(service: str) -> dict:
    """Get health status of all dependencies."""
    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (s:Service {name: $name})-[:DEPENDS_ON]->(dep:Service)
            OPTIONAL MATCH (inc:Incident {status: "open"})-[:AFFECTS]->(dep)
            RETURN dep.name AS name,
                   count(inc) > 0 AS is_unhealthy
            """,
            name=service,
        )
        return {rec["name"]: "unhealthy" if rec["is_unhealthy"] else "healthy" async for rec in result}

async def get_correlation_group(service: str) -> dict | None:
    """Check if service is part of a correlation group."""
    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (i:Incident)-[:AFFECTS]->(s:Service {name: $name})
            MATCH (i)-[:MEMBER_OF]->(cg:CorrelationGroup)
            RETURN cg.id AS group_id, cg.root_cause AS root_cause,
                   size((cg)<-[:MEMBER_OF]-()) AS member_count
            """,
            name=service,
        )
        rec = await result.single()
        return dict(rec) if rec else None
```

**Triage Output Enhancement**:

```json
{
  "triage_id": "TRG-A1B2C3D4",
  "target": "docling",
  "diagnosis": "gpu_oom",
  "confidence": 0.92,
  "correlation_group": {
    "group_id": "CG-E5F6G7H8",
    "root_cause": "CUDA OOM on GPU 0",
    "member_count": 4
  },
  "dependency_health": {
    "caddy": "healthy",
    "nfs-models": "healthy"
  },
  "blast_radius": {
    "affected_services": ["qwen3-asr", "qwen3-tts", "ace-step"],
    "critical_count": 2
  },
  "recommended_action": "Investigate GPU 0 state. Do not restart individual services — fix root cause first."
}
```

**Fixes**: Triage becomes context-aware, not just pattern matching

---

## Implementation Plan

### Phase 4.1: Correlation Groups (Week 1)

**Deliverables**:
- [ ] `src/routers/correlations.py` — correlation check endpoint
- [ ] `src/tasks/correlation.py` — background correlation sweep
- [ ] Neo4j schema: CorrelationGroup nodes + relationships
- [ ] Event emission: `correlation.group_created`
- [ ] Update `spec/events.md` with correlation group data schema

**Tests**:
- [ ] Test: 2 incidents on same GPU → correlation group created
- [ ] Test: 5 incidents on same host → correlation group created
- [ ] Test: Independent incidents → no correlation group

**Exit Criterion**: ops-agent can create correlation groups during sweep

---

### Phase 4.2: CI Operational Model (Week 2)

**Deliverables**:
- [ ] Extend `ops_cmdb` table with CI fields (or create `ops_ci` table)
- [ ] `GET /ops/cmdb/ci/{name}/impact` — CI impact analysis
- [ ] `GET /ops/cmdb/ci/expiring` — CI expiry query
- [ ] Neo4j CI relationship population from CMDB
- [ ] Update `spec/cmdb.md` with CI operational fields

**Tests**:
- [ ] Test: Register CI with relationships
- [ ] Test: Query CI impact (what depends on this CI)
- [ ] Test: Query expiring CIs in next 30 days

**Exit Criterion**: CIs can be registered and queried with operational context

---

### Phase 4.3: Deploy Triage Integration (Week 3)

**Deliverables**:
- [ ] Extend runbook executor with `deploy.workflow_logs` and `containers.drift_check`
- [ ] `src/discovery/deploy_manager.py` — integrate with triage flow
- [ ] Update ops-agent governance rules to use deploy triage
- [ ] Document GitOps pipeline integration for declared state

**Tests**:
- [ ] Test: Deploy failure → triage returns stale_container_config diagnosis
- [ ] Test: Deploy failure → triage returns slow_startup diagnosis
- [ ] Test: Drift check detects healthcheck mismatch

**Exit Criterion**: Deploy failures get FMEA triage, not passthrough

---

### Phase 4.4: Config Drift Loop (Week 4)

**Deliverables**:
- [ ] `src/tasks/drift_detection.py` — automated drift sweep
- [ ] CMDB drift update logic
- [ ] Gap problem creation for drift
- [ ] `GET /ops/cmdb/{name}/drift` — detailed drift report
- [ ] Update `spec/cmdb.md` with drift detection spec

**Tests**:
- [ ] Test: Container created before healthcheck → drift detected
- [ ] Test: Image tag change → drift detected
- [ ] Test: No drift → no gap problem created

**Exit Criterion**: Drift is automatically detected and logged as gap problems

---

### Phase 4.5: Pattern Quality API (Week 5)

**Deliverables**:
- [ ] `src/routers/patterns.py` — pattern validation endpoint
- [ ] False-positive corpus (100+ test cases)
- [ ] Pattern quality rule engine
- [ ] Neo4j `DiagnosisPattern` node creation from runbooks
- [ ] Pattern hit tracking during triage

**Tests**:
- [ ] Test: Bad pattern (no word boundaries) → validation fails
- [ ] Test: Good pattern → validation passes
- [ ] Test: Pattern matches false-positive corpus → warning

**Exit Criterion**: Patterns can be validated before deployment

---

### Phase 4.6: Graph-Powered Triage (Week 6)

**Deliverables**:
- [ ] Triage executor enhancement with graph context
- [ ] `get_dependency_health`, `get_correlation_group`, `get_blast_radius` functions
- [ ] Triage output enhancement with graph context
- [ ] Update runbook executor to include graph data

**Tests**:
- [ ] Test: Triage returns correlation group info
- [ ] Test: Triage returns dependency health
- [ ] Test: Triage recommends "fix root cause first" for correlated failures

**Exit Criterion**: Triage is context-aware, not just pattern matching

---

## Risk Assessment

| Risk | Blast Radius | Reversibility | Mitigation |
|------|-------------|---------------|------------|
| Correlation groups create false positives | Low | Easy (disable correlation check) | Start with conservative thresholds (3+ incidents, not 2) |
| CI model adds complexity to CMDB | Medium | Moderate (additive fields) | Phase 4.2 uses additive schema changes only |
| Deploy triage breaks existing deploy flow | Medium | Easy (feature flag) | Feature flag: `CORVUS_DEPLOY_TRIAGE_ENABLED` |
| Drift detection creates noise | Medium | Easy (adjust thresholds) | Start with critical services only, expand gradually |
| Pattern validation blocks valid patterns | Low | Easy (whitelist exceptions) | Validation is advisory in Phase 4, mandatory in Phase 5 |
| Graph-powered triage slows response time | Low | Easy (cache graph queries) | Cache blast radius and dependency health for 5 minutes |

## Rollback Plan

Every Phase 4 sub-phase is independently reversible:
- **4.1**: Disable correlation sweep task, agents fall back to independent alerts
- **4.2**: CI fields are additive, queries without CI data still work
- **4.3**: Feature flag disables deploy triage, reverts to passthrough
- **4.4**: Disable drift sweep task, manual drift check still available
- **4.5**: Pattern validation is advisory, doesn't block deployment
- **4.6**: Triage falls back to pattern-only mode if graph unavailable

## Success Metrics

| Metric | Baseline | Phase 4 Target |
|--------|----------|----------------|
| Correlated incidents detected | 0% | >80% of shared-resource failures |
| Deploy failure MTTR | ~30 min (manual) | <5 min (auto-diagnosed) |
| Config drift detection time | ~24h (manual discovery) | <1h (automated sweep) |
| False positive alert rate | ~25% | <10% |
| Triage context awareness | 0% (pattern-only) | 100% (graph-enhanced) |
| CI-level incident tracking | 0% | 100% of CIs with operational lifecycle |

## Dependency Map

```
Phase 4.1 (Correlation) ──► Neo4j graph, events, incidents
Phase 4.2 (CI Model) ─────► CMDB, Neo4j graph
Phase 4.3 (Deploy Triage) ─► Runbook executor, ops-agent
Phase 4.4 (Drift Loop) ───► CMDB, Neo4j graph, gap problems
Phase 4.5 (Pattern API) ──► Runbooks, Neo4j graph
Phase 4.6 (Graph Triage) ─► All of the above + triage executor
```

## Agent Contract Updates

Phase 4 adds these obligations to the ops protocol:

**Correlation**:
- When creating multiple incidents in the same sweep, agents MUST call
  `POST /ops/correlations/check` before alerting
- Agents MUST respect correlation groups (single alert, not per-member)

**Deploy Triage**:
- On deploy failure, agents MUST call `POST /ops/runbooks/triage` with
  `service_type: "deploy"` and workflow logs
- Agents MUST use diagnosis hints for remediation suggestions

**Config Drift**:
- On every deploy, GitOps pipeline MUST update declared state via
  `PATCH /ops/cmdb/{service}`
- Agents MUST check drift status before recommending restart

**Pattern Quality**:
- Before adding diagnosis patterns to runbooks, agents SHOULD validate
  via `POST /ops/patterns/validate`
- Agents MUST use word boundaries for short tokens (<6 chars)

## Exit Criteria

Phase 4 is complete when:
1. ✅ Correlation groups are created automatically during sweeps
2. ✅ CIs can be registered with operational relationships
3. ✅ Deploy failures get FMEA triage (not passthrough)
4. ✅ Config drift is detected automatically (<1h detection time)
5. ✅ Diagnosis patterns can be validated against quality rules
6. ✅ Triage includes graph context (dependency health, blast radius, correlation)
7. ✅ False positive rate <10% (measured over 50 incidents)
8. ✅ All Phase 4 tests pass (minimum 30 new tests)

## Next Steps

After Phase 4 completes, Phase 5 will focus on:
- **Autonomous Remediation** — Self-healing for common failure modes
- **Predictive Analytics** — ML-based anomaly detection
- **Multi-Tenant Support** — Organization isolation, RBAC at scale
- **Marketplace** — Community runbooks, diagnosis patterns, integrations

---

**Approved by**: [Pending Advocate challenge]
**Target Start Date**: 2026-04-13
**Target Completion Date**: 2026-05-17 (6 weeks)
