#!/usr/bin/env python3
"""Validate the corvus-splunk Splunk app.

This app is config-only, so this script IS the whole guard. It proves:
  * every default/*.conf parses as a [stanza] / key = value file
  * every dashboard/nav XML is well-formed
  * every lookup CSV has a header and a consistent column count
  * the transforms.conf -> lookups/, props.conf -> transforms.conf and
    nav/default.xml -> views/ cross-references all resolve
  * every bin/*.py compiles
  * any JSON/YAML that appears parses (there are none today)

It CANNOT prove: that Splunk accepts the app, that the SPL in the saved searches is
valid, or that the dashboards render. Those all need a live Splunk instance.

Stdlib only by design — no venv, no dependencies.
"""

from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT = ROOT / "default"
LOOKUPS = ROOT / "lookups"
VIEWS = DEFAULT / "data" / "ui" / "views"

# Views Splunk ships itself: a nav reference to one of these needs no file here.
BUILTIN_VIEWS = {"search", "dashboards", "reports", "alerts", "help", "launcher"}

REQUIRED = [
    DEFAULT / "app.conf",
    DEFAULT / "indexes.conf",
    DEFAULT / "macros.conf",
    DEFAULT / "props.conf",
    DEFAULT / "savedsearches.conf",
    DEFAULT / "transforms.conf",
    ROOT / "metadata" / "default.meta",
    LOOKUPS,
]

errors: list[str] = []


def check(ok: bool, message: str) -> bool:
    if not ok:
        errors.append(message)
    return ok


def parse_conf(path: Path) -> dict[str, dict[str, str]]:
    """Parse a Splunk .conf into {stanza: {key: value}}.

    Handles '#' comments, blank lines and backslash line continuations. The
    continuations matter: savedsearches.conf splits long SPL across lines, and a
    naive one-key-per-line parser false-fails on them.
    """
    stanzas: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    pending = ""
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = pending + raw
        pending = ""
        if line.rstrip().endswith("\\"):
            pending = line.rstrip()[:-1] + " "
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1].strip()
            if not name:
                errors.append(f"{path.name}:{lineno}: empty stanza name")
            elif name in stanzas:
                errors.append(f"{path.name}:{lineno}: duplicate stanza [{name}]")
            current = stanzas.setdefault(name, {})
            continue
        if current is None:
            errors.append(f"{path.name}:{lineno}: content before the first [stanza]")
            continue
        if "=" not in stripped:
            errors.append(f"{path.name}:{lineno}: not a 'key = value' line: {stripped[:60]!r}")
            continue
        key, _, value = stripped.partition("=")
        current[key.strip()] = value.strip()
    if pending:
        errors.append(f"{path.name}: file ends inside a line continuation")
    return stanzas


def main() -> int:
    counts = {"conf": 0, "xml": 0, "csv": 0, "py": 0}

    # 1. the metadata files a Splunk app cannot ship without
    for path in REQUIRED:
        check(path.exists(), f"missing required path: {path.relative_to(ROOT)}")

    # 2. every .conf parses
    confs: dict[str, dict[str, dict[str, str]]] = {}
    for path in sorted(DEFAULT.glob("*.conf")):
        confs[path.name] = parse_conf(path)
        counts["conf"] += 1
        print(f"  conf  default/{path.name}: {len(confs[path.name])} stanza(s)")

    # 3. every XML is well-formed
    for path in sorted(DEFAULT.rglob("*.xml")):
        counts["xml"] += 1
        try:
            ET.parse(path)
            print(f"  xml   {path.relative_to(ROOT)}: well-formed")
        except ET.ParseError as exc:
            errors.append(f"{path.relative_to(ROOT)}: malformed XML: {exc}")

    # 4. every lookup CSV has a header and a consistent column count
    for path in sorted(LOOKUPS.glob("*.csv")):
        counts["csv"] += 1
        rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
        if not rows:
            errors.append(f"lookups/{path.name}: empty CSV")
            continue
        width = len(rows[0])
        for lineno, row in enumerate(rows[1:], start=2):
            if len(row) != width:
                errors.append(f"lookups/{path.name}:{lineno}: {len(row)} columns, header has {width}")
        print(f"  csv   lookups/{path.name}: {len(rows) - 1} row(s) x {width} col(s)")

    # 5. transforms.conf filename = X must exist under lookups/
    transforms = confs.get("transforms.conf", {})
    for stanza, keys in transforms.items():
        filename = keys.get("filename")
        if filename:
            check((LOOKUPS / filename).exists(), f"transforms.conf [{stanza}] points at missing lookup {filename!r}")

    # 6. props.conf LOOKUP-<name> = <transform stanza> ... must resolve
    for stanza, keys in confs.get("props.conf", {}).items():
        for key, value in keys.items():
            if not key.upper().startswith("LOOKUP-"):
                continue
            target = value.split()[0] if value.split() else ""
            check(target in transforms, f"props.conf [{stanza}] {key} references unknown transforms stanza {target!r}")

    # 7. nav/default.xml view references must resolve to views/<name>.xml
    nav = DEFAULT / "data" / "ui" / "nav" / "default.xml"
    if nav.exists():
        for view in ET.parse(nav).getroot().iter("view"):
            name = view.get("name") or ""
            if name in BUILTIN_VIEWS:
                continue
            check((VIEWS / f"{name}.xml").exists(), f"nav/default.xml references view {name!r} with no views/{name}.xml")

    # 8. every bin/ script compiles (in memory — writes nothing)
    for path in sorted((ROOT / "bin").glob("*.py")):
        counts["py"] += 1
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            print(f"  py    bin/{path.name}: compiles")
        except SyntaxError as exc:
            errors.append(f"bin/{path.name}: syntax error: {exc}")

    # 9. JSON, and YAML if any appears (there are none today)
    for path in sorted(ROOT.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.relative_to(ROOT)}: malformed JSON: {exc}")
    yamls = sorted(ROOT.rglob("*.yaml")) + sorted(ROOT.rglob("*.yml"))
    if yamls:
        try:
            import yaml
        except ImportError:
            errors.append("YAML files present but PyYAML is unavailable — refusing to skip them silently")
        else:
            for path in yamls:
                try:
                    yaml.safe_load(path.read_text(encoding="utf-8"))
                except yaml.YAMLError as exc:
                    errors.append(f"{path.relative_to(ROOT)}: malformed YAML: {exc}")

    if errors:
        print(f"\nvalidate: FAILED — {len(errors)} problem(s)", file=sys.stderr)
        for problem in errors:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(
        f"\nvalidate: ok — {counts['conf']} conf, {counts['xml']} xml, "
        f"{counts['csv']} csv, {counts['py']} py, 0 json, {len(yamls)} yaml"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
