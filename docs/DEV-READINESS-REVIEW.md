# Dev Readiness Review — the plan against what the harness can prove

**Baseline**: worktree `corvus-dev`, branch `harness/per-component`, HEAD `2191155` (= `origin/main`).
**Interpreter**: `python3 --version` → 3.15.0; `python3.12 --version` → 3.12.15. Every component
harness pins 3.12; CI uses 3.12.
**Method**: every current-state claim names its instrument — a `file:line`, a command with its real
output, or a live probe. Claims I could not verify are listed in §8, not softened into the prose.
Numbers below are from my own runs on this worktree unless a different instrument is named. The
repo's README and CLAUDE.md are not instruments: they describe v1 and are stale (§7.12).

## 1. Component inventory

| Component | What it is | Status | Current state — instrument |
|---|---|---|---|
| `corvus-v2` | The decision engine + the CCB spine (the single binary) | **LIVE** — deployed | 24 modules, 1,277 statements; 90 tests pass at 73.0% coverage (`make cycle`). No `pyproject.toml` (`ls corvus-v2/pyproject.toml` → absent; requirements.txt only), so `pip install -e .` is impossible. Three modules at 0% (`coverage.json` per-file list): `app.py` (78 stmts), `conformance.py` (66), `trust.py` (61). |
| `corvus-sdk` | Async Python client | **LIVE PACKAGE, v1 protocol** | 220 statements; 54 tests, 100% coverage, all against mocked HTTP (`respx`; `make cycle`). 30 `/ops` paths, **3** served by v2. |
| `corvus-cli` | typer CLI | **LIVE PACKAGE, v1 protocol** | 214 statements; 50 tests (added on this branch), 100% coverage, `MockTransport` (`make cycle`); 15 `/ops` paths, **3** served by v2; no evidence-export command. |
| `corvus-server` | v1 platform (FastAPI, CMDB, runbooks, Neo4j) | **LEGACY** — archived at `v1-archive`, not deployed | `src/` absent on this branch (`ls corvus-server/src` → No such file); `Dockerfile:35` still `COPY src/ src/`; two modules remain; 15 runbooks; 0 tests. |
| `corvus-hooks` | v1 governance hooks (CC PreToolUse/PostToolUse, 3 adapters, installer) | **LEGACY** — not deployed | stdlib scripts; default URL `http://localhost:9420` and v1 route `/ops/events/targets/{target}/status` (`corvus_core.py:28,80`); 0 tests; v1 copy archived at `~/.claude/hooks/_archive-corvus-decom-2026-05-28`. |
| `corvus-splunk` | Splunk app (4 dashboards, 11 searches, 3 lookups) | **LEGACY config** — not deployed | expects `index=corvus sourcetype="corvus:ocsf"` + `class_uid` (`default/macros.conf:4,13-29`); app version 0.1.0; 0 tests; no Splunk instance locally. |

The `Status` column carries the distinction that matters: a component can be **live as a package**
(builds, lints, tests, CI-gated) while speaking a protocol nothing serves. `corvus-cli` and
`corvus-sdk` are exactly that (§3.1).

## 2. What "live" actually is: the deployed surface

- **One workload, one container.** `kubectl -n corvus get deploy,svc,pods -o wide` → `corvus-engine`
  1/1 ready, image `harbor.themillertribe-int.org/homelab/corvus-v2:2191155`, Service
  `10.43.206.222:8933`, pod on `tmtdockp01` (1 restart 2d14h ago). `kubectl get deploy,sts,ds -A |
  grep -i corvus` returns that single line — no v1 server, no second deployment.
- **The deployed artifact is the decision engine, not the CCB.** The container sets no
  `command`/`args` (`kubectl … -o jsonpath` → `||8933`), so the image CMD runs:
  `python -m corvus.engine_shim --port 8933` (`corvus-v2/Dockerfile:21`). The shim declares exactly
  one route, `POST /v1/fleets/{fleet_id}/decide` (`corvus/engine_shim.py:111`); there is no GET
  status route, and liveness/readiness are TCP probes on 8933.
- **The CCB spine is not deployed.** `corvus/app.py` defines the event ingest, change windows and
  the conflict check (`app.py:70-119`, six paths) but no workload in this cluster serves them and
  nothing exposes a port other than 8933.
- **The register is byte-identical to HEAD.** `shasum -a 256 decision-register.yaml` →
  `7ede7637…6e368`; `kubectl -n corvus get cm corvus-register -o jsonpath='{.data.decision-register\.yaml}'
  | shasum -a 256` → the same hash. The register is 19 sites + 10 facts + 3 composition policies
  (`python3.12` + yaml: `len(sites)=19`, `len(fact_layer.facts)=10`), while its own header comment
  (`decision-register.yaml:5`) says "18 sites + 9 fact citizens".
- **The live capture store is not durable.** The deployment sets `CORVUS_CAPTURE_DB=/data/capture.db`
  on an `emptyDir` volume (`kubectl -n corvus get deploy corvus-engine -o yaml`), so the decision
  records and the replay index die with the pod. The local default (`:memory:`,
  `engine_shim.py:92`) is no better; only an explicitly configured file path persists.
- **Public reachability is real but the path is not visible from the cluster.**
  `curl -sS -o /dev/null -w '%{http_code}' https://corvus.themillertribe-int.org/` → `404`
  (the app answers); `dig +short corvus.themillertribe-int.org` → `192.168.20.230`;
  `kubectl get ingress -A` → 0 corvus matches. The hop from that address to the ClusterIP is
  outside the cluster's Ingress surface and I did not verify it.

## 3. The two seams that are broken

### 3.1 The clients speak v1; the engine serves v2

Exact string comparison of the clients' called paths against `app.py`'s route decorators
(`python3.12`, regex over the three files):

```
v2 routes: ['/health', '/ops/changes', '/ops/changes/active', '/ops/conflict-check',
            '/ops/events', '/ops/events/stream']
sdk: 30 distinct paths; exact v2 matches: 3 -> ['/ops/changes', '/ops/changes/active', '/ops/events']
cli: 15 distinct paths; exact v2 matches: 3 -> ['/ops/changes', '/ops/changes/active', '/ops/events']
```

So **27 of 30 SDK paths and 12 of 15 CLI paths are not served by v2** — `/ops/cmdb`,
`/ops/incidents`, `/ops/runbooks/*`, `/ops/graph/*`, `/ops/trust`, `/ops/gaps`, `/ops/metrics`,
`/ops/knowledge/*`, `/ops/discovery/*`, `/ops/problems`, `/ops/events/context`,
`/ops/events/targets/{t}/status`, `/ops/changes/{id}`. The same v1 routes are hard-coded in the
hooks (`corvus_core.py:80,107`) against `http://localhost:9420` (`:28`) — the v1 server's port.

Their 100% coverage is real but scoped: the SDK tests mock with `respx`, and the CLI fixture states
"No test ever opens a socket" (`corvus-cli/tests/conftest.py:3`). **No test in the repo starts a v2
server and runs a client against it.** Green here proves the client's own logic, not parity.

### 3.2 The v2 binary exercises 4 of its 24 modules

Static import reachability from the two entrypoints (`python3.12` + `ast` over `corvus/*.py`):

```
engine_shim reachable: ['canonical', 'capture', 'contract_codes', 'engine_shim']
app reachable:         ['app', 'config', 'core', 'hlc', 'state']
NOT reachable from either entrypoint: __init__, adapter, attested, cc_adapter, compiler,
  config_loader, conformance, decision_core, decisions, delivery, facts, observe, ops, tokens, trust
```

15 modules exist only for the tests or for the out-of-repo adapter. The load-bearing ones:

- **The trust ledger is unwired.** `TrustLedger` (`trust.py:52`) has no importer; nothing writes the
  `ops_trust` table (`state.py:49`) — `conflict_check` only reads it (`core.py:133`), so every live
  answer carries the default `trust_tier: "ESCALATE"`. `test_spine.py:65-68` pins that default; no
  test promotes a tier and observes it in a conflict answer. Capability 3 (graded autonomy) is not
  on the deployed path.
- **The observe mode, delivery chain, verdict tokens, decision client and conformance runner are
  not reachable from the deployed binary** — `observe.py`, `delivery.py`, `tokens.py`,
  `decisions.py`, `conformance.py`. They are tested as units (`test_observe_delivery.py`,
  `test_decision_contract.py`), never as the deployed surface.
- **`app.py` is 0% under pytest** even though it is the CCB's whole HTTP surface. The harness build
  step exercises `/health` and the auth boundary over a socket (`scripts/dev_check.py`), which is
  why the build target is meaningful — but no pytest test covers the app.
- **The P1 conformance gate is not gated.** At HEAD, `ci-v2.yaml` ran lint, tests, the metrics
  guard and a smoke job — no mutation, no conformance run. The branch's CI matrix runs each
  component's `make cycle`, which still does not include the `mutation`/`conformance` targets.
  The P1 capability gate ("the conformance suite runs green in CI with the mutation evidence") is
  therefore a manual target, not a gate.

## 4. What the dev harness proves today

Each component owns `<component>/Makefile`; the root `Makefile` runs every component's `cycle`.

| Component | Targets | Evidence from my run | What it cannot prove |
|---|---|---|---|
| `corvus-v2` | setup build lint test fix metrics metrics-check run check cycle mutation conformance clean | `make cycle`: "build: ok — dev-fleet / health + authenticated read + 401 control"; "All checks passed!"; "90 passed, 13 warnings in 15.94s"; "TOTAL 1277 345 73%"; "metrics: fresh (no drift) — 90 tests, 73.0% coverage, 1277 statements" | the deployed decision path; `app.py` under pytest; the mutation/conformance gates (manual, not in cycle/CI) |
| `corvus-sdk` | setup build lint test fix cycle clean | `make cycle`: "build: ok — 0.1.0"; "All checks passed!"; "54 passed in 0.33s"; "TOTAL 220 0 100%" | parity with v2 — every request is mocked |
| `corvus-cli` | setup build lint test fix cycle clean | `make cycle`: "import: ok"; "`corvus --help`" and "`corvus check-target --help`" exit 0; "All checks passed!"; "50 passed in 0.72s"; "TOTAL 214 0 100%" | parity with v2; any command that reads decisions/capture/audit evidence |
| `corvus-server` | setup lint import fix cycle clean | `make cycle`: "All checks passed!"; "import: ok on 3.12.15 — soc2 APIRouter(3 routes), typer app 'corvus' (11 commands)" | anything behavioral: no tests, no runnable app |
| `corvus-hooks` | setup lint import fix cycle clean | `make cycle`: "All checks passed!"; "import: byte-compiled 8 scripts"; "import: ok — corvus_core imported, public API present" | that the hooks work against any server (they target v1 routes) |
| `corvus-splunk` | setup validate cycle clean | `make cycle`: "validate: ok — 6 conf, 5 xml, 3 csv, 1 py" | that Splunk accepts the app, that the SPL is valid, that the dashboards render |

Two contract deviations, stated plainly: `corvus-v2` has no `pyproject.toml`, so its `build` is a
live-socket proof instead of `pip install -e .`; and the three legacy components replace
`build`/`test` with `import`/`validate` because there is no installable package and no suite.

Consequence for the umbrella, and its fix: the root's `build`/`lint`/`test`/`fix` first looped
over all six components and aborted at the first one lacking the target
(`make -C corvus-hooks test` → "No rule to make target 'test'"; `make -C corvus-splunk build` →
same, and splunk has no `lint` or `fix` either). The root Makefile now declares per-target
component lists — `LIVE` (the three with build/test), `PY` (the five that lint and autofix), and
`ALL` (setup/cycle/clean) — so every root target resolves. Verified on this worktree: `make lint`,
`make build`, `make test` and `make fix` all exit 0, and `make fix` on the clean tree leaves
`git status` byte-identical (it is idempotent). `make check` is an alias for `make cycle`.

## 5. Plan mapping — the phase that needs each component next

| Component | Phase | What the plan needs | What the harness proves | The gap |
|---|---|---|---|---|
| `corvus-v2` | **P1** (then P2/P3) | C1 answers live traffic in observe mode; the capture store records full-schema decisions; the conformance suite runs green in CI with mutation evidence | the engine contract (15 wire tests), 90 unit tests, a live health/auth proof | trust ledger unwired; observe/delivery/tokens not on the deployed path; capture ephemeral live; conformance/mutation not in CI; `app.py` 0% under pytest |
| `corvus-sdk` | **P3** | "the SDK reduced to the documented HTTP contract (any language)" | 54 mocked tests at 100% | v1 protocol: 27/30 paths unserved; no real-server test |
| `corvus-cli` | **P5** | "the audit CLI's evidence export" | 50 mocked tests at 100%, entrypoint dispatch | v1 protocol; no decision/audit/evidence commands exist |
| `corvus-server` | **P2** (+P4) | the runbook schema + validation gate; the knowledge base; blind-spot detection "ported from the old implementation where the concept survives review" | lint + import of the two remaining modules | `src/` is in `v1-archive`; 15 runbooks with no schema gate; 78 archived test files / 746 test functions that cannot run on this branch |
| `corvus-hooks` | **P1** | ADR-004's adapter contract, its conformance suite, and the first two real adapters | lint + byte-compile + `corvus_core` import | v1 routes; no adapter-conformance fixture; the one real v2 adapter is outside the repo (§7.4) |
| `corvus-splunk` | **P3** | "The Splunk app validated against the rebuilt OCSF events" | config/XML/CSV parse + cross-reference validation | v2 emits no OCSF and forwards nothing to a SIEM (§7.6) |

**THE acceptance gate is untestable today.** "A new harness reaches full governance parity by
shipping only an adapter" needs a fixture that runs an adapter against the engine and checks the
four capabilities. The repo has the engine's wire conformance (`conformance.py:111`) and unit tests
for the CC adapter with a stub client (`test_cc_adapter.py`), but no adapter-conformance harness.

## 6. The metrics guard: the drift it could not see

```
committed at HEAD (git show HEAD:docs/canonical-path/dev-metrics.json): 108 tests, 79.1%, 1274 lines, source dabbda4
my fresh run (make cycle):                                              90 tests, 73.0%, 1277 lines, source 2191155
```

At HEAD the guard compared only coverage percent (tolerance 7.0) and `lines_total` (tolerance 6)
(`git diff corvus-v2/scripts/check_metrics.py` shows the removed code); 108-vs-90 tests was
invisible to it. On this branch the guard gates the test count exactly and coverage to 1.0 point
with 0-statement tolerance — my `make cycle` above passes the tightened gate.

## 7. Blind spots — what a developer cannot verify locally

1. **The deployed decision path has no test.** `app.py` is 0% under pytest; the deployed shim's only
   route is `POST /decide`, so even a live smoke check writes to the capture store.
2. **The live capture store is ephemeral** (`emptyDir`): the audit trail does not survive a pod
   restart, and no local run can prove otherwise for the deployment.
3. **Client↔engine parity is unproven**: no test starts a v2 server and drives a client at it.
4. **The only real adapter is out of repo.** `~/.claude/hooks/corvus-v2-observe.py` (wired at
   `~/.claude/settings.json:119`) imports `corvus` from a different worktree
   (`/Users/tmiller/worktrees/corvus-canonical/corvus-v2`) and defaults to the deployed URL. Its
   chain DB `~/.corvus-v2/chain.db` has mtime 2026-10-19T15:17 (12,288 bytes) — the local evidence
   store has not recorded since. Nothing in the repo exercises it.
5. **The acceptance gate has no fixture** (§5), so "parity by adapter alone" is a claim, not a check.
6. **OCSF/SIEM is absent from v2.** `grep -rniE 'splunk|\bsiem\b|ocsf' corvus-v2/corvus/ --include=*.py`
   → one docstring line (`core.py:5`). PRODUCT capability 2's "OCSF 1.3.0" stream and the Splunk
   app's consumer side cannot be validated locally.
7. **No lockfiles anywhere** (`find . -maxdepth 3 \( -name 'poetry.lock' -o -name 'uv.lock' -o -name
   'requirements*.lock' -o -name 'Pipfile.lock' -o -name 'pdm.lock' \) -not -path '*/.venv/*'` → none).
   Dependency floors are `>=`; a fresh resolve today equals the current latest (Lead's PyPI query,
   2026-10-24T03:30Z, corroborated by `.venv` `pip list`: fastapi 0.162.0, uvicorn 0.54.0,
   pydantic 2.14.1, pyyaml 6.0.3), but nothing pins that resolve — the only pin is the toolchain
   (`ruff==0.17.1`, deliberate; latest is 0.17.2). Reproducibility rests on CI going red after a
   break, not on a pinned set. The legacy server's floors are majors behind
   (`corvus-server/requirements.txt`: `neo4j>=5.20.0`, `mcp>=1.0.0`; latest 6.4.1 and 2.3.0 per the
   Lead's query), and it caps `pytest-asyncio>=0.25.0,<1.0.0`.
8. **The mutation runner rewrites the working tree.** `run_mutation_suite` writes the mutant and
   restores it (`conformance.py:87,98`); a kill between the two leaves a mutated repo. It is not in
   CI and is unsafe to run concurrently with anyone editing.
9. **The contract tests share a fixed port.** Each `shim` fixture starts uvicorn on 8934 and never
   stops it; my run emits repeated `PytestUnhandledThreadExceptionWarning` (Thread-2…6, uvicorn
   startup `SystemExit: 3`) and still passes because an earlier server is listening. Parallel runs
   or a busy port collide. The `conformance` make target had the same class of defect and it bit
   CI: it bound a fixed 8933 and cleaned up with `pkill -f "engine_shim --port 8933"`, which also
   matched the recipe's own shell, so the run passed 2/0 while make reported "Terminated" and
   exited 2 (CI run 40058979560). It now binds an ephemeral port and kills the shim by PID.
10. **This host runs a launchd-managed engine on the conformance port.** `launchctl list` shows
    `com.themillertribe.corvus-v2-engine` (PID 66272, `-m corvus.engine_shim --port 8933 --host
    127.0.0.1`, cwd `/Users/tmiller/worktrees/corvus-canonical/corvus-v2`, python 3.15) holding
    127.0.0.1:8933. It restarts when killed (parent PID 1). A local `make conformance` against a
    fixed 8933 was therefore testing THAT process, not this worktree's code — a green local result
    that proved nothing. The ephemeral port fixes the harness; the agent itself is outside this
    repo and was not touched.
10. **The deployed register load is inferred, not observed.** The mount is proven (hash match), and
    `engine_shim.py:66-80` is the path ladder, but I could not read the running process's loaded
    register: `kubectl exec` is blocked by the session's guardrails (a DDR is required for that
    target), and I did not author one.
11. **The public route is unverified** (§2): DNS resolves to a LAN address; there is no Ingress.
12. **The repo's own docs are stale instruments.** `CLAUDE.md` documents `corvus-server/src/app.py`,
    `routers/`, `middleware/` (absent: `ls corvus-server/src` fails), a 12-runbook count (15 on
    disk: `ls corvus-server/runbooks/*.yaml | wc -l`), and a `docker run … ghcr.io/…/corvus:latest`
    deployment (the live image is `harbor…/corvus-v2:2191155` on 8933). README describes the v1 box.

## 8. Claims I could not verify

- That the deployed engine actually **loaded** the mounted register (mount hash proven; load not).
- The live capture DB's contents, row count, or persistence across a restart (`kubectl exec` blocked).
- SDK/CLI behavior against a **real** v2 server (not attempted; static route comparison is the
  instrument used instead).
- The v1 hooks' runtime behavior (no tests, not deployed, and their target routes do not exist in v2).
- The Splunk app in a real Splunk (no instance available): acceptance, SPL validity, rendering.
- The deployed engine's latency, availability, or behavior under load (no load instrument here).
- Whether the out-of-repo CC adapter currently works end-to-end (its chain DB is stale; running it
  would POST a decision to the live engine, which I did not do).
