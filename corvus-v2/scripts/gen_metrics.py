#!/usr/bin/env python3
"""Generate the dev-metrics artifact (docs/canonical-path/dev-metrics.json).

The metrics are first-class and version-controlled: this file is committed
with every change, and check_metrics.py guards its freshness (the drift
guard — a stale metrics file fails the CI). The file's git history IS the
trend: each commit's timestamp is the measurement time.

The schema:
{
  "schema": 1,
  "source_commit": "<short sha the measurement ran at>",
  "generated_at": "<ISO timestamp>",
  "tests": {"total": N, "passed": N, "failed": N},
  "coverage": {"percent": N.N, "lines_covered": N, "lines_total": N},
  "duration_seconds": N.N
}
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", required=True, help="the pytest-cov coverage.json")
    ap.add_argument("--junit", help="the pytest junit.xml (the real test counts)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source", required=True, help="the short sha")
    ap.add_argument("--duration", type=float, default=0.0, help="the test run's seconds")
    args = ap.parse_args()

    cov_path = Path(args.coverage)
    if not cov_path.exists():
        sys.exit(f"gen_metrics: {cov_path} missing — the coverage step must run first")
    try:
        cov = json.loads(cov_path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"gen_metrics: {cov_path} is not valid JSON: {e}")
    totals = cov.get("totals", {})
    if "percent_covered" not in totals:
        sys.exit(f"gen_metrics: {cov_path} lacks totals.percent_covered — not a pytest-cov report")
    tests = {"total": 0, "passed": 0, "failed": 0}
    if args.junit and Path(args.junit).exists():
        import xml.etree.ElementTree as ET
        root = ET.parse(args.junit).getroot()
        suite = root.find("testsuite") if root.tag == "testsuites" else root
        tests = {
            "total": int(suite.get("tests", 0)),
            "passed": int(suite.get("tests", 0)) - int(suite.get("failures", 0)) - int(suite.get("errors", 0)),
            "failed": int(suite.get("failures", 0)) + int(suite.get("errors", 0)),
        }
    metrics = {
        "schema": SCHEMA,
        "source_commit": args.source,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tests": tests,
        "coverage": {
            "percent": round(totals.get("percent_covered", 0.0), 1),
            "lines_covered": totals.get("covered_lines", 0),
            "lines_total": totals.get("num_statements", 0),
        },
        "duration_seconds": args.duration,
    }
    Path(args.out).write_text(json.dumps(metrics, indent=1) + "\n")
    print(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
