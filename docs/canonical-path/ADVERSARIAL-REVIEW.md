# The Dev-Test Harness's Adversarial Review — the findings and their disposition

**The machinery**: the estate's adversarial-review multi-perspective loop
(22 findings: 5 high / 9 medium / 8 low, deduplicated to five themes) over
the harness's own artifacts — the CI workflows, the drift guard, the
metrics generator, the Makefile, the branch protection, the auth model.
**Date**: 2026-10-18. **The rule**: every finding fixed or explicitly
accepted-with-reason.

## FIXED (in this branch)

1. **The CI paths-filter blind spot (high, four perspectives)** — a PR
   touching only `corvus-sdk` or the Makefile got ZERO CI: the
   workflow-level paths filter gated both jobs, so the smoke never ran for
   the out-of-scope changes. **The fix**: the paths filter removed; every
   PR and main push runs everything (the test ~16s, the smoke ~13s — the
   always-run cost is trivial). The workflow_dispatch stays as the manual
   re-run lever.

2. **The dev-key fallback (high, three perspectives)** — the env fallback
   `dev-key-change-me` meant a misconfigured production deploy started
   silently insecure: a known key authenticating everything. **The fix**:
   the config is fail-closed — no explicit `CORVUS_API_KEY`, no start
   (the ValueError names the reason). The module-level app instance was
   removed with it: the import must be side-effect-free, or the
   fail-closed config breaks every import.

3. **The smoke's compile-only inadequacy (medium, four perspectives)** —
   `py_compile` checks syntax, not imports: the circular imports and the
   missing deps passed the smoke. **The fix**: the smoke does the editable
   installs (`pip install -e ./corvus-cli ./corvus-sdk`, which pull the
   declared deps) and imports the PACKAGES — what a consumer experiences.

4. **The lint verdict flip-flop (medium, found live)** — the local ruff
   0.17.1 and the CI's latest disagreed on the isort grouping, whipsawing
   the required check across pushes. **The fix**: the repo's
   `pyproject.toml` (`known-first-party = ["corvus"]`) + the ruff pinned
   0.17.1 in the CI — both verdicts deterministic.

5. **The gen_metrics' input validation (low)** — the missing/malformed
   coverage.json produced silent garbage. **The fix**: the explicit
   validation (the missing file, the invalid JSON, the missing
   totals.percent_covered each fail loudly).

## ACCEPTED-WITH-REASON

6. **`enforce_admins=false` (medium, four findings)** — the admins can
   bypass the required check. **The reason**: this is the operator's
   delegated-merge design — the bot's autonomous merges under the
   operator's standing authorization ride the admin bypass, and every such
   merge is recorded (the PR, the review, the sha). Setting it true would
   break the autonomous loop the operator built. The bypass is auditable;
   the review requirement stays for humans.

7. **The drift guard's tolerance (medium, three findings)** — ±1.5% could
   mask the gradual erosion. **The reason**: the two-layer design — the
   guard catches the big movements (the dropped suites, the stale file);
   the *gradual* erosion is visible in the version-controlled metrics
   file's git history, which IS the trend. The ratchet suggestion is
   noted for P1+ if the trend review shows erosion; the interpreter
   variance (3.15 local vs 3.12 CI) makes a strict ratchet fragile today.

8. **The Makefile's check speed (low)** — moot at the current scale: the
   suite runs in 0.2s. Revisit if the suite exceeds ~30s.

9. **The metrics schema versioning (low)** — already addressed: the file
   carries `"schema": 1`; the schema is documented in gen_metrics.py's
   docstring.

## The can-fail proofs (the review's prerequisite — both verdicts recorded)

- **The red**: the deliberately-broken assertion turned the required
  `test` check RED (the run 39162136821, PR #44).
- **The green**: the restored assertion turned it GREEN (the runs at
  9bf0a9e). The synchronize-quirk workaround discovered en route: the
  workflow-file change re-triggers the paths-filtered CI; the
  workflow_dispatch is the durable lever.
- **The collection proof**: the planted test PASSED in CI — 11 passed
  (the run 39163690110, PR #45). The gate collects new tests.

Both throwaway PRs (#44, #45) deleted after the verdicts, per the
constraint.
