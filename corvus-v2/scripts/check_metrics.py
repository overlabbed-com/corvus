#!/usr/bin/env python3
"""The metrics drift guard: the committed dev-metrics.json must match a fresh run.

A stale file fails the gate — the mutation-provable control that keeps the
metrics honest (the mutation: stale the file -> the gate must red).

WHAT IS GATED AND WHY THE TOLERANCES ARE WHAT THEY ARE
The interpreter is PINNED to python3.12 in the Makefile and in CI, so the
interpreter-variance that forced a 7.0-point coverage tolerance is gone. The
measured history, kept because it explains the numbers:
  2026-10-19: the same suite on 3.15 = 79.1% vs 3.12 = 72.9% -> 6.2 points apart.
  2026-10-24: pinned 3.12.15 = 73.0%, 1277 statements, 90 tests.
The 108-tests / 79.1% / 1274-lines file committed on 2026-10-19 was therefore
stale, and the OLD guard passed it: it compared only coverage percent and
lines_total, so a test-count drift of 108-vs-90 was invisible. The test count
is now gated exactly. That is the whole point of a drift guard — it must be
able to fail on the drift that actually happened.
"""
import argparse
import json
import sys
from pathlib import Path

# The interpreter is pinned (python3.12) on both sides, so these are tight.
COVERAGE_TOLERANCE = 1.0  # percentage points — rounding only, not interpreter variance
LINES_TOLERANCE = 0  # statements are deterministic for a fixed interpreter + source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True, help="the committed dev-metrics.json")
    ap.add_argument("--actual", required=True, help="the metrics from a fresh run")
    ap.add_argument("--coverage-tolerance", type=float, default=COVERAGE_TOLERANCE)
    ap.add_argument("--lines-tolerance", type=int, default=LINES_TOLERANCE)
    args = ap.parse_args()

    expected = json.loads(Path(args.expected).read_text())
    actual = json.loads(Path(args.actual).read_text())

    # source_commit is INFORMATIONAL: every commit changes the HEAD sha, so gating
    # on it is structurally unsatisfiable (caught live by this guard's first CI run).
    # The MEASURABLE facts gate.
    drifts = []

    ec = expected.get("coverage", {}).get("percent")
    ac = actual.get("coverage", {}).get("percent")
    if ec is None or ac is None or abs((ac or 0) - (ec or 0)) > args.coverage_tolerance:
        drifts.append(f"coverage percent: committed {ec} != fresh {ac} (tolerance {args.coverage_tolerance})")

    et = expected.get("coverage", {}).get("lines_total")
    at = actual.get("coverage", {}).get("lines_total")
    if et is None or at is None or abs(at - et) > args.lines_tolerance:
        drifts.append(f"lines_total: committed {et} != fresh {at} (tolerance {args.lines_tolerance})")

    # The test count is exact: it cannot vary with the interpreter, and its drift is
    # exactly the failure the old guard could not see.
    ett = expected.get("tests", {}).get("total")
    att = actual.get("tests", {}).get("total")
    if ett is None or att is None or ett != att:
        drifts.append(f"tests total: committed {ett} != fresh {att} (exact — no tolerance)")

    af = actual.get("tests", {}).get("failed")
    if af is not None and af > 0:
        drifts.append(f"the fresh run has {af} failing test(s)")

    if drifts:
        print("METRICS DRIFT — the committed dev-metrics.json is stale:")
        for d in drifts:
            print("  ", d)
        print("Run 'make test && make metrics' and commit the refreshed file.")
        sys.exit(1)

    print(f"metrics: fresh (no drift) — {att} tests, {ac}% coverage, {at} statements")


if __name__ == "__main__":
    main()
