# The Dev Gap Backlog — what the green does not prove

**Baseline**: worktree `corvus-gap-backlog`, branch `docs/dev-gap-backlog`, from `origin/main`
`be0ba58` (the harness merge, PR #51).
**Source**: `docs/DEV-READINESS-REVIEW.md` §3, §5, §7 — re-run, not copied. The review's baseline
was `2191155`; every number below was re-derived on `be0ba58`, and one review claim no longer
holds (§0).
**Method**: every entry carries the instrument that settles it — a command with its output, a
`file:line`, or an executed probe. Where I ran the thing, the output is quoted. Claims I could
not settle are in §4, not softened into the prose.

## 0. One review claim is now stale

Review §3.2 says the P1 conformance gate "is not gated … no mutation, no conformance run [in CI]".
That was true at `2191155` and is false at `be0ba58`:

~~~
$ git show 2191155:.github/workflows/ci-v2.yaml | grep -E 'mutation|conformance'   # no match
$ sed -n '45,63p' .github/workflows/ci-v2.yaml                                    # the phase-gates job
      - name: Mutation evidence
        run: make mutation
      - name: Conformance run
        run: make conformance
$ gh run view 40059341183 --repo overlabbed-com/corvus --json jobs \
    --jq '.jobs[] | select(.name=="phase-gates") | .conclusion'                   # success
$ gh run view 40059341183 --job 120769245576 --log | grep -E 'all_mutants_caught|"caught"|"passed"'
 "all_mutants_caught": true,
   "id": "M1-permissive-fail-answer",   "caught": true,
   "id": "M2-enum-widened-uncovered",   "caught": true,
   "id": "M3-client-conflation-restored","caught": true,
   "id": "M4-permissive-default-restored","caught": true,
 "passed": 2,
 "failed": 0,
~~~

So the gate exists and is green. GB-8 and GB-9 are therefore **not** "make the gate exist" — they
are "make the gate's evidence mean what it says". The corpus it runs is two checks
(`happy-path`, `existence-hiding`), which is worth knowing before quoting "the conformance
suite runs green" as coverage.

## 1. How to read an entry

`GB-n` · **Blocks** — the capability (PRODUCT.md's four) and the phase gate that needs it next
(BUILD-PLAN.md's P1–P4) · **Evidence** — the instrument, re-run on this branch · **Why** — what the
gap prevents someone from claiming or doing · **Acceptance** — the check that closes it, runnable
as written · **Depends on** — other entries, or an artifact that lives outside this repo.

| ID | One line | Capability | Phase | Order |
|---|---|---|---|---|
| GB-1 | The clients speak v1; neither works against a real v2 server | 1 change control | P1, P3 | 4 |
| GB-2 | The trust ledger is unwired — nothing writes `ops_trust` | 3 graded autonomy | P1, P3 | 3 |
| GB-3 | The live artifact is a one-route shim; the CCB has no deployment | 1 change control | P1 | 7 |
| GB-4 | The CCB's six routes have no pytest test (app.py at 0%) | 1 change control | P1 | 1 |
| GB-5 | The live capture store is an `emptyDir` on a `Recreate` deployment | 3 graded autonomy | P1, P3 | 6 |
| GB-6 | OCSF/SIEM is absent from v2 | 2 shared awareness | P2, P3 | 8 |
| GB-7 | No lockfiles: the tested resolve is not the installed one | build integrity | P3 | 10 |
| GB-8 | The mutation runner rewrites the working tree and cannot tell a kill from a crash | gate instrument | P1 | 5 |
| GB-9 | The contract tests share a fixed port and never stop their servers | gate instrument | P1 | 2 |
| GB-10 | The alert file names metrics nothing emits | 2 shared awareness | P2 | 9 |

## 2. The entries

### GB-1 — The clients speak v1, and neither works against a real v2 server

**Blocks** change control (capability 1) — the pre-action call is the product's core call. Next
needed by **P1** (the adapter's brake-pedal integration) and **P3** ("the SDK reduced to the
documented HTTP contract").

**Evidence**

- The static count, re-run: 30 distinct SDK paths, 3 matching v2's route set; 15 CLI paths, 3
  matching.
  ~~~
  $ python3.12 - <<'PY'   # regex over app.py decorators vs the clients' path literals
  v2 routes: ['/health', '/ops/changes', '/ops/changes/active', '/ops/conflict-check',
              '/ops/events', '/ops/events/stream']
  sdk paths: 30  exact v2 matches: 3
  cli paths: 15  exact v2 matches: 3
  ~~~
- The call that matters is unserved. `CorvusClient.check_target` GETs
  `/ops/events/targets/{target}/status` (`corvus-sdk/src/corvus_sdk/client.py:93`) and
  `corvus check-target` does the same (`corvus-cli/src/corvus_cli/main.py:58`); v2 serves the
  decision at `/ops/conflict-check` (`corvus-v2/corvus/app.py:116`).
- **The 3 path matches are 0 working methods.** Executed against a real `create_app()` on an
  ephemeral port:
  ~~~
  $ .venv/bin/python - <<'PY'   # a throwaway probe: create_app() on an ephemeral port,
                                # CorvusClient driven against it
  check_target:   CorvusError 404: Not Found
  emit_event:     CorvusError 401: invalid or missing X-Corvus-Key
  create_change:  CorvusError 401: invalid or missing X-Corvus-Key
  active_changes: CorvusError 401: invalid or missing X-Corvus-Key
  ~~~
  The 401s are the auth contract: the SDK sends `Authorization: Bearer`
  (`client.py:57`) and the CLI does too (`main.py:33`); v2 reads `X-Corvus-Key`
  (`app.py:52`). Adding the header the clients do not send isolates a second layer:
  ~~~
  emit_event:     KeyError: 'timestamp'      # v2 returns {id, hlc_timestamp, type, target, signature}
  create_change:  KeyError: 'created_at'     # v2 returns {id, targets, status}
  active_changes: 422 missing query param 'target'
  $ CORVUS_URL=http://127.0.0.1:<port> CORVUS_TOKEN=k corvus check-target db
  exit 1  Error 404: {"detail":"Not Found"}
  $ CORVUS_URL=... CORVUS_TOKEN=k corvus changes
  exit 1  Error 401: {"detail":"invalid or missing X-Corvus-Key"}
  ~~~
- No parity test exists. SDK tests are `respx`-mocked (`corvus-sdk/tests/test_client.py:7`); the
  CLI fixture says "No test ever opens a socket" (`corvus-cli/tests/conftest.py:3`); the only
  test that starts a server drives `DecisionClient`, not the SDK
  (`corvus-v2/tests/test_decision_contract.py:39`).
- The v2 client does exist, inside the engine: `DecisionClient`
  (`corvus-v2/corvus/decisions.py:17`). The published SDK has no `decide` method at all
  (`grep -n 'def decide' corvus-sdk/src` → no match).

**Why it matters.** Both clients are 100% covered, green, and unusable against the thing that
serves the product: all three path-matching SDK methods fail on the wire, the other 27 hit
unserved paths, and the brake-pedal command exits 1. Green proves their own logic, which is the
definition of the gap.

**Acceptance**

- **AC-1a** — the count is machine-checked. A committed script derives the served set from the
  FastAPI app object and the called set from the SDK/CLI sources, and exits non-zero on any path in
  neither the served set nor an explicit `UNSERVED` manifest entry with a reason. Runnable:
  `python3.12 scripts/route_parity.py; echo $?` → 0, and deleting a decorator from `app.py`
  reds it. CI runs it in the harness matrix.
- **AC-1b** — parity is executed. A test starts `create_app()` on an ephemeral port and drives
  every SDK method whose path is in the served set; a 404, 405, 401 or a `KeyError` fails.
  Runnable: `cd corvus-v2 && .venv/bin/python -m pytest tests/test_client_parity.py -q`. It is red
  today, which is the point.

**Depends on** GB-4 (the server fixture) and GB-9 (the fixture pattern it should copy).

### GB-2 — The trust ledger is unwired: nothing writes `ops_trust`

**Blocks** graded autonomy (capability 3). **P1** delivers the ledger; **P3**'s flip gate spends it
("AUTO grants are earned only by enforced outcomes").

**Evidence**

- `grep -rn 'TrustLedger' --include=*.py .` → one line, its own definition
  (`corvus-v2/corvus/trust.py:52`). No importer anywhere.
- `grep -rn 'ops_trust' --include=*.py .` → two lines: the table DDL
  (`corvus-v2/corvus/state.py:49`) and one SELECT (`corvus-v2/corvus/core.py:133`). No INSERT,
  no UPDATE.
- Two stores, no bridge. `TrustLedger` keeps its tiers in an in-memory dict
  (`trust.py:57`) in front of an `AttestedStore` (`trust.py:53-56`); the conflict check
  reads the SQLite table and defaults to `ESCALATE` when the row is absent (`core.py:137`).
- The default is what the tests pin: `tests/test_spine.py:65-68` asserts
  `trust_tier == "ESCALATE"` and `recommendation == "CAUTION"`. No test promotes a tier and
  observes a different answer.
- `trust.py` is 0% covered — `corvus/trust.py` 0 of 61 statements in the committed
  `corvus-v2/coverage.json`.

**Why it matters.** Every live answer carries the same tier, so the tier's effect on a decision is
unobserved; the promotion queue, the demotion and the enforce-flip gate have no write path to the
table the decision reads.

**Acceptance**

- A test (`corvus-v2/tests/test_trust_wiring.py`) that (a) drives a promotion through
  `TrustLedger`, (b) reads the same `(agent, action_type)` back through
  `CorvusCore.conflict_check` and asserts the returned `trust_tier` is the promoted one **and**
  the recommendation differs from the `ESCALATE` case, and (c) reopens `State` at the same file
  path and finds the tier still there.
- The mechanical instrument: `grep -cE 'INSERT INTO ops_trust|UPDATE ops_trust' corvus-v2/corvus/*.py`
  → ≥1.

**Depends on** nothing: the read path already exists, so the missing half is the writer.

### GB-3 — The live artifact is a one-route shim; the CCB has no deployment

**Blocks** change control (capability 1). **P1**'s gate clause "C1 answers live traffic in observe
mode" is half-true: a decision engine answers, the change control board does not.

**Evidence**

- `kubectl get deploy,sts,ds -A | grep -i corvus` → one line:
  `corvus  deployment.apps/corvus-engine  1/1`. No second workload.
- The container sets no `command`/`args` (`kubectl -n corvus get deploy corvus-engine
  -o jsonpath='{.spec.template.spec.containers[0].command}{.spec.template.spec.containers[0].args}'`
  → empty), so the image CMD runs: `CMD ["python", "-m", "corvus.engine_shim", "--port", "8933"]`
  (`corvus-v2/Dockerfile:21`).
- The shim declares one route: `engine_shim.py:111`
  `@app.post("/v1/fleets/{fleet_id}/decide")`. No GET status route.
- Both probes are a port, not an answer: `{"tcpSocket":{"port":8933}}` for liveness and
  readiness (same `jsonpath`, `.livenessProbe` / `.readinessProbe`).
- `app.py`'s six CCB routes (`app.py:75,85,90,105,112,116`) are served by nothing.
- The designed shape is two workloads — `corvus-engine` + `corvus` (the organization layer)
  — in `docs/canonical-path/OPS-READINESS.md:15-20`. One exists.
- The deployed image is `harbor…/corvus-v2:2191155`, not `be0ba58`: merged is not live.

**Why it matters.** The conflict check, the event stream and the change windows are not in the live
system, and a TCP-open probe cannot tell an operator whether the CCB is answering — only that a
port accepted a connection.

**Acceptance**

- **AC-3a** — the engine answers an HTTP health check and the probes use it: a `GET /health` (or
  `/v1/health`) returns 200 with a body naming the register version and the capture store path;
  `kubectl -n corvus get deploy corvus-engine -o jsonpath='{…livenessProbe.httpGet}'` is non-empty.
- **AC-3b** — the second workload serves the six routes:
  `kubectl -n corvus get deploy corvus -o jsonpath='{.status.readyReplicas}'` → ≥1, and an
  in-cluster `GET /ops/conflict-check?target=<t>` returns 200 with a `recommendation` field. The
  image can serve it without a new Dockerfile — `uvicorn corvus.app:create_app --factory`, which
  runs locally today: `cd corvus-v2 && .venv/bin/python -m uvicorn corvus.app:create_app --factory --port 0`.
- Both checks are estate-tier (they touch a live target) and need the DDR the manifest change
  carries; the manifests live in the estate repo, not here.

**Depends on** GB-4 (do not deploy an untested surface) and GB-5 (the attested stores belong to the
second workload per OPS-READINESS).

### GB-4 — The CCB's six routes have no pytest test (app.py at 0%)

**Blocks** change control (capability 1) and breakage tracking (4). **P1**.

**Evidence**

- `corvus-v2/coverage.json` (committed at `be0ba58`): `corvus/app.py` — 0 of 78 statements,
  0%.
- `grep -rn 'corvus.app' corvus-v2/tests/` → no match. The two test modules that import an app
  import `corvus.engine_shim` (`tests/conftest.py:30`, `tests/test_decision_contract.py:39`).
- What does exercise it: `scripts/dev_check.py:21` imports `create_app` and asserts `/health`,
  one authenticated `GET /ops/events`, and a 401 control — 2 of 7 paths, no write path, and it is
  the build step, not a test with a per-route assertion.
- The untested routes are the ones that change state: `POST /ops/events`, `POST /ops/changes`,
  `GET /ops/changes/active`, `GET /ops/conflict-check`, and the SSE stream.
- **The gap is not cosmetic — the first test is red today.** A change window with no
  `created_by` returns 500:
  ~~~
  $ POST /ops/changes {"targets":["db"],"description":"x"}  ->  500
  sqlite3.IntegrityError: NOT NULL constraint failed: ops_changes.created_by
    at core.py:90 (open_change) via app.py:108
  ~~~
  `ChangeIn.created_by` is optional (`app.py:45`) and the fallback
  `change.get("created_by", authenticated_as or "unknown")` (`core.py:94`) never fires on an
  explicit `None`, so the route advertises an optional field and then crashes on its absence.

**Why it matters.** The file implementing the product's most defensible decision is the least
covered module in the engine, and a documented HTTP call already 500s on the deployed-path code. Any
refactor of the CCB is a blind change.

**Acceptance**

- **AC-4a** — a test asserts `POST /ops/changes` without `created_by` returns 201 (with
  `created_by` = the authenticated principal) or 422, never 500. Red today.
- **AC-4b** — `cd corvus-v2 && .venv/bin/python -m pytest tests/test_app.py --cov=corvus.app
  --cov-fail-under=90` exits 0, with one test per route decorator (7), a 401 for each protected
  route, and one SSE test that reads the first event off the stream.

**Depends on** nothing. Unblocks GB-1b (server fixture), GB-3 (a tested surface) and GB-2's HTTP half.

### GB-5 — The live capture store is an `emptyDir` on a `Recreate` deployment

**Blocks** graded autonomy (3) and the evidence half of change control (1). **P1**'s gate clause
"the capture store records full-schema decisions"; **P3**'s flip gate reads observe-era records.

**Evidence**

- `kubectl -n corvus get deploy corvus-engine -o jsonpath='{.spec.template.spec.volumes}'` →
  `[{"configMap":…"name":"corvus-register"},{"emptyDir":{"sizeLimit":"1Gi"},"name":"capture"}]`;
  `kubectl -n corvus get pvc` → "No resources found".
- `CORVUS_CAPTURE_DB=/data/capture.db` on that volume (same `jsonpath`,
  `.containers[0].env`).
- `strategy: {"type":"Recreate"}` — every rollout replaces the pod, so the decision records and the
  replay index are discarded on each deploy, not only on a crash.
- The code is not the problem: `CaptureStore` opens a real SQLite file with
  `PRAGMA journal_mode=WAL` (`capture.py:36-37`) and persists the replay table
  (`capture.py:45-47`). The docstring's "a restart does not wipe the replay"
  (`capture.py:15-17`) is true for a process restart and false for a pod replacement.
- The design classes this store as **telemetry** — "best-effort", "poison-tolerant"
  (`docs/canonical-path/ENGINE-DESIGN.md:78`) — and relocates audit truth to "Corvus's decision
  records" (`TRACEABILITY.md:19`). That workload does not exist (GB-3), so the store is carrying
  audit weight it was not designed to carry, on a volume that dies.
- The operator signal the design names — `capture_dropped` (`OPS-READINESS.md:36`) — has no
  exporter: `grep -n 'metrics\|dropped' corvus-v2/corvus/engine_shim.py` → no match, and
  `CaptureStore.dropped` is an in-process integer (`capture.py:34`).

**Why it matters.** A replay window and an audit trail that both die on every deploy cannot support
the claim "the capture store records full-schema decisions", and there is no metric to notice the
loss.

**Acceptance**

- **AC-5a** — durability: `kubectl -n corvus get deploy corvus-engine
  -o jsonpath='{.spec.template.spec.volumes[*].persistentVolumeClaim}'` is non-empty, and the
  pod-replacement test passes: record a decision with a known `idempotency_key`, delete the pod,
  re-post the same key, and the returned `decision_id` equals the first one.
- **AC-5b** — observability: `curl -sS <engine>/metrics | grep '^corvus_capture_dropped_total'`
  returns a series (so the named alert can fire), or the alert is removed from the docs.
- AC-5a is APPROVE+IMPACT tier on a live target (it deletes a pod and asserts on its data).

**Depends on** GB-3 for the full fix (the attested half belongs to the second workload); the volume
change alone closes the replay half.

### GB-6 — OCSF/SIEM is absent from v2

**Blocks** shared awareness (capability 2) — the "structured event stream (OCSF 1.3.0)" is the
capability. Next needed by **P2** (the fabric) and **P3** ("the Splunk app validated against the
rebuilt OCSF events").

**Evidence**

- `grep -rniE 'splunk|\bsiem\b|ocsf' corvus-v2/corvus/ --include=*.py` → one line, a docstring
  (`corvus-v2/corvus/core.py:5`). No transformer, no forwarder, no sink config.
- The event row has no OCSF field: `ops_events` is
  `(id, hlc_timestamp, timestamp, source, type, target, severity, data, related_change_id,
  authenticated_as, signature)` (`corvus-v2/corvus/state.py:34-46`) — no `class_uid`, no
  `metadata`.
- The consumer side is real and waiting: `corvus-splunk/default/macros.conf` indexes
  `sourcetype="corvus:ocsf"` and filters on `class_uid`.
- The producer that used to exist is on `v1-archive`: `corvus-server/src/ocsf.py` and
  `corvus-server/src/siem/splunk.py` (verified with `git ls-tree --name-only v1-archive --
  corvus-server/src/`); `ls corvus-server/src` on this branch → "No such file or directory".

**Why it matters.** The SIEM edge, the Splunk app and the "forwarded to the fleet's SIEM" product
claim are all unverifiable without a producer, and the alert that watches forwarding
(`prometheus-alerts.yml:10`) watches a series that cannot exist.

**Acceptance**

- A test posts an event and asserts the forwarder emits one OCSF 1.3.0 envelope to a stub sink:
  `class_uid` matches the event type's mapping, `metadata.version == "1.3.0"`, and the event's
  `target`/`severity` survive. Runnable: `pytest tests/test_ocsf_forward.py -q`.
- The count is exact: one sink line per emitted event
  (`len(sink.lines) == len(events)`), so a dropped forward is a red test, not a missing log line.

**Depends on** a sink decision (which SIEM, which credential shape). Nothing in the repo blocks it.

### GB-7 — No lockfiles: the tested resolve is not the installed one

**Blocks** no capability gate directly; it blocks **P3**'s "a fresh fleet can onboard from the docs
alone" and the harness's own reproducibility claim.

**Evidence**

- `find . -maxdepth 3 \( -name 'poetry.lock' -o -name 'uv.lock' -o -name 'requirements*.lock' -o
  -name 'Pipfile.lock' -o -name 'pdm.lock' \) -not -path '*/.venv/*' | wc -l` → `0`.
- The dependency sets are floors with major caps: `corvus-v2/requirements.txt`
  (`fastapi>=0.162,<1.0`, `uvicorn>=0.54,<1.0`, `pyyaml>=6.0.3,<7.0`, `pydantic>=2.14,<3.0`)
  and `corvus-sdk/pyproject.toml` (`httpx>=0.28,<1.0`) — two installs inside the same range can
  resolve differently.
- The one pinned tool is ruff (`ruff==0.17.1`, `corvus-v2/Makefile:19`), which is deliberate.

**Why it matters.** "Run `make cycle`" reproduces the gate only if it installs the same versions the
gate was green on; today green is evidence about that day's resolve, not about the commit.

**Acceptance**

- One lockfile per live component (`corvus-v2`, `corvus-sdk`, `corvus-cli`), installed with the
  frozen flag so an unlocked change cannot install: `uv lock --check` exits 0 for each component in
  a clean checkout, and `git status --porcelain` after `make setup` is empty (the lock is the only
  record of the resolve).

**Depends on** nothing, but the install path changes in every component's `setup` target, so it
should land with the next dependency change rather than on its own.

### GB-8 — The mutation runner rewrites the working tree and cannot tell a kill from a crash

**Blocks** the P1 gate's own instrument: "the conformance suite runs green in CI with the mutation
evidence". A green whose evidence is unsound ends the search.

**Evidence**

- The runner reads the file (`conformance.py:80`), writes the mutant into it
  (`conformance.py:87`), and restores it in a `finally` (`conformance.py:98`).
  `REPO = Path(__file__).parent.parent.parent` (`conformance.py:38`) — the real checkout, despite
  the docstring's "WORK COPY" (`conformance.py:69`).
- A kill between :87 and :98 (SIGKILL, OOM, a cancelled CI job, a laptop that sleeps and loses the
  process) leaves the mutant in the tree. `make mutation` is also unsafe to run while anyone edits.
- The kill test is `caught = proc.returncode != 0` (`conformance.py:92`): a collection error, an
  import failure or a full-disk crash counts as a caught mutant. The red test is recorded
  (`_extract_red_test`, `conformance.py:104`) but never compared to an expectation, and a crash
  yields `suite-level` — indistinguishable from a kill in the evidence.
- It is in CI (`ci-v2.yaml:60-63`) and green (run 40059341183), so the weakness is live, not
  theoretical.

**Why it matters.** The gate's evidence is produced by a runner that can corrupt the tree it
measures and can credit a crash as a kill — the exact vacuity the mutation matrix exists to prevent.

**Acceptance**

- The runner mutates a throwaway copy (`tmp_path` or `git worktree add`): after `make mutation`
  on a clean tree, `git status --porcelain` is empty, and on a tree with an unrelated edit that
  edit is byte-identical afterwards.
- Each mutant declares its expected red test and the run fails when the observed red test differs or
  is `suite-level`. Runnable: `make mutation` exits 0 with 4/4 caught, and changing one
  `expect_red` to a wrong name makes it exit non-zero.

**Depends on** nothing.

### GB-9 — The contract tests share a fixed port and never stop their servers

**Blocks** the P1 gate's wire fixtures, and any parallel run of the suite.

**Evidence**

- `SHIM_PORT = 8934` (`corvus-v2/tests/test_decision_contract.py:24`), used by every helper in
  the file.
- The `shim` fixture starts uvicorn in a daemon thread and yields with no teardown
  (`test_decision_contract.py:32-45`): nothing sets `should_exit`, nothing joins the thread, so
  every test requesting `shim` starts another server on the same port.
- The run emits `PytestUnhandledThreadExceptionWarning` for uvicorn startup `SystemExit: 3` and
  still passes because an earlier server is listening — a green that proves a *previous* server
  answered.
- The same defect class already bit CI once on the conformance target (fixed 8933,
  `pkill -f` matching the recipe's own shell; documented in `corvus-v2/Makefile`, CI run
  40058979560).

**Why it matters.** A test that silently talks to a stale server reports on code that may no longer
exist, and the fixed port makes the suite unsafe to run twice at once.

**Acceptance**

- No fixed port: `grep -rn '8934' corvus-v2/` → no match; each fixture binds port 0 and its
  teardown stops the server (`server.should_exit = True` plus `join`, or a subprocess killed by
  PID).
- Two concurrent runs both pass:
  `(cd corvus-v2 && pytest tests/test_decision_contract.py -q) & (cd corvus-v2 && pytest
  tests/test_decision_contract.py -q) & wait` → both exit 0.
- The warning is an error: `pytest tests/ -q -W error::pytest.PytestUnhandledThreadExceptionWarning`
  → 0 warnings.

**Depends on** nothing. Do it before GB-1b copies the fixture.

### GB-10 — The alert file names metrics nothing emits

Found while re-running the review's instruments; outside its list.

**Blocks** shared awareness (capability 2) at the operator's surface, and **P2**'s quiet strip and
deadmen, which are built on these series.

**Evidence**

- `prometheus-alerts.yml` defines 9 alerts over `corvus_siem_forwarded_failure_total`,
  `corvus_graph_connections`, `corvus_events_dropped_total`, `up{job="corvus"}`,
  `corvus_triage_duration_seconds_bucket`, `corvus_gaps_open_total`, `corvus_requests_total`,
  `corvus_changes_expiring_soon`, `corvus_sse_subscriptions`
  (`prometheus-alerts.yml:10-93`).
- v2 exports none of them: `grep -rn 'metrics' corvus-v2/corvus/` finds a registry in
  `ops.py:9` used only by `observe.py:27-55` (not reachable from either entrypoint — review
  §3.2), and `engine_shim.py` has no metrics route (`grep -n 'metrics'` → no match).
- Nothing deploys the file: `grep -rn 'prometheus-alerts' .` → no match.

**Why it matters.** The alert file reads as monitoring coverage. With no series behind it every
expression evaluates to no data and no alert can fire — including the ones the design relies on for
the deadmen.

**Acceptance**

- An engine metrics endpoint exposes the counters the alerts name (or the alerts are regenerated
  from the exported set). Runnable: `curl -sS <engine>/metrics | grep -cE
  '^(corvus_events_dropped_total|corvus_requests_total|corvus_sse_subscriptions)'` → 3, and a
  script comparing the alert file's `expr` metric names against the exported set reds on a missing
  one (`promtool check rules prometheus-alerts.yml` plus that comparison in CI).

**Depends on** GB-3 (an exporter needs a serving process) and GB-6 (the SIEM counter).

## 3. The order

### 3.1 The next gate, clause by clause

The next capability gate is **P1** (`BUILD-PLAN.md:37-39`). Its three clauses, against what this
branch shows:

| P1 gate clause | What the code and the live system show | Status |
|---|---|---|
| C1 answers live traffic in observe mode | the shim answers `/decide`; observe mode is `observe.py`, not reachable from either entrypoint (review §3.2); the only real adapter is out of repo (review §7.4) | partial, and unprovable from the repo |
| the capture store records full-schema decisions | WP5's dual-precision tests pass; the deployed store is an `emptyDir` on a `Recreate` deployment | true in code, false across a deploy (GB-5) |
| the conformance suite runs green in CI with the mutation evidence | `ci-v2.yaml:45-63`; run 40059341183 `phase-gates` green; log: 4/4 mutants caught, conformance 2 passed / 0 failed | met — with a two-check corpus and a kill test that counts a crash as a kill (GB-8) |

The gate is therefore not "not started": one clause is met with a weak instrument, one is met in
code and false in the deployment, and one is not on the deployed path. The order below follows from
that, not from effort.

### 3.2 The sequence

| # | Entry | Why it sits here |
|---|---|---|
| 1 | **GB-4** | The only entry that unblocks three others (GB-1b's server fixture, GB-3's tested surface, GB-2's HTTP half) and is purely additive. Its first test is already red on a real 500, so it starts as a bug fix. |
| 2 | **GB-9** | Fix the fixture pattern before GB-1b copies it. A parity test built on a stale server would inherit the exact defect it exists to catch. |
| 3 | **GB-2** | Capability 3's only missing piece is the writer; the read path is proven, so the change is small and the acceptance is decisive. It is the P1 deliverable most likely to be declared done while doing nothing. |
| 4 | **GB-1** | Needs the fixture from 1 and the pattern from 2. The machine-checked count (AC-1a) is the part that stops the drift; the reduce-vs-implement call on 27 paths is a product decision that AC-1a makes visible instead of urgent. |
| 5 | **GB-8** | It is the instrument behind the one gate clause already green. A vacuous green is worse than a missing one because it ends the search. |
| 6 | **GB-5** | The volume change lives in the estate repo, so the in-repo half (the dropped counter and the durability test) ships first; the pod-replacement check is APPROVE+IMPACT on a live target. |
| 7 | **GB-3** | The largest change, and it depends on 1 (a tested surface) and lands GB-5's attested half. Do not deploy an untested CCB. |
| 8 | **GB-6** | Capability 2's wire. Needs a sink decision, and it is what makes the Splunk app validatable at P3. |
| 9 | **GB-10** | Follows 8 (the SIEM counter) and 7 (a process to export from); it is the operator's view of both. |
| 10 | **GB-7** | Independent of every gate; it belongs in the change that next touches a dependency, so the lock and the change land together rather than as a standalone churn. |

Two entries are deliberately not early: **GB-3** because deploying an untested surface trades one
unprovable claim for another, and **GB-6** because a SIEM producer with no sink is a forwarder that
drops silently — the same "green that proves nothing" shape this backlog exists to remove.

### 3.3 The first increment

**GB-4: a pytest suite for `corvus-v2/corvus/app.py`.**

One new file (`corvus-v2/tests/test_app.py`) and one fixture in `tests/conftest.py`:

- The fixture builds the app the way production does —
  `create_app(config=FleetConfig(name="test-fleet", node_id="test-1", api_key="test-key"),
  db_path=str(tmp_path / "corvus.db"))` (`app.py:58`) — serves it on **port 0** with a stoppable
  `uvicorn.Server`, and stops it in teardown.
- Seven route tests (one per decorator), a 401 test per protected route, one SSE test that reads the
  first event off the stream, and **AC-4a**: `POST /ops/changes` with no `created_by` returns
  201 with the authenticated principal (or 422) — never 500.

**Why this one.** It is the smallest change that converts the largest untested surface into a gate;
it needs no new dependency (`httpx` and `uvicorn` are already in the v2 venv, and the fixture is
the pattern GB-1b and GB-3 both need); and it pays immediately, because the route it tests is
broken today — the 500 at `core.py:94` is a real defect on the product's core call, not a coverage
number.

The two file changes are disjoint from every other entry, so this increment can land alone.

## 4. What I could not verify

- **The deployed engine's loaded register and capture-DB contents.** I read the deployment spec
  (read-only `kubectl -n corvus get deploy … -o jsonpath`) and did not exec into the pod; the
  review reports that `kubectl exec` is blocked by the session guardrails, and I did not attempt it.
- **That the live capture store actually loses rows on a pod replacement.** Inferred from the
  manifest (`emptyDir` + `Recreate`), not observed: I did not delete a pod or POST to the live
  engine (a decision POST writes to the capture store).
- **The deployed engine's behavior at `be0ba58`.** The live image is `2191155`; my parity probes
  ran against a locally started `create_app()`, not the live service.
- **The CLI's behavior against the deployed artifact.** My CLI probe ran against a locally started
  `app.py` (404 / 401, quoted in GB-1); I did not run the CLI against the live service, which
  serves neither client's paths anyway.
- **`make mutation` on this worktree.** I read the runner's code path but did not execute it: it
  rewrites `corvus-v2/corvus/decision_core.py` in the real tree, and this session shares the
  worktree's filesystem with other agents. The CI log is the evidence that it runs and catches 4/4.
- **The Splunk app in a real Splunk.** No instance available; the consumer-side claim is read from
  `corvus-splunk/default/macros.conf` only.
- **Whether the alert file is deployed anywhere.** `grep -rn 'prometheus-alerts' .` finds no
  reference; a cluster-side check would need the monitoring stack, which I did not query.
