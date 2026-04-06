# FMEA Catalog & Runbook Engine Design

> Agent: Architect
> Workspace: automation
> Project: operational-runbooks
> Risk Level: APPROVE (modifies ops-agent triage pipeline + adds new playbooks)
> Generated: 2026-03-29

## Summary

Design for FMEA-informed, service-type-aware operational runbooks that replace
ops-agent's generic one-size-fits-all investigation with targeted triage per
service category. 92 CMDB services classified into 12 service types, each with
specific failure modes, investigation steps, remediation actions, and escalation
criteria.

## Problem Statement

The ops-agent's current investigation pipeline is generic:
- Same 50-line log pull for every container
- Same log pattern matching (14 rules in `diagnostics.py`)
- No service-specific knowledge (vLLM OOM vs PostgreSQL connection exhaustion)
- No GPU-aware investigation for inference services
- No data-safety awareness (stateless vs stateful restart risk)
- Investigation quality: "No errors in recent 20 log lines" for an exited container

**Result**: Mean time to restore is extended by generic investigation that doesn't
ask the right questions for the specific service.

## Service Type Classification

92 CMDB services classified into 12 types based on failure characteristics:

### Type 1: `inference` — GPU Inference Engines (7 services)
**Services**: vllm-primary (host-01), vllm-embed (host-01), vllm-rerank (host-01),
vllm-default (host-02), vllm-subagent (host-02), vllm-sonnet (host-03), vllm-ocsf (host-03)

**Characteristics**: GPU-bound, high VRAM usage, long startup (model loading),
TP=2 configs span multiple GPUs, FP8 KV cache, specific parser requirements.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| I-1 | CUDA OOM | `cuda_oom` log pattern, VRAM >99% | High | No — will recur |
| I-2 | Model loading failure | `loading model` timeout, exit code | High | Yes — transient NFS |
| I-3 | Tool call parser crash | `--tool-call-parser` in error, immediate exit | Critical | No — config fix |
| I-4 | NFS model mount missing | `/mnt/models` not found, ENOENT | Critical | No — host fix |
| I-5 | TP=2 GPU visibility | Wrong GPU index, NCCL error | Critical | No — compose fix |
| I-6 | Inference timeout | Requests queueing, latency spike | Medium | Yes — if not OOM |
| I-7 | Health check timeout | `/health` not responding, but process alive | Low | Yes — likely transient |

**Investigation steps (service-specific)**:
1. `nvidia-smi` on host — VRAM per GPU, process list, temperature
2. Check model loading status — is the model fully loaded or still loading?
3. Check container uptime vs expected startup time (vLLM takes 2-5 min to load)
4. For TP=2: verify both GPUs visible, NCCL communication healthy
5. Check NFS mount: `mount | grep /mnt/models` on host
6. Check recent request latency if available

**Remediation guardrails**:
- Never restart while model is still loading (check uptime < 10 min)
- For CUDA OOM: check what other processes are on the GPU first
- For TP=2 failures: ALWAYS escalate (cross-GPU issues need design review)
- Post-restart verification: wait for `/health` to return 200, not just container "running"

---

### Type 2: `database` — Databases (6 services)
**Services**: litellm-postgres (host-01), postgres (host-04), prefect-postgres (host-04),
homeassistant-postgres (host-04), ops-agent-postgres (host-04), blog-mysql (host-04)

**Characteristics**: Stateful, data integrity critical, WAL/binlog, connection pools,
volume-dependent. Restart risk: potential data corruption.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| D-1 | Connection pool exhaustion | `too many connections` | Medium | Sometimes — check consumers |
| D-2 | Disk full (WAL/data) | `No space left on device` | Critical | No — need space first |
| D-3 | Volume corruption | Startup failure after unclean shutdown | Critical | No — need recovery |
| D-4 | Stuck queries / locks | Long-running queries, lock waits | Medium | Risky — may lose transactions |
| D-5 | OOM killed | `oom_killed` pattern | High | Yes — but may corrupt |
| D-6 | Auth failure (pg_hba) | `authentication failed` | Medium | No — config fix |

**Investigation steps (service-specific)**:
1. Check disk usage on data volume
2. Check active connections: `pg_stat_activity` (via docker exec)
3. Check for lock contention: `pg_locks`
4. Check WAL size (PostgreSQL)
5. Check dependent services — who consumes this database?

**Remediation guardrails**:
- ALWAYS escalate before restart (data integrity risk)
- Exception: connection pool exhaustion with no stuck queries → restart OK
- Never delete database volumes without explicit operator approval
- Post-restart: verify data integrity (table count, recent writes)

---

### Type 3: `proxy` — Reverse Proxy / Load Balancer (1 service)
**Services**: caddy (host-04)

**Characteristics**: Critical infrastructure, affects ALL web-accessible services.
Blast radius: external. Config reload vs full restart distinction matters.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| P-1 | Config syntax error | `error adapting config` | Critical | No — fix config |
| P-2 | Upstream unreachable | Specific route 502/504 | Medium | No — fix upstream |
| P-3 | TLS cert failure | `tls handshake` errors | High | Maybe — may need cert renewal |
| P-4 | Port binding failure | `address already in use` | Critical | No — find conflicting process |
| P-5 | Memory leak | Gradual memory growth, eventual OOM | Medium | Yes — but investigate leak |

**Investigation steps**:
1. Check which routes are failing (not all may be down)
2. Check Caddy admin API (`localhost:2019/config/`) for config state
3. Check cert validity for affected domains
4. Check upstream container health for 502 errors
5. Check if this is config reload failure vs full crash

**Remediation guardrails**:
- Caddy restart = ALL web services briefly unavailable → NOTIFY always
- Try `caddy reload` before full restart
- For cert issues: check certbot container
- Post-restart: verify all routes responding

---

### Type 4: `mcp_bridge` — MCP Server Bridges (16 services)
**Services**: admin-api-mcp, arr-stack-mcp, birdnet-mcp, cloudflare-mcp, docker-inspect,
docker-mcp, esphome-mcp, github-mcp, homeassistant-mcp, mqtt-mcp, netdata-mcp,
overseerr-mcp, playwright-mcp, portainer-mcp, powerdns-mcp, prefect-mcp, searxng-mcp,
tautulli-mcp, unifi-mcp, zigbee2mqtt-mcp

**Characteristics**: Stateless, ephemeral, low blast radius. FastAPI/Python services
that proxy API calls. Can restart freely.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| M-1 | Upstream API unreachable | Connection refused to backend | Low | No — fix backend |
| M-2 | Auth token expired | 401/403 from backend | Medium | No — rotate credential |
| M-3 | Python crash | Unhandled exception, exit | Low | Yes — restart is fix |
| M-4 | Memory leak | Gradual growth | Low | Yes — restart is fix |
| M-5 | Type coercion failure | jsonschema validation error | Low | No — code fix needed |

**Investigation steps**:
1. Check if backend service is healthy
2. Check for auth errors in logs (expired tokens)
3. Check for unhandled exceptions
4. Light-weight — 20 log lines is sufficient

**Remediation guardrails**:
- AUTO restart (stateless, low risk)
- If auth_failure pattern: flag for credential rotation, don't just restart
- Group check: if 3+ MCP bridges down simultaneously, likely a shared dependency

---

### Type 5: `secrets` — Secrets Management (2 services)
**Services**: op-connect-api (host-04), op-connect-sync (host-04)

**Characteristics**: Critical infrastructure, affects ALL services that consume secrets.
Restart can cause cascade (services can't fetch secrets during downtime).

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| S-1 | 1Password sync failure | `sync error` in logs | High | Maybe — check 1P cloud |
| S-2 | Credential file corruption | Startup failure | Critical | No — need new credentials file |
| S-3 | API unresponsive | Health check timeout | Medium | Yes — if sync is healthy |

**Investigation steps**:
1. Check if op-connect-sync is healthy (API depends on sync)
2. Check 1Password cloud connectivity
3. Check credential file permissions (UID 999, mode 600)
4. Check if issue affects one host or all hosts

**Remediation guardrails**:
- ALWAYS escalate (credential file issues are unrecoverable without manual intervention)
- If restart: check ALL consuming services afterward
- Credential file corruption = manual fix (SCP from another host)

---

### Type 6: `iot_gateway` — IoT Gateways & Controllers (5 services)
**Services**: zigbee2mqtt_up_mbr (host-04), zigbee2mqtt_dn_kit (host-04),
zigbee2mqtt_gr_gar (host-04), mqtt (host-04), esphome (host-04)

**Characteristics**: Real-time device communication, hardware coordinator dependencies,
paired devices, state synchronization.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| Z-1 | Coordinator disconnected | `Error: Failed to connect` | High | Yes — USB reset |
| Z-2 | MQTT broker down | All Z2M instances disconnected | Critical | Yes — cascade recovery |
| Z-3 | Device flood | High message rate, queue backup | Medium | Risky — may lose state |
| Z-4 | Z2M database corruption | Startup failure after crash | High | No — backup needed |

**Investigation steps**:
1. Check MQTT broker connectivity: `mosquitto_sub -t '$SYS/broker/clients/connected' -C 1 -W 3`
2. For Z2M: check coordinator serial device (`/dev/ttyUSB*` or `/dev/ttyACM*`)
3. Check connected device count vs expected
4. Check if single Z2M instance or all three affected

**Remediation guardrails**:
- MQTT broker restart = all Z2M instances temporarily disconnect → restart Z2M after
- Z2M restart safe if coordinator is connected
- Check HA integration after any Z2M restart (MQTT alias dependency)
- Post-restart: verify `$SYS/broker/clients/connected` returns expected count (4)

---

### Type 7: `home_automation` — Home Automation Platform (1 service)
**Services**: homeassistant (host-04)

**Characteristics**: Critical for household, ipvlan networking, multiple integrations,
HomeKit bridges, complex startup sequence.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| H-1 | Network unreachable (all VLANs) | Bridge NAT disruption | Critical | Maybe — check init script |
| H-2 | MQTT disconnected | `Failed to connect to MQTT server` | Medium | Yes — check alias |
| H-3 | HomeKit "No Response" | mDNS binding issue | Medium | Yes — but check network config |
| H-4 | Integration failure | Specific integration error | Low | Maybe — depends on integration |
| H-5 | Database corruption | Startup failure | Critical | No — backup restore needed |

**Investigation steps**:
1. Check if HA is reachable on 10.0.1.222 (ipvlan IP)
2. Check default route inside container (should be via 10.0.1.1, not Docker bridge)
3. Check MQTT connectivity (mosquitto alias)
4. Check `core.config_entries` for integration errors
5. Check HomeKit bridge `advertise_ip` and `core.network` settings

**Remediation guardrails**:
- Restart usually safe but may trigger HomeKit re-pairing
- For network issues: check init script ran correctly
- For MQTT: check `mqtt` container has `aliases: [mosquitto]`
- ALWAYS notify operator (household impact)

---

### Type 8: `media` — Media Services (8 services)
**Services**: plex (host-04), sonarr (host-04), radarr (host-04), radarr-4k (host-04),
prowlarr (host-04), nzbget (host-04), sabnzbd (host-04), tautulli (host-04), overseerr (host-04)

**Characteristics**: User-facing, external access (Plex), database-backed (SQLite),
download queues, library scanning.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| ME-1 | Plex database locked | `database is locked` | Medium | Yes — but check scans |
| ME-2 | Download client disconnected | Sonarr/Radarr can't reach nzbget/sab | Low | No — fix client |
| ME-3 | Library scan stuck | High CPU, no progress | Low | Yes |
| ME-4 | Indexer failure | Prowlarr can't reach indexers | Low | No — external issue |
| ME-5 | Plex stream buffering | Network/transcode issue | Medium | Maybe — check resources |

**Investigation steps**:
1. Check if downstream services are healthy (Plex depends on nothing; Sonarr depends on Prowlarr + download client)
2. For Plex: check active streams (Tautulli API)
3. Check disk space on media volumes
4. Check download client queue depth

**Remediation guardrails**:
- Plex restart = active streams interrupted → check for active sessions first
- Sonarr/Radarr/Prowlarr: safe to restart (stateless-ish, SQLite recovery is automatic)
- nzbget/sabnzbd: safe to restart (queue persists on disk)

---

### Type 9: `monitoring` — Monitoring & Observability (4 services)
**Services**: netdata (host-04), splunk (host-01), splunk-init (host-01), uptime-kuma (host-02)

**Characteristics**: Observability infrastructure, meta-circular dependency (monitoring
the monitors), volume-dependent (Splunk), complex startup (Splunk init).

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| MO-1 | Splunk provisioning loop | Ansible permission denied | Critical | No — volume wipe |
| MO-2 | Splunk "No users exist" | Corrupted auth state | Critical | No — volume wipe + redeploy |
| MO-3 | Netdata collector failure | Missing metrics | Low | Yes |
| MO-4 | Uptime Kuma probe failure | False positives | Low | Yes |

**Investigation steps**:
1. Splunk: check for permission errors (ansible uid=998), provisioning state
2. Splunk: first boot takes ~6 min (4 min chown + 2 min provision) — don't restart too early
3. Netdata: check which collectors are failing
4. Uptime Kuma: check if it's the monitor or the target

**Remediation guardrails**:
- Splunk: NEVER restart without checking logs first (provisioning loop wastes time)
- Splunk volume wipe: APPROVE+IMPACT
- Netdata/Uptime Kuma: AUTO restart

---

### Type 10: `automation` — Workflow Orchestration (4 services)
**Services**: prefect-server (host-04), prefect-worker (host-04), admin-api (host-04),
ops-agent (host-04)

**Characteristics**: Self-referential (ops-agent monitoring itself), workflow state,
database-dependent.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| A-1 | Prefect server DB connection lost | Worker can't register runs | High | Yes — check postgres |
| A-2 | Worker deployment registration failure | Flows not available | Medium | Yes |
| A-3 | Admin API auth failure | All MCP tools broken | High | No — check ADMIN_API_KEYS |
| A-4 | ops-agent self-failure | Meta: who watches the watchman? | Critical | Autoheal handles |

**Investigation steps**:
1. Check prefect-postgres health first (dependency)
2. Check admin-api health endpoint
3. For ops-agent: autoheal container handles restarts
4. Check if prefect deployments are registered after worker restart

**Remediation guardrails**:
- Prefect server restart = all running flows interrupted → check for active flows first
- Admin API restart = brief MCP tool outage → NOTIFY
- ops-agent: autoheal handles, but if it fails 3x -> escalate

---

### Type 11: `dns` — DNS Infrastructure (external services, not containers)
Monitored via infrastructure-registry but not Docker containers on these hosts.
Dedicated DNS hosts run PowerDNS Auth + Recursor.

**Key failure modes**:
| # | Failure Mode | Detection | Severity | Restart Safe? |
|---|-------------|-----------|----------|---------------|
| DN-1 | Resolver not responding | dig timeout | Critical | Yes |
| DN-2 | Zone transfer failure | Secondary stale | High | No — check primary |
| DN-3 | Record missing/wrong | Specific lookup fails | Medium | No — check zone |

---

### Type 12: `utility` — Miscellaneous Stateless Services (remaining)
**Services**: certbot, cloudflareddns, cloudflared, cloudflared-blog, cloudflared-media,
autoheal, logai, logai-redis, redis, scheduled-jobs, scrypted, birdnet-go, infra-docs,
searxng, playwright-backend, comfyui, ocsf-training, ace-step, docling, qwen3-asr,
qwen3-tts, portainer-agent, restic-backup, tetragon, test-hybrid, agitated_feynman,
udp-relay-weatherflow

**Characteristics**: Mixed bag. Generally low blast radius, restart-safe.
Sub-categories:

- **Tunnels** (cloudflared, cloudflared-blog, cloudflared-media): External connectivity.
  Restart = brief outage for external access. NOTIFY.
- **Cron-like** (certbot, cloudflareddns, restic-backup): Run periodically. Restart safe.
- **AI workloads** (ace-step, docling, qwen3-asr, qwen3-tts, comfyui): GPU-dependent,
  check VRAM before restart. Similar to `inference` but lighter.
- **Autoheal**: The watchman. If autoheal dies, nothing auto-restarts. ALERT immediately.
- **Redis/LogAI**: Caching layer. Restart safe (data loss acceptable for cache).

**Remediation guardrails**:
- Autoheal failure: ALERT (P1) — nothing else auto-restarts without it
- Tunnel restart: NOTIFY (external access briefly down)
- GPU workloads (ace-step, etc.): check VRAM on GPU 0 before restart
- Everything else: AUTO restart

---

## Proposed Solution: Runbook-Driven Triage

### Architecture

```
Health Check Result
    ↓
TriageEngine (existing)
    ↓ (unhealthy container)
CMDB Lookup → service_type
    ↓
RunbookSelector → picks runbook by service_type
    ↓
RunbookExecutor → runs service-specific investigation steps
    ↓
DiagnosticsEngine (enhanced) → root cause + remediation
    ↓
TriageDecision (enriched with runbook context)
```

### Changes Required

**1. CMDB `service_type` field** (new)
Add `service_type` to the CMDB services table. Populated by discovery (Docker labels)
or manual registration. Values: `inference`, `database`, `proxy`, `mcp_bridge`,
`secrets`, `iot_gateway`, `home_automation`, `media`, `monitoring`, `automation`,
`dns`, `utility`.

Sub-types for utility: `tunnel`, `cron`, `gpu_workload`, `cache`, `watchdog`.

**2. Runbook YAML format** (new playbook type: `triage`)

```yaml
name: Inference Service Triage
type: triage                    # NEW: distinguishes from rotation/security playbooks
service_type: inference         # Matches CMDB service_type
version: 1
description: FMEA-informed investigation for GPU inference engines (vLLM)

investigation:
  - name: Check GPU state
    type: gpu.nvidia_smi
    params:
      host: "{{ host }}"
    outputs:
      gpu_state: "{{ result }}"
    timeout: 10

  - name: Check model loading
    type: containers.logs
    params:
      name: "{{ target }}"
      lines: 100
      grep: "model|loading|error|cuda|oom|nccl"
    outputs:
      filtered_logs: "{{ result }}"

  - name: Check NFS mount
    type: host.command
    params:
      host: "{{ host }}"
      command: "mount | grep /mnt/models"
    outputs:
      nfs_status: "{{ result }}"

  - name: Check container uptime
    type: containers.inspect
    params:
      name: "{{ target }}"
      field: "State.StartedAt"
    outputs:
      started_at: "{{ result }}"

diagnosis_hints:
  - pattern: "cuda_oom"
    root_cause: gpu_oom
    restart_safe: false
    explanation: "CUDA OOM — check VRAM allocation and concurrent workloads"
  - pattern: "nccl"
    root_cause: config_error
    restart_safe: false
    explanation: "NCCL error on TP=2 — GPU visibility or cross-GPU communication failure"
  - pattern: "model.*not found"
    root_cause: config_error
    restart_safe: false
    explanation: "Model not found — check NFS mount on host"
  - pattern: "loading model"
    condition: "uptime_seconds < 600"
    root_cause: transient
    restart_safe: false
    explanation: "Model still loading (vLLM takes 2-10 min). Wait before restarting."

remediation:
  restart_safe: conditional           # Depends on diagnosis
  pre_restart_checks:
    - "gpu_state.vram_available > 1024"   # At least 1GB VRAM free
    - "uptime_seconds > 600"               # Not still loading
  post_restart_verification:
    - type: http.check
      params:
        url: "http://{{ target }}:8000/health"
        timeout: 300                        # vLLM takes time to load
        expect_status: 200
  escalation_triggers:
    - "nccl error"
    - "all GPUs full"
    - "NFS mount missing"
```

**3. Triage engine changes** (`triage.py`)
- Before calling generic `Investigator`, look up `service_type` from CMDB
- If a triage runbook exists for that type, execute it instead of generic investigation
- Pass runbook results to enhanced DiagnosticsEngine
- Fall back to generic investigation if no runbook matches

**4. DiagnosticsEngine enhancement** (`diagnostics.py`)
- Accept optional `diagnosis_hints` from runbook
- Runbook hints override generic pattern matching when present
- New root cause: `model_loading` (vLLM-specific), `coordinator_disconnected` (Z2M-specific)
- Preserve existing 14-rule chain as fallback

**5. New investigation steps** (extend `investigator.py` or new `runbook_executor.py`)
- `gpu.nvidia_smi` — run nvidia-smi on host, parse JSON output
- `host.command` — run read-only command on host (via admin-api or SSH)
- `containers.inspect` — get specific container field
- `containers.logs` with `grep` filter — targeted log search
- `http.check` — HTTP health check with timeout and status expectation
- `mqtt.check` — MQTT broker connectivity check

### Phased Implementation

**Phase 1** (this design): FMEA catalog (done above) + CMDB service_type field +
3 priority runbooks: `inference`, `database`, `proxy`

**Phase 2**: Remaining service type runbooks + runbook executor engine

**Phase 3**: Remediation runbooks (not just triage — actual fix steps)

**Phase 4**: Continuous FMEA — feedback loop from incidents to runbook gaps

## Risk Assessment

| Component | Blast Radius | Reversibility | Autonomy |
|-----------|-------------|---------------|----------|
| CMDB service_type field | Contained | Trivial | AUTO |
| Triage runbook YAMLs | None (config) | Trivial | AUTO |
| Triage engine changes | Contained (ops-agent) | Easy (revert PR) | APPROVE |
| DiagnosticsEngine changes | Contained (ops-agent) | Easy (revert PR) | APPROVE |
| New investigation steps | Contained (ops-agent) | Easy (revert PR) | APPROVE |

Overall: **APPROVE** — modifies ops-agent's decision-making pipeline, but fallback
to existing generic investigation preserves current behavior if runbooks have issues.

## Rollback Plan

1. Remove `service_type` lookup from triage.py → falls back to generic investigation
2. Runbook YAMLs are inert if not loaded — simply don't reference them
3. DiagnosticsEngine changes are additive — existing 14 rules remain as fallback
4. CMDB field is additive — no existing queries break

## Dependency Map

- **CMDB** (SOP): needs `service_type` field added to schema
- **Admin API**: needs `/ops/services/{name}` to return `service_type`
- **ops-agent triage.py**: modified to lookup and use runbooks
- **ops-agent investigator.py**: extended with new investigation step types
- **ops-agent diagnostics.py**: enhanced with runbook diagnosis hints
- **Infrastructure registry**: can be simplified once CMDB has service_type

## Lean Review

Applied. Decisions:
- **No new services**: Everything runs within existing ops-agent + Admin API
- **No new databases**: service_type is a column on existing CMDB table
- **YAML over Python**: Runbooks are declarative, not code. Editable without deploys
- **Existing playbook engine**: Extend, don't replace. Same engine runs rotation + triage
- **Fallback to generic**: If runbook lookup fails, existing investigation runs unchanged
- **12 types not 92 runbooks**: Classify by type, not per-service. One runbook per type
- **Deferred**: Remediation runbooks (Phase 3) — triage-only first, prove value

## Responses to Advocate Findings

### F1: Service Type Classification Gaps — ACCEPTED, option (b)
Make the `inference` runbook parameterizable. Add to CMDB `service_metadata` field:
`requires_model_load`, `tp_enabled`, `gpu_index`. GPU workloads (ace-step, asr, tts,
docling) use the same runbook with `requires_model_load: false`, `tp_enabled: false`.
ComfyUI gets `service_type: gpu_workload` (new sub-type). Training workloads
(ocsf-training) get `service_type: utility` — they're batch jobs, not services.

### F2: CMDB Service Type Bootstrap — ACCEPTED
Phase 1 includes a concrete bootstrap:
1. Add `service_type` column to CMDB SQLite schema (Admin API migration)
2. Python classification script with hardcoded mapping (the FMEA catalog IS the map)
3. Admin API bulk update endpoint: `POST /ops/services/bulk-classify`
4. Docker label convention: `ops.service-type=inference` for future auto-discovery
5. Discovery enrichment: if label exists, use it; otherwise, default to `utility`

### F3: Host Command Allowlist — ACCEPTED
`host.command` becomes `host.check` with an allowlist baked into ops-agent code:
```python
ALLOWED_HOST_CHECKS = {
    "nfs_mount": "mount | grep /mnt/models",
    "gpu_state": "nvidia-smi --query-gpu=... --format=csv",
    "disk_usage": "df -h",
    "memory_info": "cat /proc/meminfo | head -5",
    "zfs_status": "zpool status -L",
}
```
Runbook YAML references the check by NAME, not by command string. No arbitrary execution.

### F4: Align with Existing Playbook Engine — ACCEPTED
Triage runbooks will use the existing `steps:` format. New step types added to the
engine: `gpu.nvidia_smi`, `containers.inspect`, `host.check`, `http.health`,
`mqtt.check`. `diagnosis_hints` is a separate YAML section (post-processing, not
step execution). No parallel execution path.

### F5: ops-agent Self-Investigation — ACCEPTED
Runbook execution wrapped in try/except with 30-second timeout. On failure:
```python
try:
    result = await runbook_executor.execute(runbook, context, timeout=30)
except Exception as e:
    logger.warning(f"Runbook execution failed for {target}: {e}")
    result = await generic_investigation(target, host)  # fallback
```
Explicit in code, not just implied.

### F6: Post-Restart Verification Timing — ACCEPTED
Verification timeout is per-service-type in the runbook. For inference services:
- Check logs for "loading model" or "model loaded" patterns
- If "loading model" found and uptime < 600s: extend wait to 600s
- If no model loading pattern: use default timeout (60s)
- Timeout → NOTIFY (not escalate, not restart again)

### F7: Runbook Effectiveness Metrics — PARTIALLY ACCEPTED
Define metrics now, instrument in Phase 2 (not Phase 1 — Phase 1 is catalog + bootstrap).
Metrics: (a) time-to-restore by service type, (b) escalation rate, (c) runbook hit rate
(how often a runbook fires vs generic fallback). Diagnosis accuracy is hard to measure
automatically — defer to Phase 4 feedback loop from problem records.

## Recommendations

1. Start with 3 highest-value runbooks: `inference`, `database`, `proxy`
   - These cover the most complex failure modes and highest blast radius services
2. Bootstrap CMDB service_type via bulk classification script (Phase 1 deliverable)
3. Add service_type to CMDB discovery so new services get classified automatically
4. Instrument runbook hit rate from day one (simple counter in triage.py)
5. Host command allowlist in code, not YAML (F3 security boundary)
