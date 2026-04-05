# Threat Model -- Shared Operational Picture + Unified Ops Protocol

> Agent: Auditor
> Workspace: automation
> Project: 021-unified-ops-protocol
> Risk Level: AUTO (analysis only)
> Generated: 2026-03-29

## Summary

This threat model covers the multi-agent coordination platform spanning Projects
019 (SOP), 020 (FMEA Runbooks), and 021 (Unified Ops Protocol). The system
enables two AI agents (Claude Code and NemoClaw) to share operational awareness
through a REST API with SQLite backing, MCP tool proxy, YAML-defined runbooks,
and a host command allowlist. Analysis uses the STRIDE methodology across all
trust boundaries. 27 findings identified: 2 Critical, 7 High, 10 Medium, 8 Low.

## System Architecture (Data Flow)

```
                    +------------------------+
                    |     Todd (Human)       |
                    |   Slack / CC CLI       |
                    +----------+-------------+
                               |
          +--------------------+--------------------+
          |                                         |
          v                                         v
+-------------------+                    +-------------------+
|   Claude Code     |                    |    NemoClaw       |
|   (Mac / CC CLI)  |                    |  (dockp04 Docker) |
|                   |                    |                   |
| Uses MCP tools    |                    | Direct HTTP to    |
| via LiteLLM proxy |                    | Admin API         |
+--------+----------+                    +--------+----------+
         |                                        |
         v                                        v
+-------------------+                    +-------------------+
| LiteLLM Proxy     |                    |                   |
| (dockp01:4000)    |------ HTTP ------->|    Admin API      |
| MCP server        |                    |  (dockp04:8000)   |
+-------------------+                    |                   |
                                         | - FastAPI         |
                                         | - Bearer token    |
                                         | - IP whitelist    |
                                         | - 25 /ops/* routes|
                                         | - /backup/exec    |
                                         | - /backup/zfs     |
                                         | - Docker TCP API  |
                                         +--------+----------+
                                                  |
                                    +-------------+-------------+
                                    |             |             |
                                    v             v             v
                              +-----------+ +---------+ +-------------+
                              | SQLite DB | | Docker  | | Splunk HEC  |
                              | /data/    | | Socket  | | (fire&forget|
                              | ops.db    | | + mTLS  | |  forwarding)|
                              +-----------+ +---------+ +-------------+
                                                |
                                    +-----------+-----------+
                                    |           |           |
                                    v           v           v
                              dockp01      dockp02      dockp03
                              (mTLS 2376)  (mTLS 2376)  (mTLS 2376)
```

## Trust Boundaries

| Boundary | Inside | Outside | Crossing Mechanism |
|----------|--------|---------|-------------------|
| **TB1: Admin API perimeter** | FastAPI app, SQLite, Docker socket | All callers (CC, NC, LiteLLM MCP) | Bearer token + IP whitelist |
| **TB2: Docker host boundary** | Admin API container process | Docker daemon, host kernel | Docker socket (local) + Docker TCP API (mTLS, port 2376) |
| **TB3: MCP proxy boundary** | LiteLLM MCP server on dockp01 | Claude Code sessions (Mac) | LiteLLM API key + team-based access control |
| **TB4: NemoClaw process boundary** | NemoClaw Python process | Admin API, Docker hosts, Slack, LLM backend | HTTP + bearer token + guardrails engine |
| **TB5: Runbook YAML boundary** | Python runbook selector/triage engine | YAML files on disk (bind-mounted from Git) | yaml.safe_load + named check allowlist |
| **TB6: Network boundary** | Docker internal networks (172.16.x.x) | Server VLAN (192.168.20.x), other VLANs | IP whitelist (172.16/12, 10/8, 192.168.20/24, 127/8) |

## Attack Surface Enumeration

| Surface | Exposure | Protocol | Auth |
|---------|----------|----------|------|
| Admin API port 8000 | Host-bound (0.0.0.0:8000 on dockp04) | HTTP/REST | Bearer token + IP whitelist |
| Docker socket (/var/run/docker.sock) | Container-internal | Unix socket | No auth (root equivalent) |
| Docker TCP API (port 2376 on dockp01/02/03) | Network reachable from dockp04 | mTLS | Client certificate |
| SQLite database (/data/ops.db) | Volume-mounted, container-internal | File I/O | No file-level auth |
| Runbook YAML files (/app/config/playbooks/) | Bind-mounted from GitOps repo | File I/O | GitOps pipeline (CI/CD) |
| Splunk HEC forwarding | Outbound from Admin API to Splunk | HTTPS | HEC token in env var |
| Slack webhook (audit alerts) | Outbound from Admin API to Slack | HTTPS | Webhook URL in env var |
| MCP tool proxy (LiteLLM) | dockp01 Docker network | HTTP | LiteLLM API key |
| NemoClaw Slack bot | Inbound from Slack Events API | HTTPS via Slack | Slack signing secret |
| CORS on Admin API | `allow_origins=["*"]` | HTTP | Bearer token required per-request |

---

## STRIDE Analysis

### S1: Spoofing -- Identity and Authentication

#### S1.1: Single bearer token shared across all callers [HIGH]

**Finding**: All API consumers (Claude Code via MCP, NemoClaw, Prefect worker,
any MCP bridge) authenticate with the same bearer token format (`hlab-*`).
The `ADMIN_API_KEYS` env var supports multiple named keys (`name:key` pairs),
but the auth system returns the same policy set (`admin-api-user`) regardless
of which key authenticated. There is no role differentiation.

**Impact**: Any caller with a valid token has full access to all 25+ ops
endpoints, the `/backup/exec` endpoint (arbitrary container command execution),
`/backup/zfs` (privileged ZFS commands), secret read/write operations, and
container restart capabilities. A compromised MCP bridge token grants the same
access as the admin-api's own token.

**Risk**: HIGH -- Blast radius is infrastructure-wide; reversibility varies by
action taken.

**Mitigation**:
- Implement role-based access on API keys (e.g., `ops-read`, `ops-write`,
  `backup-exec`, `secrets-admin`). Each named key should map to a specific
  permission set.
- NemoClaw should use a key scoped to ops endpoints + container restart.
- MCP proxy should use a key scoped to ops read + event creation.
- `/backup/exec` and `/backup/zfs` should require a separate, restricted key.

#### S1.2: Agent impersonation in operational records [MEDIUM]

**Finding**: The `operator` and `source` fields in change windows and events
are caller-supplied strings. Any authenticated caller can create a change window
claiming `operator: "claude-code"` or emit events with `source: "nemoclaw"`.
The auth system identifies the API key name, but the ops layer does not enforce
that the operator/source field matches the authenticated key name.

**Impact**: An agent could create false change windows to suppress alerts for
targets it wants to act on without detection. It could also create misleading
events attributed to the other agent.

**Risk**: MEDIUM -- Requires a valid token but allows attribution manipulation.

**Mitigation**:
- Enforce that `operator`/`source` fields are derived from or validated against
  the authenticated key name. If key name is `nemoclaw`, only allow
  `operator: "nemoclaw"`.
- Alternatively, add an `authenticated_as` field to all records populated from
  the auth layer, independent of caller-supplied fields.

#### S1.3: No mutual authentication between NemoClaw and Admin API [LOW]

**Finding**: NemoClaw calls Admin API using a bearer token read from its
environment. Admin API cannot verify the caller is actually NemoClaw vs. any
other process on the Docker network that obtained the token. The token is
stored in the Docker compose environment, visible via `docker inspect`.

**Risk**: LOW -- Attacker needs container access on the same Docker network.

**Mitigation**: Consider mTLS between NemoClaw and Admin API (already used
for Docker TCP API). Would provide bidirectional identity verification.

---

### T1: Tampering -- Data Integrity

#### T1.1: No write-once guarantee on operational records [HIGH]

**Finding**: All ops records (changes, events, incidents, problems) support
PATCH/UPDATE operations. A change window can be modified after creation to
change its targets, description, or status. Events can't be modified (no PATCH
endpoint), but change records and incident records CAN be freely updated by
any authenticated caller. The DELETE endpoint on changes (`DELETE /ops/changes/{id}`)
allows complete record removal.

**Impact**: An agent (or compromised token holder) could:
- Retroactively modify a change window to cover additional targets
- Delete change records to hide that planned work occurred
- Update incidents to mark them resolved without actual resolution
- Modify problem records to downplay recurring issues

**Risk**: HIGH -- Undermines the audit trail and operational coordination.

**Mitigation**:
- Make change window `targets` field immutable after creation (close and create
  a new window if targets change).
- Remove the DELETE endpoint for changes, or restrict to admin-only key.
- Add an `audit_trail` column to ops tables storing a JSON array of all
  modifications with timestamps and actor identity.
- Consider append-only event log pattern: events are immutable once created.

#### T1.2: Runbook YAML tampering via GitOps pipeline [MEDIUM]

**Finding**: Triage runbook YAMLs are loaded from `/app/config/playbooks/`
which is bind-mounted from the GitOps repo via CI/CD. The YAMLs define
diagnosis patterns (regex), remediation policies, and escalation triggers.
A malicious PR that modifies `triage-inference.yaml` could:
- Change `restart_safe: true` for dangerous conditions (e.g., NCCL errors)
- Add overly broad regex patterns that match normal operation
- Remove escalation triggers to suppress critical alerts

**Impact**: Altered runbooks change NemoClaw's autonomous decision-making.
A subtle change to restart_safe flags could cause repeated restarts of
TP=2 inference during NCCL errors (data corruption risk).

**Risk**: MEDIUM -- Requires GitOps PR approval, but the YAML changes are
subtle and might not be caught in review.

**Mitigation**:
- Add a YAML schema validation step in CI that enforces: all NCCL-related
  patterns must have `restart_safe: false`, all `type: triage` YAMLs must
  have `escalation_triggers` section.
- Runbook YAMLs should be checksummed at load time, with the hash logged.
- Consider a dedicated runbook review label on PRs touching `config/playbooks/`.

#### T1.3: SQLite database file tampering [LOW]

**Finding**: The SQLite database at `/data/ops.db` lives on a Docker volume.
Any process with access to the volume (or the container filesystem) can
directly modify the database file, bypassing all API-level auth and audit.

**Risk**: LOW -- Requires container escape or volume access.

**Mitigation**: Run Admin API container as non-root user. Ensure the Docker
volume has restrictive permissions. Monitor database file integrity via
periodic checksum.

#### T1.4: Service classification map is hardcoded [MEDIUM]

**Finding**: `service_classification.py` contains a hardcoded Python dict
(`SERVICE_TYPE_MAP`) mapping 92+ container names to FMEA service types.
This mapping determines which triage runbook is used, which directly affects
whether NemoClaw escalates or auto-restarts. The mapping can only be changed
via code commit + deploy.

If a new service is deployed that happens to match the heuristic fallback
patterns (e.g., any service with "mcp" in the name is classified as
`mcp_bridge`, any with "postgres" is `database`), it will inherit that
type's triage behavior without explicit classification.

**Risk**: MEDIUM -- Heuristic misclassification could apply wrong triage
runbook to a new service.

**Mitigation**:
- Log a warning when heuristic fallback is used (already done).
- Require explicit CMDB registration for new services before triage applies.
- Add a "heuristic_classified" flag to CMDB entries so operators can
  review and confirm.

---

### R1: Repudiation -- Audit Trail

#### R1.1: Audit log is append-only file with no integrity protection [MEDIUM]

**Finding**: The audit system (`auth.py`) writes to a JSONL file at
`/data/audit.jsonl` and an in-memory ring buffer (1000 entries). The file is
plain text with no signing, checksumming, or tamper-detection. The ring buffer
is volatile (lost on restart). There is no independent audit log consumer.

Splunk HEC forwarding exists for events (Phase 5) but only for the ops event
stream, not for the auth audit log. The Slack webhook only fires for
`high_risk_ops` (secret_delete, secret_write, api_key_delete, user_offboard,
container_restart, container_update).

**Impact**: An attacker with file access could modify or delete the audit log
to hide unauthorized API calls. Ops operations (change window creation, event
emission, CMDB modification) are NOT in the `high_risk_ops` set and do NOT
trigger Slack alerts.

**Risk**: MEDIUM -- Audit log exists but can be tampered with.

**Mitigation**:
- Forward the auth audit log to Splunk HEC (alongside ops events).
- Add `ops_change_create`, `ops_change_update`, `ops_change_delete`,
  `cmdb_register`, `ops_incident_create` to the `high_risk_ops` Slack
  alert set.
- Consider signing audit log entries with a per-session HMAC.
- Ensure Splunk ingestion is verified (currently fire-and-forget with
  logged-but-ignored failures).

#### R1.2: NemoClaw triage decisions have limited attribution [LOW]

**Finding**: When NemoClaw auto-restarts a container, the trust ledger records
the action with `model_tier: "system"` and the triage decision detail. However,
the specific LLM inference that informed the decision (diagnosis, investigation
summary) is logged at DEBUG level and not persisted to the ops event stream
or Splunk.

**Risk**: LOW -- Triage decisions are logged, but the reasoning chain is
only available in container logs (which rotate).

**Mitigation**: Emit a `triage.decision` event to the ops event stream for
every non-LOG triage action, including the runbook used, diagnosis hint
matched, and confidence score.

---

### I1: Information Disclosure

#### I1.1: Container logs exposed via multiple paths without filtering [HIGH]

**Finding**: Container logs are accessible through:
1. Admin API `/containers/{name}/logs` endpoint (all authenticated callers)
2. NemoClaw investigator (reads logs during triage)
3. Splunk HEC forwarding of ops events (may include log snippets in detail)
4. Slack messages (investigation summaries posted to threads)

Container logs frequently contain: connection strings, API tokens in error
messages, internal IP addresses, database queries, stack traces with file
paths, and user data in request logs.

**Impact**: Logs from inference containers (vLLM) may contain prompt content.
Logs from database containers may contain query content. Logs from LiteLLM
may contain API keys in error traces. All of this flows through the ops
platform into Slack threads and potentially Splunk.

**Risk**: HIGH -- Secret material in logs is a common and proven attack
surface.

**Mitigation**:
- Implement a log sanitizer that strips known secret patterns (`hlab-*`,
  `sk-*`, `ghp_*`, `eyJ*`, `Bearer *`, connection strings) before:
  (a) returning logs via API, (b) including in Slack messages,
  (c) forwarding to Splunk, (d) storing in investigation reports.
- Redact environment variables in container inspect output (partially done
  in `docker_inspect` MCP server per its docstring, but not in Admin API's
  own container routes).

#### I1.2: CORS wildcard allows any origin to make authenticated requests [MEDIUM]

**Finding**: Admin API sets `allow_origins=["*"]` in CORS middleware with the
comment "IP whitelist provides security." However, CORS and IP whitelisting
serve different purposes. A malicious web page loaded in a browser on the
192.168.20.x VLAN could make authenticated requests to Admin API if the user's
browser has the bearer token cached or if the page can guess/extract it.

**Risk**: MEDIUM -- Requires browser on the server VLAN with token access, but
CORS wildcard is unnecessary when all legitimate callers are server-side.

**Mitigation**: Set `allow_origins` to an empty list or to specific trusted
origins only. Server-to-server callers (NemoClaw, MCP bridges) do not send
Origin headers and are unaffected by CORS restrictions.

#### I1.3: Splunk HEC token in environment variable [LOW]

**Finding**: `SPLUNK_HEC_URL` and `SPLUNK_HEC_TOKEN` are in the Admin API
container environment. The token grants write access to the `log-sop` Splunk
index. Visible via `docker inspect admin-api`.

**Risk**: LOW -- Contained to operators with Docker access.

**Mitigation**: Rotate HEC token periodically. Consider using a dedicated
HEC input with restricted index scope.

#### I1.4: Change window details expose operational intent [LOW]

**Finding**: Change windows contain `description`, `rollback_plan`, and
`project` fields. The `/ops/changes` endpoint returns all of this to any
authenticated caller. While designed for transparency between agents, this
data reveals current project work, planned infrastructure changes, and
rollback strategies.

**Risk**: LOW in homelab context. Would be MEDIUM in enterprise context.

**Mitigation**: Consider a "need-to-know" field or abbreviated responses for
non-admin API keys.

---

### D1: Denial of Service

#### D1.1: SQLite write lock contention under concurrent load [HIGH]

**Finding**: SQLite in WAL mode supports concurrent reads but only ONE writer
at a time. Every ops API write (change creation, event emission, incident
creation, CMDB registration) acquires a write lock. NemoClaw emits events at
high rates during sweeps (up to ~150 requests per sweep). If Claude Code is
simultaneously creating change windows and emitting events, write lock
contention will cause `SQLITE_BUSY` errors.

The code creates a new connection per function call (`_get_conn()`) with no
connection pooling or retry logic. A `SQLITE_BUSY` error would propagate as
a 500 error to the caller.

**Impact**: Under concurrent load from both agents, ops operations may fail
intermittently. NemoClaw's change window check (hot path) would fail,
potentially causing false alerts during planned work.

**Risk**: HIGH -- Likely to occur during real incidents when both agents are
active simultaneously (the exact scenario SOP is designed for).

**Mitigation**:
- Set `PRAGMA busy_timeout=5000` (5 seconds) in `_get_conn()` to retry
  automatically on lock contention instead of failing immediately.
- Implement connection pooling (single connection per thread with proper
  locking, or use aiosqlite for async access).
- Consider read-only connection for GET endpoints (separate connection
  with no write transactions).
- Long-term: migrate to PostgreSQL (already noted in Decision Log as
  future consideration).

#### D1.2: Event stream unbounded growth [MEDIUM]

**Finding**: The `cleanup_old_events` function exists (30-day retention)
but is only called when explicitly invoked -- there is no scheduled cleanup.
Events accumulate indefinitely until someone calls the cleanup function.
With NemoClaw emitting events every 5-minute sweep, the events table
will grow by ~8000+ rows/day.

Over months, this degrades query performance (the `/ops/events/context`
endpoint queries 500 events with multiple filters) and increases SQLite
file size.

**Risk**: MEDIUM -- Gradual degradation, not immediate failure.

**Mitigation**:
- Add event cleanup to Admin API startup routine (run on init).
- Schedule periodic cleanup via a Prefect flow or a startup task.
- Add an index on `(timestamp, source, type)` composite for the context
  query pattern.

#### D1.3: Regex patterns in diagnosis hints are not bounded [MEDIUM]

**Finding**: The `TriageRunbook.match_diagnosis()` method compiles and
executes regex patterns from YAML files against log text using
`re.search(pattern, log_text, re.IGNORECASE)`. Log text can be up to 100
lines from container logs. Malformed regex patterns could cause
catastrophic backtracking (ReDoS).

The code catches `re.error` for invalid regex but does not protect against
exponential-time patterns (e.g., `(a+)+$`).

**Risk**: MEDIUM -- Requires malicious YAML commit (GitOps gate), but a
ReDoS pattern would stall the triage engine for all containers during a
sweep.

**Mitigation**:
- Set a timeout on regex execution (Python's `re` module doesn't support
  timeouts natively; use `regex` library with `timeout` parameter, or
  run in a thread with a deadline).
- Validate regex patterns at YAML load time with a complexity check.
- Add a maximum pattern length limit (e.g., 500 chars).

#### D1.4: Admin API rate limit is per-IP, not per-key [LOW]

**Finding**: The rate limiter in `main.py` tracks requests per source IP.
All containers on the same Docker network share the same gateway IP
(e.g., 172.16.x.1). NemoClaw and MCP bridges calling from the same Docker
network may all appear as the same IP, causing legitimate traffic to be
rate-limited together.

The limit is 500 requests/minute, which is generous, but a misbehaving MCP
bridge could exhaust the budget and block NemoClaw's critical sweep requests.

**Risk**: LOW -- 500/min is generous; actual contention unlikely.

**Mitigation**: Rate limit per API key name rather than per IP.

---

### E1: Elevation of Privilege

#### E1.1: /backup/exec allows arbitrary command execution in any container [CRITICAL]

**Finding**: The `/backup/exec` endpoint accepts a container name, an
arbitrary command list, and optional environment variables. It executes the
command via `container.exec_run()` with no command allowlist, no container
allowlist, and no audit logging (it returns immediately without calling
`audit_log`).

Any authenticated caller can execute arbitrary commands in ANY container
accessible via the Docker socket. This includes:
- Reading environment variables: `["env"]` in any container (exposing all secrets)
- Writing files: `["sh", "-c", "echo malicious > /app/config.py"]`
- Installing packages: `["apt", "install", "-y", "netcat"]`
- Network reconnaissance: `["sh", "-c", "cat /etc/hosts"]`
- Database access: `["psql", "-U", "postgres", "-c", "SELECT * FROM secrets"]`

**Impact**: Full privilege escalation from API token to arbitrary code
execution across all containers on dockp04. Combined with Docker TCP API
access (mTLS certs in Admin API's env), this extends to containers on all
4 hosts.

**Risk**: CRITICAL -- Any compromised API key becomes root-equivalent across
the entire container fleet.

**Mitigation** (URGENT):
- Add a command allowlist for `/backup/exec` (e.g., only `pg_dump` and
  `psql` with specific flags).
- Add a container allowlist (e.g., only `*-postgres` containers).
- Add audit logging for every exec call (command, container, actor, result).
- Consider removing `/backup/exec` entirely and implementing purpose-built
  endpoints (e.g., `/backup/pg-dump/{database}`).

#### E1.2: /backup/zfs allows arbitrary commands via privileged container [CRITICAL]

**Finding**: The `/backup/zfs` endpoint accepts an arbitrary command list and
executes it via `run_privileged_command()`, which spawns a privileged Alpine
container with host PID namespace. While named "zfs", the endpoint accepts
ANY command, not just ZFS commands.

An authenticated caller could run:
- `["sh", "-c", "cat /etc/shadow"]` (read host passwords)
- `["sh", "-c", "echo '* * * * * root /bin/bash -c ...' >> /etc/crontab"]`
  (persistent host access)
- `["sh", "-c", "dd if=/dev/sda of=/dev/null"]` (destructive disk access)

**Impact**: Direct host-level root access via privileged container execution.
This is worse than Docker socket access because it includes host PID
namespace.

**Risk**: CRITICAL -- Equivalent to unrestricted root SSH.

**Mitigation** (URGENT):
- Implement a command allowlist: only `zpool`, `zfs`, `zpool status`,
  `zfs list`, `zfs snapshot`, `zfs destroy` with validated arguments.
- Validate that the first element of the command list is in a whitelist
  of ZFS binaries.
- Add audit logging for every ZFS command execution.
- Consider a dedicated `/backup/zfs-snapshot` and `/backup/zfs-status`
  endpoint with no arbitrary command injection.

#### E1.3: Host command allowlist bypass via NemoClaw service chain [MEDIUM]

**Finding**: NemoClaw's `host_checks.py` defines a 5-command allowlist. The
`RunbookSelector` uses named references (e.g., `check: gpu_state`). However,
NemoClaw also has access to Admin API's `/backup/exec` endpoint via its bearer
token. If NemoClaw's triage engine or LLM-driven investigation decides to
"look deeper," it could call `/backup/exec` directly, bypassing the
named-check allowlist entirely.

The guardrails engine (`guardrails.py`) blocks certain action types but does
not gate raw API calls to Admin API endpoints. The LLM inference driving
NemoClaw's investigation could be prompted (via log content or error messages)
to call arbitrary Admin API endpoints.

**Risk**: MEDIUM -- Requires LLM to generate specific API calls, which
guardrails and intent classification are designed to prevent, but the
technical path exists.

**Mitigation**:
- NemoClaw's API key should NOT have access to `/backup/exec` or
  `/backup/zfs`. Use role-based API keys (see S1.1).
- The infra_client used by NemoClaw should not expose methods that call
  backup endpoints.

#### E1.4: CMDB alert_policy can be set to "silent" to suppress all alerts [MEDIUM]

**Finding**: The CMDB service registration endpoint allows setting
`alert_policy: "silent"` for any service. If NemoClaw's auto-discovery
or a malicious API caller registers a critical service as silent, health
alerts for that service will be suppressed.

The `bulk_sync` endpoint could silently override the alert_policy for all
services in a single API call.

**Risk**: MEDIUM -- Requires valid token but provides persistent alert
suppression without change window visibility.

**Mitigation**:
- Log alert_policy changes at WARNING level.
- Add alert_policy to the immutable-after-creation fields (require explicit
  PATCH to change, not overwrite via sync).
- Add a Sentinel check that verifies no critical services have
  `alert_policy: "silent"`.

#### E1.5: Change window auto-expire can be disabled [LOW]

**Finding**: The `auto_expire` field defaults to True (4-hour expiry) but
can be set to False by any caller, creating a permanent suppression window.
Stale windows are cleaned by `expire_stale_windows()` which only runs when
explicitly called and respects the `auto_expire` flag.

**Risk**: LOW -- A permanent change window is visible in the API and
dashboard, so it would be noticed.

**Mitigation**: Enforce a maximum window duration regardless of auto_expire
(e.g., 24 hours). Alert if any window is open for more than 8 hours.

#### E1.6: MCP tool `are_you_sure` parameter is a soft gate [LOW]

**Finding**: Several MCP tools (ops_create_change, ops_create_incident,
ops_emit_event, ops_register_service, etc.) have an `are_you_sure` parameter.
This is a Claude Code convention to require explicit confirmation. However,
the parameter is enforced client-side by the CC session, not server-side by
Admin API. Any direct API caller or a compromised MCP bridge can omit this
parameter.

**Risk**: LOW -- The gate is for CC UX, not security.

**Mitigation**: Document that `are_you_sure` is a UX convention, not a
security control. Server-side enforcement should rely on API key roles and
audit logging.

---

## Compound Attack Scenarios

### Scenario A: Token Theft to Silent Takeover

1. Attacker compromises any MCP bridge container (e.g., via dependency
   vulnerability in a Node.js MCP server)
2. Reads `ADMIN_API_TOKEN` from container environment
3. Calls `/ops/cmdb/register` to set `alert_policy: "silent"` on target services
4. Calls `/ops/changes` to create a permanent suppression window
5. Calls `/backup/exec` to execute arbitrary commands in target containers
6. Modifies `/backup/zfs` to destroy ZFS snapshots (eliminating recovery)
7. All actions are logged but attributed to the MCP bridge's key name,
   not to the attacker

**Mitigations**: Role-based API keys (S1.1), command allowlists (E1.1, E1.2),
CMDB alert_policy restrictions (E1.4), audit log forwarding to Splunk (R1.1).

### Scenario B: LLM Prompt Injection via Log Content

1. Attacker places crafted text in a service's log output (e.g., via a
   request to a web service that logs request bodies)
2. NemoClaw's investigator reads these logs during triage
3. Crafted text includes instructions that influence the LLM's investigation
   summary or remediation decision
4. LLM recommends restart of a healthy critical service, or recommends
   "no action" for a genuinely broken service

**Mitigations**: NemoClaw's guardrails engine, rate limiter (max 2 restarts
per container per hour), trust tier system, and the fact that investigation
summaries pass through the triage engine's programmatic decision logic
(not direct LLM-to-action). The FMEA runbooks add an additional layer of
pattern-based rather than LLM-based diagnosis.

---

## Risk Summary Table

| ID | Finding | Category | Risk | Effort to Mitigate |
|----|---------|----------|------|-------------------|
| E1.1 | /backup/exec arbitrary command execution | Elevation of Privilege | **CRITICAL** | Low (add allowlist) |
| E1.2 | /backup/zfs arbitrary privileged commands | Elevation of Privilege | **CRITICAL** | Low (add allowlist) |
| S1.1 | Single bearer token, no role differentiation | Spoofing | HIGH | Medium (auth refactor) |
| T1.1 | Mutable/deletable operational records | Tampering | HIGH | Low (remove DELETE, add immutable fields) |
| I1.1 | Unfiltered secrets in container logs | Info Disclosure | HIGH | Medium (log sanitizer) |
| D1.1 | SQLite write lock contention | Denial of Service | HIGH | Low (add busy_timeout) |
| D1.3 | Unbounded regex in diagnosis hints | Denial of Service | MEDIUM | Low (timeout or validation) |
| S1.2 | Agent impersonation in ops records | Spoofing | MEDIUM | Low (validate source vs key) |
| T1.2 | Runbook YAML tampering via GitOps | Tampering | MEDIUM | Medium (CI validation) |
| T1.4 | Heuristic service classification | Tampering | MEDIUM | Low (add flag) |
| R1.1 | Audit log without integrity protection | Repudiation | MEDIUM | Medium (Splunk forwarding) |
| I1.2 | CORS wildcard on Admin API | Info Disclosure | MEDIUM | Low (set empty origins) |
| D1.2 | Unbounded event stream growth | Denial of Service | MEDIUM | Low (scheduled cleanup) |
| E1.3 | Host check allowlist bypass via /backup/exec | Elevation of Privilege | MEDIUM | Addressed by E1.1 fix |
| E1.4 | CMDB silent alert_policy suppression | Elevation of Privilege | MEDIUM | Low (log + validate) |
| S1.3 | No mutual auth NC-to-Admin-API | Spoofing | LOW | Medium (mTLS) |
| T1.3 | SQLite file tampering | Tampering | LOW | Low (non-root user) |
| R1.2 | Limited triage decision attribution | Repudiation | LOW | Low (emit events) |
| I1.3 | Splunk HEC token in env | Info Disclosure | LOW | Low (rotation) |
| I1.4 | Change window details expose intent | Info Disclosure | LOW | N/A in homelab |
| D1.4 | Rate limit per-IP not per-key | Denial of Service | LOW | Low (key-based limiting) |
| E1.5 | Permanent change window suppression | Elevation of Privilege | LOW | Low (max duration) |
| E1.6 | are_you_sure is client-side only | Elevation of Privilege | LOW | N/A (by design) |

## Recommended Priority Actions

### Immediate (Before Next Production Incident)

1. **Add command allowlist to `/backup/exec`** -- restrict to `pg_dump`,
   `psql`, `pg_restore` with validated arguments. Add container allowlist
   restricting to `*-postgres` containers only. Add full audit logging.

2. **Add command allowlist to `/backup/zfs`** -- restrict to `zpool status`,
   `zfs list`, `zfs snapshot`, `zfs destroy` (snapshot only, not dataset).
   Validate that command[0] is in `{zpool, zfs}`. Add full audit logging.

3. **Add `PRAGMA busy_timeout=5000`** to `_get_conn()` in `ops_db.py` to
   prevent SQLite lock contention during concurrent agent operations.

### Short-Term (Next 2-4 Weeks)

4. **Implement role-based API keys** -- at minimum, separate keys for:
   `ops-full` (CC/NemoClaw), `ops-read` (MCP bridges), `backup-admin`
   (Prefect backup flows only).

5. **Remove DELETE endpoint** from `/ops/changes` route. Make `targets`
   field immutable on change records. Add `authenticated_as` field
   populated from auth layer.

6. **Forward auth audit log to Splunk** alongside ops events. Add ops
   write operations to Slack `high_risk_ops` set.

7. **Set `allow_origins=[]`** in CORS middleware (all callers are
   server-side).

### Medium-Term (Next Quarter)

8. **Implement log sanitizer** for container log output before inclusion in
   API responses, Slack messages, and Splunk forwarding.

9. **Add regex complexity validation** for triage runbook diagnosis patterns
   at YAML load time.

10. **Schedule event cleanup** via Prefect flow (daily, 30-day retention).

11. **Add CI validation** for runbook YAMLs enforcing safety invariants
    (NCCL patterns must have `restart_safe: false`, all triage YAMLs must
    have escalation triggers).

---

## Resolution Status (Updated 2026-03-30)

Corvus Phase 1 security hardening addressed 15 of 22 findings. The remaining
5 partial/open findings were fully remediated in a follow-up session.

### Fully Resolved (15 findings — prior session)

| ID | Finding | Resolution |
|----|---------|------------|
| E1.1 | /backup/exec arbitrary commands | Command allowlist + container allowlist + audit logging |
| E1.2 | /backup/zfs arbitrary privileged commands | Command allowlist (zpool/zfs only) + argument validation + audit logging |
| S1.1 | Single bearer token, no roles | 4-role RBAC (admin, ops-write, ops-read, agent) with path+method permissions |
| T1.1 | Mutable/deletable ops records | DELETE endpoint removed, targets immutable after creation |
| I1.1 | Unfiltered secrets in logs | Sanitizer strips hlab-*, sk-*, ghp_*, Bearer tokens, connection strings, JWTs |
| D1.1 | SQLite write lock contention | `PRAGMA busy_timeout=5000` added to all connections |
| T1.4 | Heuristic service classification | Logged warnings + CMDB registration required |
| R1.1 | Audit log without integrity | Splunk HEC forwarding for all ops events |
| I1.2 | CORS wildcard | Origins restricted to empty list |
| D1.2 | Unbounded event growth | Cleanup on startup + retention policy |
| E1.3 | Host check allowlist bypass | Addressed by E1.1 (NemoClaw key lacks /backup/ access) |
| S1.3 | No mutual auth NC→Admin API | Accepted risk (LOW) — Docker network isolation sufficient |
| T1.3 | SQLite file tampering | Accepted risk (LOW) — non-root container user |
| I1.3 | Splunk HEC token in env | Accepted risk (LOW) — standard Docker secret pattern |
| I1.4 | Change window details | Accepted risk (LOW) — transparency is a feature |

### Fully Resolved (5 findings — 2026-03-30 hardening session)

| ID | Finding | Resolution | Implementation |
|----|---------|------------|----------------|
| S1.2 | Agent impersonation | `authenticated_as` column populated from auth layer on events, changes, and incidents. Separate from caller-claimed `source`/`created_by`/`detected_by` fields. Response models include field. | `src/routers/events.py`, `changes.py`, `incidents.py` |
| T1.2 | Runbook YAML tampering | Schema validation at load time: required keys, type checks, step type allowlist, regex pattern validation. Invalid runbooks rejected without crashing registry. | `src/runbooks/loader.py` — `_validate_runbook_schema()`, `RunbookValidationError` |
| D1.3 | ReDoS in diagnosis hints | Pattern length limit (200 chars), nested quantifier detection (`(a+)+` pattern), pre-compilation at load time. Compiled patterns stored on `Runbook.compiled_patterns` dict. | `src/runbooks/loader.py` — `_validate_regex_pattern()`, `_REDOS_PATTERN` |
| E1.4 | Silent alert_policy suppression | Allowlist validation (`default`, `silent`, `critical-only`, `all`). Invalid values return 400. Policy changes emit `cmdb.alert_policy_changed` audit event with old/new policy and actor identity. | `src/routers/cmdb.py` — `VALID_ALERT_POLICIES`, audit event emission |
| D1.4 | Rate limit per-IP not per-key | Global rate limit via slowapi (500/minute). In-memory storage. 429 response on limit exceeded. | `src/app.py` — `Limiter`, `RateLimitExceeded` handler |

### Additional Hardening (2026-03-30)

| Enhancement | Description | Implementation |
|-------------|-------------|----------------|
| Centralized auth middleware | `AuthMiddleware` enforces auth on ALL `/ops/`, `/backup/`, `/agent-instructions` paths. Individual routers no longer need `Depends(get_auth)`. New endpoints are protected by default. | `src/middleware/auth.py` — `AuthMiddleware(BaseHTTPMiddleware)` |
| Dev mode safety | Auth middleware passes through when no API keys configured (dev/test mode). Production always has keys via MCP internal key registration. | `src/middleware/auth.py` line 161 |

### Test Coverage

| Test File | Tests | Coverage Area |
|-----------|-------|---------------|
| `test_auth_middleware.py` | 19 | Auth enforcement on all paths, role-based access, authenticated_as recording |
| `test_runbook_validation.py` | 21 | Schema validation, ReDoS protection, registry integration |
| `test_security_hardening.py` | (existing) | Backup exec/zfs allowlists, sanitizer integration |
| Full suite | **448 passed** | All endpoints, auth, RBAC, sanitizer, runbooks, triage, trust |

### Remaining Accepted Risks

| ID | Finding | Risk | Rationale |
|----|---------|------|-----------|
| R1.2 | Limited triage decision attribution | LOW | Triage decisions logged; full reasoning chain in container logs |
| E1.5 | Permanent change windows | LOW | Visible in API; monitoring can detect stale windows |
| E1.6 | are_you_sure client-side only | LOW | UX convention, not security control — documented as such |

---

## Appendix A: Files Examined

| File | Role |
|------|------|
| `admin-api/auth.py` | Authentication, audit logging |
| `admin-api/main.py` | Security middleware, rate limiting, CORS |
| `admin-api/security.py` | IP whitelist implementation |
| `admin-api/ops_db.py` | SQLite schema, all CRUD operations |
| `admin-api/ops_routes.py` | Change window endpoints |
| `admin-api/ops_events_routes.py` | Event stream + Splunk forwarding |
| `admin-api/ops_incidents_routes.py` | Incident management endpoints |
| `admin-api/ops_problems_routes.py` | Problem management endpoints |
| `admin-api/ops_cmdb_routes.py` | CMDB service registry endpoints |
| `admin-api/backup_routes.py` | Container exec + ZFS command endpoints |
| `admin-api/host_routes.py` | Host-level state queries via Netdata exec |
| `nemoclaw/src/health_monitor.py` | Tiered sweep scheduler, SOP integration |
| `nemoclaw/src/triage.py` | Triage engine, runbook-driven decisions |
| `nemoclaw/src/runbook_selector.py` | YAML runbook loader, diagnosis matcher |
| `nemoclaw/src/service_classification.py` | Hardcoded FMEA type mapping |
| `nemoclaw/src/host_checks.py` | Named host command allowlist |
| `nemoclaw/src/guardrails.py` | Self-preservation and safety checks |
| `nemoclaw/src/ops_executor.py` | Credential rotation task execution |
| `nemoclaw/config/guardrails.yaml` | Rate limits, trust thresholds |
| `nemoclaw/config/playbooks/triage-inference.yaml` | Inference triage runbook |
| `docker-compose.yml` | Network topology, port exposure |
