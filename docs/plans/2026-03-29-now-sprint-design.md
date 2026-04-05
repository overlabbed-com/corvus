# NOW Sprint Design — Issues #3, #7, #17

> Approved: 2026-03-29
> Issues: #3 (Compliance Instrumentation), #7 (Threat Model CRITICALs), #17 (Log Sanitizer)
> Parallel execution: 3 independent branches

---

## Issue #7: Threat Model CRITICAL Remediation

### New: Backup Router (`src/routers/backup.py`)

**`POST /backup/exec`** — Container command execution with security controls:

- **Command allowlist**: `pg_dump`, `psql`, `pg_restore` only, with validated argument patterns
- **Container allowlist**: only containers matching `*-postgres`
- **Audit logging**: every call logged with command, container, actor, result
- **Auth**: requires `admin` role

**`POST /backup/zfs`** — ZFS operations via privileged container:

- **Command allowlist**: `zpool status`, `zfs list`, `zfs snapshot`, `zfs destroy` (snapshots only)
- **Argument validation**: `command[0]` must be in `{zpool, zfs}`, no shell metacharacters
- **Audit logging**: same as exec
- **Auth**: requires `admin` role

### Existing code changes (HIGH findings)

- **T1.1**: Remove `DELETE /ops/changes/{id}`. Add `authenticated_as` field to changes/incidents/events (from auth context). Make change `targets` immutable after creation.
- **I1.2**: Set `allow_origins=[]` in CORS middleware.
- **R1.1**: Forward audit log entries to Splunk HEC alongside ops events.

### Files to create/modify

- Create: `src/routers/backup.py`
- Modify: `src/routers/changes.py` (remove DELETE, immutable targets, authenticated_as)
- Modify: `src/routers/events.py` (authenticated_as)
- Modify: `src/routers/incidents.py` (authenticated_as)
- Modify: `src/app.py` (CORS fix, register backup router)
- Modify: `src/middleware/audit.py` (forward to SIEM)
- Tests: `tests/test_backup.py`, `tests/test_security_hardening.py`

---

## Issue #17: Log Sanitizer

### New: `src/sanitizer.py`

Regex-based secret stripping module.

**Default patterns**:

| Pattern | Matches |
|---------|---------|
| `hlab-[A-Za-z0-9_-]+` | Homelab API keys |
| `sk-[A-Za-z0-9_-]{20,}` | OpenAI/Anthropic keys |
| `ghp_[A-Za-z0-9]{36,}` | GitHub personal tokens |
| `ghs_[A-Za-z0-9]{36,}` | GitHub server tokens |
| `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*` | JWT tokens |
| `Bearer\s+[A-Za-z0-9_.\-/+=]+` | Bearer auth headers |
| `(postgres\|mysql\|redis)://[^@]+@` | Connection strings with creds |
| `AKIA[A-Z0-9]{16}` | AWS access key IDs |
| `password=['"][^'"]+['"]` | Password assignments |
| `(secret\|token\|api_key)=['"][^'"]+['"]` | Generic secret assignments |

**API**: `sanitize(text: str) -> str` — replaces matches with `[REDACTED]`

**Configuration**: `SANITIZER_EXTRA_PATTERNS` env var (comma-separated regexes)

**Hook points**:

- `src/siem/forwarder.py` — sanitize event data before Splunk HEC
- `src/routers/backup.py` — sanitize command output in API responses

**Tests**: Known secret patterns, edge cases (don't redact "skeleton" for `sk-` pattern), extra pattern config.

### Files to create/modify

- Create: `src/sanitizer.py`
- Modify: `src/siem/forwarder.py` (call sanitize before forwarding)
- Modify: `src/routers/backup.py` (sanitize command output)
- Tests: `tests/test_sanitizer.py`

---

## Issue #3: Compliance Instrumentation

### Changes to `src/routers/metrics.py`

Extend `GET /ops/metrics` response with:

- `compliance_rate`: % of changes with corresponding events
- `event_emission_gap_count`: changes without events
- `uncovered_event_types`: event types with zero occurrences in last 24h

### New: Compliance audit endpoint

**`GET /ops/metrics/compliance`** — Detailed compliance breakdown:

- Changes vs events gap analysis
- Incidents vs resolution events
- Per-source breakdown (claude-code vs nemoclaw)
- Auto-flags gaps as problem records via existing gap detection

### New: `src/tasks/compliance_audit.py`

Session-level compliance logic:

- Query changes → match to events by target + time window
- Query incidents → match to resolution events
- Calculate compliance rate: `(changes_with_events / total_changes) * 100`
- Measurement window: last 7 days or last 10 sessions

### Files to create/modify

- Create: `src/tasks/compliance_audit.py`
- Modify: `src/routers/metrics.py` (add compliance stats + new endpoint)
- Tests: `tests/test_compliance_audit.py`

---

## Independence Check

| | #7 Security | #17 Sanitizer | #3 Compliance |
|---|---|---|---|
| **#7 Security** | — | #17 hooks into backup router from #7, but sanitizer module is standalone | No dependency |
| **#17 Sanitizer** | Backup router integration can be done in either branch | — | No dependency |
| **#3 Compliance** | No dependency | No dependency | — |

Note: #17 hooks into backup.py (from #7) and forwarder.py. The sanitizer module itself is independent. Integration into backup.py can happen in whichever branch merges second.
