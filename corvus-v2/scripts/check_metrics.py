#!/usr/bin/env python3
"""The metrics drift guard: the committed dev-metrics.json must match a fresh
run. A stale file fails the gate — the mutation-provable control that keeps
the metrics honest (the mutation: stale the file → the gate must red)."""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expected", required=True)
    ap.add_argument("--actual", required=True)
    ap.add_argument("--tolerance", type=float, default=1.5,
                    help="the coverage percent tolerance (the python-version variance: the "
                         "local 3.15 vs the CI 3.12 count statements slightly differently)")
    args = ap.parse_args()

    expected = json.loads(Path(args.expected).read_text())
    actual = json.loads(Path(args.actual).read_text())

    # The source_commit is INFORMATIONAL (every commit changes the HEAD sha,
    # so gating on it is structurally unsatisfiable — caught live by this
    # guard's own first CI run). The MEASURABLE facts gate.
    drifts = []
    ec = expected.get("coverage", {}).get("percent")
    ac = actual.get("coverage", {}).get("percent")
    if ec is None or ac is None or abs((ac or 0) - (ec or 0)) > args.tolerance:
        drifts.append(f"coverage percent: {ec} != {ac}")
    et = expected.get("coverage", {}).get("lines_total")
    at = actual.get("coverage", {}).get("lines_total")
    if et is not None and at is not None and abs(at - et) > 6:
        drifts.append(f"lines_total: {et} != {at} (beyond the interpreter variance)")

    if drifts:
        print("METRICS DRIFT — the committed dev-metrics.json is stale:")
        for d in drifts:
            print("  ", d)
        print("Run `make metrics` and commit the refreshed file.")
        sys.exit(1)
    print("metrics: fresh (no drift)")


if __name__ == "__main__":
    main()
