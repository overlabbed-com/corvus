# Investigation Standards

Defines how agents collect and classify evidence during incident investigation.
Every agent's investigation becomes comparable, composable, and governed.

**Principle**: Corvus owns the investigation contract. Agents are consumers.
No agent maintains its own log patterns, exit code rules, or evidence schemas.

## Log Collection Standard

Agents MUST separate log output into three categories before any diagnosis.
Diagnosis rules ONLY run against `error_lines`. Health check noise MUST NOT
trigger pattern matching.

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
```

### Agent Contract

- Agents MUST separate log lines into these 3 categories before diagnosis
- Diagnosis hints MUST only match against `error_lines`
- Health check noise MUST NOT trigger pattern matching
- Corvus server returns 422 on investigation reports with unseparated logs

## Exit Code Semantics

Exit code is a mandatory field on every investigation report. Exit code MUST be
checked BEFORE log pattern matching.

```yaml
exit_code_semantics:
  0:   { class: "clean_shutdown", is_failure: false, action: "log_only" }
  1:   { class: "app_error",     is_failure: true,  action: "investigate" }
  2:   { class: "misuse",        is_failure: true,  action: "investigate_config" }
  137: { class: "sigkill",       is_failure: true,  action: "investigate_oom_or_external" }
  139: { class: "segfault",      is_failure: true,  action: "investigate_crash" }
  143: { class: "sigterm",       is_failure: false,  action: "log_only" }
```

### Rules

- Exit code MUST be included in every investigation report
- Exit code 0 or 143 MUST NOT be classified as a failure
- Exit code MUST be checked BEFORE log pattern matching
- If exit code is 0 and container status is `exited`, diagnosis is `clean_shutdown`
- Corvus server returns 422 on investigation reports missing `exit_code`

## Pattern Quality Requirements

Every diagnosis pattern (in runbook `diagnosis_hints`) must meet these standards:

### Rules

1. All patterns MUST use word boundaries (`\b`) for tokens shorter than 6 characters
2. Numeric patterns (401, 403, 500) MUST require HTTP response context
3. Each pattern SHOULD include a `false_positive_filter` regex
4. Patterns MUST be tested against the false-positive corpus before shipping

### Examples

**Good pattern:**
```yaml
name: auth_failure
match: '\\bHTTP[/ ]\\d+\\.?\\d*"?\\s+401\\b|\\b(?:unauthorized|authentication failed|invalid.token)\\b'
false_positive_filter: 'health.*200|GET /health.*OK'
```

**Bad pattern (common mistake):**
```yaml
name: auth_failure
match: '(?i)401|403|unauthorized'
# Why bad: matches port numbers (4010), version strings (v4.0.1),
# request IDs, and any 3-digit substring containing 401
```

## Evidence Schema

Standard fields every investigation report must include:

```yaml
investigation_report:
  required_fields:
    target: string           # Container/service name
    host: string             # Host where target runs
    exit_code: integer|null  # Container exit code (null if still running)
    uptime_seconds: integer  # Seconds since container started
    restart_count: integer   # Docker restart count
    error_lines: string[]    # Filtered error log lines
    resource_state:          # Host resource snapshot
      ram_percent: float
      disk_percent: float
      gpu_vram_percent: float|null
      gpu_temperature: float|null
    dependency_health: map   # {dep_name: "healthy"|"unhealthy"|"missing"}

  optional_fields:
    health_lines: string[]         # Filtered health check lines
    app_lines: string[]            # Everything else
    correlation_group_id: string   # If part of a correlated failure group
    drift_report: map              # Config drift details if detected
```

## API

### Submit Investigation
```
POST /ops/runbooks/triage
```
Server validates the evidence schema. Returns 422 if:
- `exit_code` is missing
- `error_lines` key is missing (unseparated logs)

Returns warning header if:
- `resource_state` is missing (graceful degradation, not rejection)
