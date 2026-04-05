#!/usr/bin/env python3
"""Sync CMDB services from Corvus API to Splunk lookup CSV.

Run as a scripted input or manually to keep the cmdb_services.csv
lookup in sync with the authoritative CMDB in Corvus.

Usage:
    python3 sync_cmdb_lookup.py

Environment:
    CORVUS_URL: Corvus API base URL (default: http://corvus:8000)
    CORVUS_TOKEN: API token for authentication
"""

import csv
import json
import os
import sys
import urllib.request
from pathlib import Path


def main():
    corvus_url = os.getenv("CORVUS_URL", "http://corvus:8000")
    corvus_token = os.getenv("CORVUS_TOKEN", "")

    # Fetch CMDB services
    url = f"{corvus_url}/ops/cmdb"
    headers = {}
    if corvus_token:
        headers["Authorization"] = f"Bearer {corvus_token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            services = json.loads(resp.read().decode())
    except Exception as e:
        print(f"ERROR: Failed to fetch CMDB from {url}: {e}", file=sys.stderr)
        sys.exit(1)

    # Write lookup CSV
    lookup_dir = Path(__file__).parent.parent / "lookups"
    lookup_file = lookup_dir / "cmdb_services.csv"

    with open(lookup_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["service_name", "host", "service_type", "critical"])
        for svc in services:
            writer.writerow([
                svc.get("name", ""),
                svc.get("host", ""),
                svc.get("service_type", ""),
                1 if svc.get("critical") else 0,
            ])

    print(f"Synced {len(services)} services to {lookup_file}")


if __name__ == "__main__":
    main()
