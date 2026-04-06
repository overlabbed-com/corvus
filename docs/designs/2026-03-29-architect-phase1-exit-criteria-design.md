# UOP Phase 1 Exit Criteria & Operationalized Blind Spot Detection

> Agent: Architect
> Workspace: automation
> Project: unified-ops-protocol
> Risk Level: AUTO (design only)
> Generated: 2026-03-29

## Summary

Redefines UOP Phase 1 as having five sub-phases with hard exit criteria. The system
cannot enter Phase 2 (CI/NFI workstreams) until the foundation is proven, the
feedback loop is closed, the signal is clean, and blind spot detection is
operationalized. Blind spot detection is not a feature — it's the mechanism by
which the system continuously knows what it doesn't know and generates problem
records to drive its own improvement.

## Revised Phase 1 Structure

### 1a: Tools + Rules — DONE
- `ops_check_target`, `ops_watch_events`, target status API
- Governance rules, ops-protocol.md, agent file updates

### 1b: Compliance Instrumentation
**Exit criterion**: >90% of agent MODIFY+ actions have corresponding SOP events, measured over 10 sessions.

Deliverables:
- Compliance counter in Admin API: every target check and event emission logged
- Session-end compliance audit: compare agent actions vs SOP events
- Extend `GET /ops/metrics` with compliance stats
- Gap: "Agent took action X but didn't emit event" → auto-flagged

### 1c: Feedback Loop
**Exit criterion**: Runbook effectiveness and resolution time are measured and queryable.

Deliverables:
- Runbook hit tracking in triage.py (which runbook fired, did it match)
- Resolution time by service_type (from incident created_at to resolved_at)
- Trust ledger bulk promotion: action types with >95% success rate → AUTO
- Extend `GET /ops/metrics` with triage effectiveness stats

### 1d: Signal Quality
**Exit criterion**: False positive rate < 20%. Per-service baselines in CMDB.

Deliverables:
- CMDB `baseline_behavior` populated for high-noise services (certbot, autoheal, etc.)
- ops-agent triage checks baseline before alerting: "certbot restarts daily = not incident"
- Intelligent severity scoring: service_type + critical + dependency_count → score
- False positive tracking: incidents created then immediately resolved with no action

### 1e: Operationalized Blind Spot Detection
**Exit criterion**: Gap detection is automated, produces problem records, and routes to CI/NFI.

This is the **core operational capability** — the system continuously knows what it
doesn't know. Not a report. Not a checklist. An automated sensor embedded in the
operational loop.

## Blind Spot Detection: Detailed Design

### Gap Sources (where blind spots are detected)

Every gap source runs automatically as part of existing operational loops:

| Source | Trigger | Gap Type | Workstream |
|--------|---------|----------|------------|
| Triage: `UNKNOWN` diagnosis | Every triage cycle | `gap:accuracy:unclassifiable` | CI |
| Triage: no runbook for service_type | Every triage cycle | `gap:coverage:no-runbook` | NFI |
| Triage: generic fallback used | Every triage cycle | `gap:coverage:generic-fallback` | NFI |
| Incident: Operator resolves manually | Every manual resolution | `gap:autonomy:manual-resolution` | CI |
| Incident: fix ≠ runbook recommendation | Every resolution | `gap:accuracy:wrong-recommendation` | CI |
| Incident: resolution time > 2x baseline | Every resolution | `gap:efficiency:slow-resolution` | CI |
| Sweep: service not seen in 7 days | Every sweep | `gap:monitoring:unseen-service` | NFI |
| CMDB: service has no service_type | Every discovery sync | `gap:coverage:untyped-service` | NFI |
| Threat model: finding unaddressed > 30d | Weekly | `gap:security:stale-finding` | CI |
| Trust ledger: action type never promotes | Weekly | `gap:autonomy:stuck-escalation` | CI |

### Gap Record Format (using existing ops_problems table)

```json
{
  "id": "PRB-042",
  "status": "identified",
  "title": "No triage runbook for service_type 'secrets'",
  "pattern": "gap:coverage:no-runbook",
  "correlated_incidents": "INC-015,INC-022",
  "root_cause": "FMEA catalog incomplete — secrets services (op-connect-api, op-connect-sync) have no triage-secrets.yaml",
  "recommended_fix": "NFI: Create triage-secrets.yaml with 1Password-specific failure modes",
  "workaround": "Generic investigation fallback handles it, but with lower confidence"
}
```

### Gap Routing

Pattern prefix determines workstream:

| Pattern Prefix | Workstream | Action |
|---------------|------------|--------|
| `gap:coverage:*` | NFI | New runbook, new sensor, new classification needed |
| `gap:accuracy:*` | CI | Existing runbook/diagnostics needs refinement |
| `gap:autonomy:*` | CI | Trust/guardrail adjustment, remediation expansion |
| `gap:efficiency:*` | CI | Triage pipeline optimization |
| `gap:monitoring:*` | NFI | New health check, new sweep target |
| `gap:security:*` | CI | Threat model remediation |

### Integration Points

**ops-agent triage.py** — after every diagnosis:
```python
if diagnosis.root_cause == RootCause.UNKNOWN:
    await self._create_gap_problem(target, "gap:accuracy:unclassifiable", ...)
if runbook is None and service_type:
    await self._create_gap_problem(target, "gap:coverage:no-runbook", ...)
```

**ops-agent health_monitor.py** — during discovery sync:
```python
if service.get("service_type") is None:
    await self._create_gap_problem(name, "gap:coverage:untyped-service", ...)
```

**Admin API incident resolution** — when incident is resolved:
```python
# Compare resolution to runbook recommendation
# Track resolution time vs baseline
```

**ops-agent proactive_ops.py** — weekly sweep:
```python
# Services not seen in 7 days
# Trust ledger stale escalations
# Threat model findings >30d old
```

### Deduplication

Same dedup as existing problems: check if a problem with the same pattern + target
already exists in `identified` or `investigating` state. If yes, append the new
incident to `correlated_incidents`. If no, create new.

### Visibility

- Gap problems appear in `ops_get_context` (agent session start briefing)
- Gap problems appear in ops-agent's weekly FMEA report
- Gap problems with `gap:security:*` pattern → P2 notification channel
- Gap count by workstream in `GET /ops/metrics`

## Phase 1 Exit Gate

ALL five sub-phases must be complete:
- [x] 1a: Tools + Rules deployed
- [ ] 1b: Compliance rate >90% over 10 sessions
- [ ] 1c: Runbook effectiveness and resolution time measured
- [ ] 1d: False positive rate <20%, baselines for top-10 noise sources
- [ ] 1e: Gap detection automated, producing problem records, routing to CI/NFI

## Phase 2: Fork into Workstreams

Once Phase 1 exits, the system is self-aware — it knows what it knows, what it
doesn't know, and which workstream should address each gap.

**CI Workstream** (continuous, never finishes):
- Consume `gap:accuracy:*` problems → refine runbooks/diagnostics
- Consume `gap:autonomy:*` problems → expand trust/remediation
- Consume `gap:efficiency:*` problems → optimize triage pipeline
- Consume `gap:security:*` problems → remediate threat model findings
- Portability constraint: all improvements are agent-agnostic

**NFI Workstream** (project-based, delivers specific capabilities):
- Consume `gap:coverage:*` problems → new runbooks, new service types
- Consume `gap:monitoring:*` problems → new health checks, new sensors
- Remaining items from brainstorm: app-level health, synthetic transactions,
  cross-service correlation, LLM-assisted diagnosis, metric trend detection
- Portability constraint: all new capabilities use the shared protocol

**Blind spot detection** feeds both workstreams continuously. It's the routing
function. The system improves itself by detecting its own gaps and creating
work items in the right lane.

## Portability Note

Every component in this design is agent-agnostic:
- Gap patterns use a generic taxonomy (not "ops-agent can't do X")
- Problem records use the existing SOP schema
- Workstream routing is pattern-based, not agent-based
- Any agent that speaks the protocol can detect gaps and consume gap records
