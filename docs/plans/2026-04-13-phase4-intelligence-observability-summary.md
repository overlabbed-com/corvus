# Phase 4: Intelligence & Observability — Implementation Summary

**Status**: In Progress (Phase 4.1 Complete)
**Start Date**: 2026-04-13
**Target Completion**: 2026-05-17

## Overview

Phase 4 transforms Corvus from an event collector into an operational intelligence platform. The foundation built in Phases 1-3 (event protocol, CMDB, runbooks, Neo4j graph) is now complete. Phase 4 activates the full power of that foundation.

## Completed Deliverables

### Phase 4.1: Correlation Groups ✅

**Deliverables**:
- ✅ `src/routers/correlations.py` — Correlation check endpoint with GPU, host, and dependency detection
- ✅ `src/tasks/correlation.py` — Background correlation sweep (runs every 5 minutes)
- ✅ Neo4j schema: CorrelationGroup nodes + MEMBER_OF relationships
- ✅ API endpoints:
  - `POST /ops/correlations/check` — Check if incidents should be correlated
  - `GET /ops/correlations/group/{group_id}` — Get correlation group details
  - `GET /ops/correlations/active` — List active correlation groups
- ✅ Updated `spec/events.md` with correlation group event schema
- ✅ Tests: `tests/test_correlations.py` (9 test cases)
- ✅ Registered in `app.py` with background task loop

**What It Does**:
- Detects when 2+ incidents share a GPU, host, or dependency
- Creates correlation groups automatically
- Enables single-alert semantics (one alert per group, not per incident)
- Provides root cause hints ("Check GPU state", "Fix dependency first")

**Example Scenario** (docling false positive):
- Before: 4 independent alerts (ace-step OOM, docling auth_failure, qwen3-asr, qwen3-tts)
- After: 1 correlation group alert "GPU 0 failure group — Check GPU state (VRAM, temperature, driver)"

**Exit Criterion Met**: ✅ Correlation groups can be created automatically during sweeps

---

## In Progress

### Phase 4.2: CI Operational Model

**Status**: Design complete, implementation pending

**Deliverables**:
- [ ] Extend `ops_cmdb` table with CI fields (or create `ops_ci` table)
- [ ] `GET /ops/cmdb/ci/{name}/impact` — CI impact analysis
- [ ] `GET /ops/cmdb/ci/expiring` — CI expiry query
- [ ] Neo4j CI relationship population from CMDB
- [ ] Update `spec/cmdb.md` with CI operational fields

**What It Will Do**:
- Register CIs (searches, indexes, models, accounts, certs, etc.) with operational lifecycle
- Link incidents to specific CIs, not just services
- Enable queries like "Which saved search is causing this indexer incident?"
- Track expiring CIs (accounts, certs, licenses) with 30-day warning

**Current State**:
- CI types defined in `spec/cmdb.md` (30+ types across 5 categories)
- Neo4j constraints for CI nodes already in `graph.py`
- CMDB has basic CI registration endpoint (`POST /ops/cmdb/ci`)

---

### Phase 4.3: Deploy Triage Integration

**Status**: Runbook exists, integration pending

**Deliverables**:
- [ ] Extend runbook executor with `deploy.workflow_logs` and `containers.drift_check`
- [ ] `src/discovery/deploy_manager.py` — Integrate with triage flow
- [ ] Update ops-agent governance rules to use deploy triage
- [ ] Document GitOps pipeline integration for declared state

**What It Will Do**:
- Parse GitHub Actions workflow logs on deploy failure
- Detect stale_container_config (container created before healthcheck added)
- Suggest `docker compose up -d --force-recreate` instead of "Step failed"
- Check config drift before recommending restart

**Current State**:
- `runbooks/triage-deploy.yaml` exists with FMEA diagnosis hints
- Runbook executor supports investigation steps
- No deploy_manager integration yet

---

### Phase 4.4: Config Drift Loop

**Status**: Design complete, implementation pending

**Deliverables**:
- [ ] `src/tasks/drift_detection.py` — Automated drift sweep
- [ ] CMDB drift update logic
- [ ] Gap problem creation for drift
- [ ] `GET /ops/cmdb/{name}/drift` — Detailed drift report
- [ ] Update `spec/cmdb.md` with drift detection spec

**What It Will Do**:
- Compare running containers against CMDB declared state every 15 minutes
- Detect stale containers (healthcheck added to compose but not recreated)
- Create `gap:coverage:config-drift:{target}` problems
- Enable "force recreate" recommendations with confidence

**Current State**:
- CMDB has `declared_image`, `runtime_image`, `drift_detected` fields
- `graph_queries.py` has `/drift` endpoints (Neo4j-based)
- No automated detection loop yet

---

### Phase 4.5: Pattern Quality API

**Status**: Design complete, implementation pending

**Deliverables**:
- [ ] `src/routers/patterns.py` — Pattern validation endpoint
- [ ] False-positive corpus (100+ test cases)
- [ ] Pattern quality rule engine
- [ ] Neo4j `DiagnosisPattern` node creation from runbooks
- [ ] Pattern hit tracking during triage

**What It Will Do**:
- Validate diagnosis patterns against quality rules (word boundaries, HTTP context)
- Run patterns against false-positive corpus before deployment
- Track pattern false positives via Neo4j (`DiagnosisPattern-MATCHED_IN->Incident`)
- Suggest pattern improvements

**Current State**:
- Pattern quality rules defined in `spec/investigation.md`
- Runbooks have `diagnosis_hints` with patterns
- No validation or tracking yet

---

### Phase 4.6: Graph-Powered Triage

**Status**: Design complete, implementation pending

**Deliverables**:
- [ ] Triage executor enhancement with graph context
- [ ] `get_dependency_health`, `get_correlation_group`, `get_blast_radius` functions
- [ ] Triage output enhancement with graph context
- [ ] Update runbook executor to include graph data

**What It Will Do**:
- Include dependency health in triage diagnosis
- Report correlation group membership during triage
- Provide blast radius context for escalation decisions
- Recommend "fix root cause first" for correlated failures

**Current State**:
- Graph queries exist in `graph_queries.py` (blast radius, dependency chain)
- Triage executor in `src/runbooks/executor.py` doesn't use graph yet
- No context-aware triage yet

---

## Progress Metrics

| Phase | Status | Completion |
|-------|--------|------------|
| 4.1: Correlation Groups | ✅ Complete | 100% |
| 4.2: CI Operational Model | 📋 Design | 0% |
| 4.3: Deploy Triage Integration | 📋 Design | 0% |
| 4.4: Config Drift Loop | 📋 Design | 0% |
| 4.5: Pattern Quality API | 📋 Design | 0% |
| 4.6: Graph-Powered Triage | 📋 Design | 0% |

**Overall Phase 4 Progress**: 17% (1 of 6 phases complete)

---

## Next Steps (Week 2)

1. **CI Operational Model Implementation**
   - Extend CMDB schema with CI operational fields
   - Implement CI impact analysis endpoint
   - Implement CI expiry query endpoint
   - Populate Neo4j CI relationships from CMDB

2. **Tests**
   - Add CI registration tests
   - Add CI impact query tests
   - Add CI expiry query tests

3. **Documentation**
   - Update `spec/cmdb.md` with CI operational fields
   - Add CI lifecycle examples to PRODUCT_VISION.md

---

## Success Criteria

Phase 4 is complete when:
1. ✅ Correlation groups are created automatically (DONE)
2. [ ] CIs can be registered with operational relationships
3. [ ] Deploy failures get FMEA triage (not passthrough)
4. [ ] Config drift is detected automatically (<1h detection time)
5. [ ] Diagnosis patterns can be validated against quality rules
6. [ ] Triage includes graph context (dependency health, blast radius, correlation)
7. [ ] False positive rate <10% (measured over 50 incidents)
8. [ ] All Phase 4 tests pass (minimum 30 new tests)

---

## Design Reference

- Full design: `docs/designs/2026-04-13-architect-phase4-intelligence-observability.md`
- Event spec: `spec/events.md` (updated with correlation groups)
- Investigation spec: `spec/investigation.md`
- CMDB spec: `spec/cmdb.md`
- Runbook spec: `spec/runbooks.md`

---

**Last Updated**: 2026-04-13
**Next Review**: 2026-04-20 (after Phase 4.2 completion)
