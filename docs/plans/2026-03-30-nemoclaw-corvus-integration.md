# NemoClaw → Corvus Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** NemoClaw consumes Corvus for investigation, diagnosis, correlation, and service metadata. Local hardcoded logic becomes fallback, not primary path. Each integration point is independently feature-flagged.

**Architecture:** NemoClaw adds a `CorvusClient` that wraps all Corvus API calls. Each integration point checks `corvus_available()` before calling. If Corvus is unreachable, NemoClaw falls back to its existing local logic with a warning log. This means NemoClaw never goes blind — Corvus enhances it, but doesn't become a single point of failure.

**Tech Stack:** Python 3.11, httpx (async HTTP), existing NemoClaw codebase at `homelab-gitops/stacks/dockp04-automation/nemoclaw/`

---

## Task 1: Add CorvusClient to NemoClaw

**Files:**
- Create: `nemoclaw/src/corvus_client.py`
- Modify: `nemoclaw/docker-compose.yml` (add CORVUS_URL + CORVUS_API_KEY env vars)

**What to build:**

```python
class CorvusClient:
    """HTTP client for Corvus operational governance API.

    Graceful degradation: all methods return None on connection failure,
    allowing callers to fall back to local logic.
    """

    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._available = False
        self._client = httpx.AsyncClient(timeout=10.0)

    async def health_check(self) -> bool:
        """Check if Corvus is reachable. Called at startup and periodically."""

    async def triage(self, target, host, service_type, investigation_data) -> dict | None:
        """POST /ops/runbooks/triage — get diagnosis from Corvus runbooks."""

    async def check_correlation(self, incidents, host) -> dict | None:
        """POST /ops/correlations/check — detect shared-resource failure groups."""

    async def create_incident(self, target, title, description, severity, detected_by) -> dict | None:
        """POST /ops/incidents — create incident in Corvus."""

    async def emit_event(self, source, type, target, severity, data) -> dict | None:
        """POST /ops/events — emit operational event."""

    async def get_service(self, name) -> dict | None:
        """GET /ops/cmdb/{name} — get service metadata (type, dependencies, baselines)."""

    async def get_blast_radius(self, service) -> dict | None:
        """GET /ops/graph/blast-radius/{service} — what breaks if this goes down."""

    async def get_correlated_gpu_services(self, host, gpu_index) -> dict | None:
        """GET /ops/graph/correlated/{host}/{gpu_index} — services sharing a GPU."""

    async def submit_triage_evidence(self, target, host, exit_code, error_lines,
                                      health_lines, resource_state, dependency_health) -> dict | None:
        """POST /ops/runbooks/triage with investigation standards-compliant evidence."""
```

All methods catch `httpx.ConnectError`, `httpx.TimeoutException`, log a warning, and return `None`.

**Env vars:**
- `CORVUS_URL` — e.g., `http://corvus:9420` (empty = disabled)
- `CORVUS_API_KEY` — Bearer token for Corvus API

**Commit:** `feat(nemoclaw): add CorvusClient with graceful degradation`

---

## Task 2: Integration Point 1 — Triage (Investigation + Diagnosis)

**Files:**
- Modify: `nemoclaw/src/investigator.py`
- Modify: `nemoclaw/src/triage.py`

**What changes:**

In `investigator.py`:
- After gathering evidence (logs, resources, GPU, dependencies), separate log lines into `error_lines` and `health_lines` per Corvus investigation standard
- Add `exit_code` to `InvestigationReport` (get from `docker inspect`)
- Increase log collection from 50 to 200 lines
- Keep existing pattern matching as fallback

In `triage.py`:
- After investigation, if `corvus_client.available`:
  - Call `corvus_client.submit_triage_evidence()` with the standards-compliant evidence
  - Use Corvus's diagnosis (root cause, confidence, restart_appropriate) instead of local `DiagnosticsEngine`
- If Corvus unavailable or returns error:
  - Fall back to existing `DiagnosticsEngine.diagnose()` with local patterns
  - Log warning: "Corvus unavailable, using local diagnosis"

**The key change:** NemoClaw still gathers evidence (it has Docker access). Corvus analyzes it. If Corvus is down, NemoClaw uses its own patterns (which still exist, just not primary).

**Commit:** `feat(nemoclaw): triage via Corvus with local fallback`

---

## Task 3: Integration Point 2 — Correlation Groups

**Files:**
- Modify: `nemoclaw/src/health_monitor.py`
- Modify: `nemoclaw/src/notifications.py`

**What changes:**

In `health_monitor.py`, after a sweep cycle that produces multiple triage decisions:
- Collect all ESCALATE/ALERT decisions from this sweep
- If 2+ decisions exist AND `corvus_client.available`:
  - Call `corvus_client.check_correlation(incidents, host)`
  - If Corvus returns a correlation group:
    - Send ONE grouped Slack alert instead of N individual alerts
    - Include shared resource and root cause hint from Corvus
    - Still create individual incidents (for tracking)
- If Corvus unavailable:
  - Fall back to existing per-incident alerting

In `notifications.py`:
- Add `notify_correlated_group()` method that sends a single Slack alert for a group:
  ```
  ESCALATE — GPU 0 failure group (dockp03)

  4 services affected:
  • ace-step (exit 137 — CUDA OOM)
  • docling (exit 0 — clean shutdown)
  • qwen3-asr (exit 0 — clean shutdown)
  • qwen3-tts (exit 0 — clean shutdown)

  Root cause: CUDA OOM on GPU 0 (A5000 24GB)
  Shared resource: gpu:tmtdockp03:0
  ```

**Commit:** `feat(nemoclaw): correlation groups via Corvus, single alert per group`

---

## Task 4: Integration Point 3 — SOP Operations (Incidents/Events/Changes)

**Files:**
- Modify: `nemoclaw/src/mcp_client.py` (InfraClient)

**What changes:**

Add a `corvus_mode` flag to InfraClient. When enabled:
- `create_incident()` → calls Corvus `POST /ops/incidents` instead of admin-api
- `emit_event()` → calls Corvus `POST /ops/events` instead of admin-api
- `create_change()` → calls Corvus `POST /ops/changes` instead of admin-api
- `check_target()` → calls Corvus `GET /ops/events/targets/{target}/status` instead of admin-api

Fallback: if Corvus call fails, retry against admin-api (existing path).

**This is the lowest-risk migration** — same API shapes, different base URL. Corvus's SOP endpoints match admin-api because they share the same origin.

**Commit:** `feat(nemoclaw): SOP operations via Corvus with admin-api fallback`

---

## Task 5: Integration Point 4 — CMDB + Service Classification

**Files:**
- Modify: `nemoclaw/src/service_classification.py`
- Modify: `nemoclaw/src/triage.py` (where service_type is resolved)

**What changes:**

In `service_classification.py`:
- Add `corvus_classify(container_name)` that calls `GET corvus/ops/cmdb/{name}`
- Returns service_type, dependencies, baseline_behavior, alert_policy from Corvus graph
- Fallback: existing heuristic classification from container name patterns

In `triage.py`:
- When resolving service_type for runbook selection, try Corvus first:
  ```python
  svc = await corvus_client.get_service(target)
  if svc and svc.get("service_type"):
      service_type = svc["service_type"]
  else:
      service_type = classify_by_name(target)  # existing fallback
  ```

**Bonus:** Corvus's graph provides dependency data that NemoClaw's flat registry can't. When checking if a restart is safe, NemoClaw can ask Corvus for the blast radius first.

**Commit:** `feat(nemoclaw): service classification from Corvus CMDB with local fallback`

---

## Task 6: Integration Point 5 — Deploy Failure Investigation

**Files:**
- Modify: `nemoclaw/src/deploy_manager.py`

**What changes:**

In `_handle_deploy_failure()`:
- After getting failed step names from GitHub API (existing logic), if `corvus_client.available`:
  - Call `corvus_client.triage(target=workflow_name, service_type="deploy", investigation_data={"workflow_logs": step_details, "run_id": run_id})`
  - Use Corvus's deploy runbook diagnosis instead of the passthrough alert
  - Include actionable fix in the Slack message (e.g., "Fix: docker compose up -d --force-recreate certbot")
- If Corvus unavailable:
  - Fall back to existing passthrough (step names + GitHub link)

**Commit:** `feat(nemoclaw): deploy failure triage via Corvus runbook`

---

## Task 7: Wire CorvusClient into NemoClaw startup

**Files:**
- Modify: `nemoclaw/src/main.py` (or wherever the app initializes)
- Modify: `nemoclaw/docker-compose.yml` (env vars)
- Modify: `nemoclaw/src/health_monitor.py` (pass client to components)

**What changes:**

At startup:
```python
corvus_url = os.getenv("CORVUS_URL", "")
corvus_key = os.getenv("CORVUS_API_KEY", "")
corvus = CorvusClient(corvus_url, corvus_key) if corvus_url else None
if corvus:
    healthy = await corvus.health_check()
    logger.info("Corvus integration: %s", "active" if healthy else "unreachable (falling back to local)")
```

Pass `corvus` to HealthMonitor, TriageEngine, Investigator, DeployManager.

**Docker Compose env:**
```yaml
environment:
  - CORVUS_URL=http://corvus:9420
  - CORVUS_API_KEY=${CORVUS_API_KEY}
```

Both containers are on the `infra-services` network, so `corvus:9420` resolves via Docker DNS.

**Commit:** `feat(nemoclaw): wire CorvusClient into startup, pass to all components`

---

## Task 8: Add NemoClaw key to Corvus secrets

**What:**
- Update 1Password secret at `services/corvus` to add a dedicated NemoClaw key
- NemoClaw's env gets `CORVUS_API_KEY` from 1Password Connect at deploy time
- Update GitHub Actions workflow for dockp04-automation to inject the key

**Commit:** (secrets + workflow only, no code change)

---

## Execution Order

```
Task 1 (CorvusClient)     → foundation, no behavior change
Task 7 (wiring)           → connects client to components, still no behavior change
Task 8 (secrets)          → auth ready
Task 2 (triage)           → BIGGEST WIN: fixes GAPs 1,2,5,6
Task 3 (correlation)      → fixes GAP 3
Task 4 (SOP operations)   → lowest risk, same API shape
Task 5 (CMDB)             → replaces hardcoded classification
Task 6 (deploy)           → fixes GAP 4
```

Each task is independently deployable. After each, NemoClaw still works even if you revert — fallback to local logic is the safety net.

## Verification After Each Task

After deploying each integration point:
1. Intentionally stop Corvus: `docker stop corvus`
2. Trigger a health sweep: verify NemoClaw falls back to local logic
3. Restart Corvus: `docker start corvus`
4. Trigger another sweep: verify NemoClaw uses Corvus
5. Check Slack alerts: correct format, correct diagnosis
