# The Continuous-Improvement Loop — how the harness improves itself

The harness is not just a gate: it is the environment the product improves
inside. This document is the loop's operating manual.

## The metrics are the loop's instrument

`docs/canonical-path/dev-metrics.json` is committed with every change; its
git history IS the trend. At any point:

```bash
git log --oneline -- docs/canonical-path/dev-metrics.json   # the measurement points
git show <sha>:docs/canonical-path/dev-metrics.json         # any point's numbers
```

The first-class measures: the test count, the coverage percent, the
coverage lines, the source commit. The cycle time and the flake rate are
derivable from the git history and the Actions runs respectively.

## The review cadence (per phase gate)

At each roadmap phase gate (P1→P2, P2→P3, …), before the phase flips:

1. **The trend read**: the metrics file's history since the last gate —
   the coverage direction, the test-count growth, the surprising jumps.
2. **The regression check**: any coverage drop >3% across the phase, any
   test count decline, any flake pattern in the Actions reruns → the
   finding, dispositioned like an adversarial finding (fixed or
   accepted-with-reason, in this doc's successor or the phase report).
3. **The harness self-review**: the gates that never fired since the last
   gate are suspect (a guard that never fires is decoration — the
   mutation control re-run proves it can still fail).

## The improvement rules

- **A red required check is an opportunity to FIX, not to bypass** — the
  estate's standing principle. The bypass path exists (the admin merge)
  and is auditable; using it for convenience erodes the harness.
- **Every new guard ships with its mutation control** — the proof it can
  fail. The drift guard proved itself live twice (the sha-gate design
  flaw, the interpreter variance); that is the standard.
- **The adversarial review re-runs at every phase gate** on whatever the
  harness grew — the new jobs, the new guards, the new metrics.
- **The tolerance changes are documented changes** — the drift guard's
  ±1.5%/±6 lines exist for the interpreter variance (3.15 local vs 3.12
  CI); tightening or loosening them names the reason in the commit.

## The current baseline (2026-10-18)

- 10 tests, 55.5% coverage (126/227 lines) — the P1 build grows from here.
- The CI: ~35s total (the test ~16s, the smoke ~13s), every PR, no paths
  filter.
- The known gap: the coverage is measured on the v2 spine only; the
  components' real tests arrive with their P-phase rebuilds.
