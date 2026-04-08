# Corvus Hooks — Threat Model & Security Assessment

**Date:** 2026-04-08
**Scope:** corvus-hooks/ (1,733 lines across 7 Python files + 1 shell installer)
**Assessment Type:** Threat model + SAST scan + Architect/Advocate/Auditor review

---

## Executive Summary

The corvus-hooks package is a governance enforcement layer for AI coding assistants.
It intercepts tool calls at the harness level (outside model control) and checks a
Corvus server for conflicts before allowing destructive infrastructure actions.

**Risk posture: LOW.** The hooks are thin shims (~70-200 lines each) with a fail-open
design. The attack surface is small — stdin JSON parsing, one HTTP call to Corvus,
and macOS keychain access. No user input reaches shell commands. No secrets are stored
on disk.

## SAST Results

### Semgrep (187 rules, p/python + p/secrets)

**0 findings.** Clean scan.

### Bandit (corvus-hooks/)

| Severity | Count | Disposition |
|----------|-------|-------------|
| MEDIUM | 2 | False positive (urlopen scheme validated at module load) |
| LOW | 3 | Expected (subprocess for macOS keychain, hardcoded command) |

**Details:**
- `corvus_core.py:86,122` — `urlopen` audit. **Mitigated:** URL scheme validated
  at import time (`http://` or `https://` only). `ValueError` raised for other schemes.
- `corvus_core.py:19,49` — subprocess import/use. **Accepted:** Calls hardcoded
  `security find-generic-password` binary. No user input in subprocess args.

## Threat Model

### Assets

| Asset | Sensitivity | Location |
|-------|-------------|----------|
| Corvus API key | HIGH | macOS keychain or env var (never on disk) |
| Hook stdin JSON | LOW | Tool call metadata (command strings, tool names) |
| Corvus API responses | LOW | GO/CAUTION/STOP recommendation + reason |

### Attack Surface

| Entry Point | Data Flow | Risk |
|-------------|-----------|------|
| stdin JSON (from AI harness) | Parsed, fields extracted, used in HTTP request path | LOW — harness-controlled, not user-controlled |
| CORVUS_GOVERNANCE_URL env var | Used to construct HTTP URLs | LOW — scheme-validated at import |
| CORVUS_API_KEY / keychain | Bearer token in Authorization header | MEDIUM — standard credential handling |
| Corvus API response | JSON parsed, recommendation extracted | LOW — fail-open on parse error |

### Threat Scenarios

#### T1: Malicious Corvus server response
**Vector:** Attacker controls or MITM's the Corvus endpoint.
**Impact:** Could return false GO/STOP recommendations, causing agents to act/block
incorrectly.
**Mitigation:** URL scheme validation prevents `file://` SSRF. TLS recommended for
production (env var supports `https://`). Fail-open design limits blast radius of
false STOP to one tool call retry.
**Residual risk:** LOW. Attacker with network position could disrupt governance
but cannot execute code.

#### T2: API key extraction from macOS keychain
**Vector:** Malware on the developer's Mac reads keychain entries.
**Impact:** Attacker could call Corvus API with stolen key.
**Mitigation:** macOS keychain access requires user approval or app signing.
Key scope is limited to Corvus read/write operations (no infrastructure access).
**Residual risk:** LOW. Standard macOS credential hygiene applies.

#### T3: Command injection via hook stdin
**Vector:** AI model crafts a tool_input that escapes regex and reaches `subprocess`.
**Impact:** None. No stdin data ever reaches `subprocess.run`. The only subprocess
call is `security find-generic-password` with hardcoded arguments.
**Residual risk:** NONE.

#### T4: Installer command injection
**Vector:** Attacker controls `--source-dir` or `--project-dir` arguments.
**Impact:** The `eval "$2"` in `do_cmd()` executes hardcoded command strings, not
user input. Arguments are quoted in the command strings.
**Mitigation:** All `do_cmd` callers pass string literals. Comment documents safety
assumption.
**Residual risk:** LOW. Would require modifying the script itself.

#### T5: URL path injection via target name
**Vector:** Container name like `../../admin` could modify the URL path.
**Impact:** Could redirect the conflict check to a different API path.
**Mitigation:** Target names are extracted by regex from docker commands. The
regex `[a-zA-Z0-9][a-zA-Z0-9_.:-]+` constrains characters (no `/` or `..`).
**Residual risk:** NONE. Regex prevents path traversal characters.

#### T6: Symlink substitution in installer
**Vector:** Attacker plants symlinks in target directories before install.
**Impact:** Installer uses `cp` (not `ln -s`), which follows symlinks on read
but writes to the actual target path. Could overwrite unexpected files if
`~/.claude/hooks/` contains a symlink.
**Mitigation:** Installer creates directories with `mkdir -p` before copying.
Standard Unix permission model applies.
**Residual risk:** LOW. Requires pre-existing filesystem access.

## Architect Assessment

### Design Strengths
1. **Fail-open by default** — Corvus unreachable or API key missing = allow action
   with warning. No single point of failure.
2. **No secrets on disk** — API key lives in macOS keychain or env var only.
3. **Scheme validation** — `CORVUS_GOVERNANCE_URL` rejects non-HTTP schemes at
   import time, preventing SSRF via `file://` or custom schemes.
4. **Regex-constrained targets** — Container/volume/network names extracted by
   strict character class regex. No path traversal possible.
5. **Harness-level enforcement** — Hooks run outside model control. The AI cannot
   skip, rationalize around, or modify the governance check.
6. **Cross-tool consistency** — All 10 supported tools get the same governance
   logic via shared `corvus_core.py`. No per-tool divergence.

### Design Concerns
1. **HTTP default** — `CORVUS_GOVERNANCE_URL` defaults to `http://localhost:9420`.
   Production deployments should use HTTPS. Consider logging a warning when HTTP
   is used with a non-localhost host.
2. **No response signature verification** — Corvus responses are not signed.
   MITM on the Corvus connection could inject false recommendations.
   Acceptable for v1 given typical deployment topology (same host or LAN).

## Advocate Challenge

### What could go wrong?

1. **False STOP on legitimate actions** — If Corvus has stale incident/change data,
   hooks will block legitimate work. Fail-open design means this only happens when
   Corvus is reachable but has bad data.
   **Verdict:** Acceptable. Operators can always restart without hooks.

2. **Regex gaps in target extraction** — If a new docker subcommand or SSH pattern
   isn't matched, destructive actions pass without governance check.
   **Verdict:** Known limitation. Coverage is explicit, not comprehensive.
   Document supported patterns.

3. **Intent classification false positives** — "Fix the blog CSS" might trigger
   incident workflow. The `FALSE_POSITIVE_PATTERNS` list helps but isn't exhaustive.
   **Verdict:** Acceptable. False classification injects a mandate via stderr but
   never blocks. The operator can ignore it.

4. **Installer overwrites existing hooks** — If a user has custom
   `~/.claude/hooks/corvus-governance.py`, the installer overwrites it silently.
   **Verdict:** Minor. Add a backup or prompt before overwriting.

## Auditor Findings

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| 1 | INFO | Bandit MEDIUM: urlopen scheme audit (2 findings) | Mitigated — scheme validated at import |
| 2 | INFO | Bandit LOW: subprocess usage (3 findings) | Accepted — hardcoded command, no user input |
| 3 | LOW | HTTP default for CORVUS_GOVERNANCE_URL | Accepted for v1 — localhost default is safe |
| 4 | INFO | Installer eval safety | Documented — all callers pass hardcoded strings |
| 5 | NONE | No secrets in code, no hardcoded credentials | Clean |
| 6 | NONE | No SQL injection surface (no database) | Clean |
| 7 | NONE | No XSS surface (no HTML output) | Clean |
| 8 | NONE | No deserialization beyond JSON | Clean |

## Remediation Applied This Session

| Fix | File | Description |
|-----|------|-------------|
| URL scheme validation | `corvus_core.py:28-30` | Reject non-HTTP/HTTPS schemes at import time |
| Trailing slash strip | `corvus_core.py:30` | Prevent double-slash in URL construction |
| Remove unused imports | `corvus_core.py`, adapters/*.py | Removed `List`, `Optional`, `Any`, `Dict` where unused |
| Document eval safety | `install-corvus-governance.sh:53` | Comment explains why eval is safe here |
| .gitignore hardening | `.gitignore` | Added `.ruff_cache/`, clarified `.claude/` comment |

## Recommendations (Future)

1. **Warn on non-localhost HTTP** — Log a stderr warning if `CORVUS_GOVERNANCE_URL`
   uses `http://` with a non-localhost host.
2. **Installer backup** — Before overwriting existing hook files, copy originals
   to `*.bak`.
3. **Integration tests** — Add pytest suite that validates regex patterns against
   known docker/SSH command strings.
4. **Hook versioning** — Add a version marker to installed hooks so the installer
   can detect stale deployments.
