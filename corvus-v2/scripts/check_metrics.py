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
    ap.add_argument("--tolerance", type=float, default=0.0)
    args = ap.parse_args()

    expected = json.loads(Path(args.expected).read_text())
    actual = json.loads(Path(args.actual).read_text())

    drifts = []
    if expected.get("source_commit") != actual.get("source_commit"):
        drifts.append(f"source_commit: {expected.get('source_commit')} != {actual.get('source_commit')}")
    ec = expected.get("coverage", {}).get("percent")
    ac = actual.get("coverage", {}).get("percent")
    if ec is None or ac is None or abs((ac or 0) - (ec or 0)) > args.tolerance:
        drifts.append(f"coverage percent: {ec} != {ac}")
    et = expected.get("coverage", {}).get("lines_total")
    at = actual.get("coverage", {}).get("lines_total")
    if et != at:
        drifts.append(f"lines_total: {et} != {at}")

    if drifts:
        print("METRICS DRIFT — the committed dev-metrics.json is stale:")
        for d in drifts:
            print("  ", d)
        print("Run `make metrics` and commit the refreshed file.")
        sys.exit(1)
    print("metrics: fresh (no drift)")


if __name__ == "__main__":
    main()
