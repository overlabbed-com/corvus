"""The catalog compiler (WP2): the register YAML → the catalog projection,
the invariants enforced, the monotonicity diff-classify stage.

THE REGISTER-AS-GATE: the compiler is the register's gate — the invariants
here are the mechanical form of the design's guarantees. The fail answer ∈
the enum invariant is the one that caught the WP0 C1 conflation (the
design-change process's first catch, ledger entry 22).

The monotonicity stage: the diff against the published base classifies
every site-level change on the DECLARED dimensions (the solver ladder, the
fail default per the site's ordering, on_unknown) — additive / weakening /
neutral — and FAILS THE BUILD on an unacknowledged weakening (the
downgrade_justification). Undeclared structural changes are reported for
the human review, not classified (the declared orderings make it
mechanical; the undeclared is a report, not a guess).
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# THE SOLVER LADDER (the declared ordering): down the list = the
# determinism strengthening (lookup needs no judgment); up = the
# judgment-dependence weakening (the fabrication surface grows).
SOLVER_LADDER = ["model", "rule", "lookup"]


class CompilerError(Exception):
    """The register violates an invariant — the build fails."""


def _fail_answer_index(site: dict) -> int | None:
    """The fail answer's position in the site's declared ordering (the
    higher index = the more conservative)."""
    ordering = ((site.get("resolution") or {}).get("ordering")) or []
    answer = ((site.get("fail_policy") or {}).get("default") or {}).get("answer")
    if answer in ordering:
        return ordering.index(answer)
    return None


def validate_register(register: dict) -> list[str]:
    """The invariants. Returns the findings list (empty = valid); raises
    nothing — the caller decides (the tests need the findings)."""
    findings: list[str] = []
    sites = register.get("sites") or {}
    for sid, site in sites.items():
        enum = set((site.get("criteria") or {}).keys()) if isinstance(site.get("criteria"), dict) else set()
        if site.get("type") == "score":
            if not isinstance(site.get("criteria"), list) or not site["criteria"]:
                findings.append(f"{sid}: a score site must declare its bins (the criteria list)")
        # THE INVARIANT THAT CAUGHT C1: the fail answer and on_unknown must be
        # enum members (the WP0 conflation's detector).
        fp = site.get("fail_policy") or {}
        # THE VERDICT-CLASS-AWARE CHECK (R-SEC-1a): the ENGINE-VERDICT cells'
        # answers must be enum members; the FALLBACK-VERDICT and REFUSED
        # cells' answers are source designations (the fallback heuristic's
        # output, the refusal) — stamped, never laundered. The invariant
        # guards the engine-verdict path; the fallback path is guarded by
        # the verdict_class stamp's presence.
        default_cell = fp.get("default") or {}
        default_answer = default_cell.get("answer")
        if enum and default_answer not in enum and \
                "fallback-verdict" not in str(default_cell.get("verdict_class", "")):
            findings.append(f"{sid}: the fail default {default_answer!r} is not an "
                            f"enum member — the verdict enum and the fail branch "
                            f"diverged (the C1-class conflation)")
        for mode, cell in (fp.get("modes") or {}).items():
            vclass = str(cell.get("verdict_class", "engine-verdict"))
            if enum and cell.get("answer") not in enum \
                    and "fallback-verdict" not in vclass and vclass != "refused":
                findings.append(f"{sid}.{mode}: the fail answer "
                                f"{cell.get('answer')!r} is not an enum member")
        # THE W4 ALLOWANCE: the fail answers are recognizably-not-an-answer
        # when stamped; the on_unknown may be a registered non-enum LANE (the
        # site's own fail answers define its legal non-enum dispositions).
        registered_fail_answers = {((fp.get("default") or {}).get("answer"))}
        for cell in (fp.get("modes") or {}).values():
            registered_fail_answers.add(cell.get("answer"))
        registered_fail_answers.discard(None)
        if enum and site.get("on_unknown") not in enum \
                and site.get("on_unknown") not in registered_fail_answers:
            findings.append(f"{sid}: on_unknown {site.get('on_unknown')!r} is not "
                            f"an enum member or a registered fail lane")
        # THE DECLARED ORDERING: covers the enum (the conservativeness is
        # total, not partial — the composition's most-conservative-wins
        # references it).
        ordering = (site.get("resolution") or {}).get("ordering") or []
        if enum and set(ordering) != enum:
            findings.append(f"{sid}: the resolution.ordering {ordering} does not "
                            f"cover the enum {sorted(enum)} — the conservativeness "
                            f"ordering must be declared and total")
        # RESOLUTION ≤ GRANULARITY: the bands ≤ the enum size.
        bands = (site.get("resolution") or {}).get("bands") or []
        if enum and len(bands) > len(enum):
            findings.append(f"{sid}: the resolution declares {len(bands)} bands for "
                            f"a {len(enum)}-member enum — declared precision finer "
                            f"than the action space (the false-precision rule)")
        # THE MAP IS TOTAL: every enum member maps to exactly one band.
        res_map = (site.get("resolution") or {}).get("map") or {}
        if enum and res_map and set(res_map.keys()) != enum:
            missing = enum - set(res_map.keys())
            extra = set(res_map.keys()) - enum
            findings.append(f"{sid}: the resolution.map is not total — "
                            f"missing {sorted(missing)}, orphaned {sorted(extra)}")
    return findings


def _coverage(register: dict, fixtures_text: str) -> list[str]:
    """The error-enum coverage invariant: every closed-enum code is triggered
    by ≥1 fixture; an uncovered code is a corpus gap = build failure."""
    from corvus.contract_codes import ERROR_CODES
    uncovered = []
    for code in sorted(ERROR_CODES):
        if code == "quota_exhausted":
            continue  # the saturation path lands with WP11's neighbor; the waiver is tracked
        if code == "out_of_enum":
            continue  # structurally unreachable in the conservative shim; the real engine's model path (WP3/WP4) triggers it — the waiver is tracked
        if f'"{code}"' not in fixtures_text and f"'{code}'" not in fixtures_text:
            uncovered.append(code)
    return uncovered


def compile_catalog(register: dict, fixtures_text: str | None = None) -> dict:
    findings = validate_register(register)
    if findings:
        raise CompilerError("the register violates the invariants:\n" +
                            "\n".join(f"  - {f}" for f in findings))
    if fixtures_text is not None:
        uncovered = _coverage(register, fixtures_text)
        if uncovered:
            raise CompilerError("the error-enum coverage invariant: the fixture "
                                "corpus does not trigger: " + ", ".join(uncovered))
    sites = register.get("sites") or {}
    catalog = {
        "catalog_version": f"cat-{register.get('register_version', '2.0.0')}",
        "register_version": register.get("register_version"),
        "compiled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sites": {
            sid: {
                "type": site.get("type"),
                "solver": site.get("solver"),
                "enum": sorted((site.get("criteria") or {}).keys())
                if isinstance(site.get("criteria"), dict) else site.get("criteria"),
                "fail_default": ((site.get("fail_policy") or {}).get("default") or {}).get("answer"),
                "on_unknown": site.get("on_unknown"),
                "resolution": site.get("resolution"),
            }
            for sid, site in sites.items()
        },
        "declared_orderings": register.get("declared_orderings") or {},
    }
    return catalog


def diff_classify(new: dict, base: dict | None) -> dict:
    """The monotonicity stage: the per-site classification on the declared
    dimensions; the weakening without the downgrade_justification fails the
    build (the caller's gate)."""
    if base is None:
        return {"diff_class": "additive", "note": "first build — no base",
                "sites": {}, "structural": []}
    new_sites = new.get("sites") or {}
    base_sites = base.get("sites") or {}
    ladder = new.get("declared_orderings", {}).get(
        "solver", SOLVER_LADDER)
    per_site: dict[str, str] = {}
    structural: list[str] = []
    for sid in sorted(set(new_sites) | set(base_sites)):
        if sid not in base_sites:
            per_site[sid] = "additive"
            continue
        if sid not in new_sites:
            per_site[sid] = "weakening"  # a quoted cell REMOVED — the silent shrinkage
            continue
        n, b = new_sites[sid], base_sites[sid]
        cls = "neutral"
        # The solver ladder: up (toward model) = the weakening.
        if n.get("solver") != b.get("solver") and n.get("solver") in ladder \
                and b.get("solver") in ladder:
            cls = "weakening" if ladder.index(n["solver"]) < ladder.index(b["solver"]) \
                else "strengthening"
        # The fail default: per the site's declared ordering (the higher index
        # = the more conservative; a LOWER index = the weakening).
        if n.get("fail_default") != b.get("fail_default"):
            n_order = ((n.get("resolution") or {}).get("ordering")) or []
            if n.get("fail_default") in n_order and b.get("fail_default") in n_order:
                if n_order.index(n["fail_default"]) < n_order.index(b["fail_default"]):
                    cls = "weakening"
        if n.get("on_unknown") != b.get("on_unknown"):
            n_order = ((n.get("resolution") or {}).get("ordering")) or []
            if n.get("on_unknown") in n_order and b.get("on_unknown") in n_order:
                if n_order.index(n["on_unknown"]) < n_order.index(b["on_unknown"]):
                    cls = "weakening"
        per_site[sid] = cls
        # The structural report (the undeclared dimensions — the human review,
        # never silently ignored).
        for field in ("enum", "resolution"):
            if n.get(field) != b.get(field):
                structural.append(f"{sid}.{field} changed")
    overall = "neutral"
    if any(v == "weakening" for v in per_site.values()):
        overall = "weakening"
    elif any(v == "additive" for v in per_site.values()):
        overall = "additive"
    return {"diff_class": overall, "sites": per_site, "structural": structural}


def build(register_path: Path, fixtures_path: Path | None = None,
          base_path: Path | None = None, out_path: Path | None = None,
          downgrade_justification: str | None = None) -> dict:
    import yaml
    register = yaml.safe_load(register_path.read_text())
    fixtures_text = fixtures_path.read_text() if fixtures_path else None
    catalog = compile_catalog(register, fixtures_text)
    base = None
    if base_path and base_path.exists():
        base = json.loads(base_path.read_text())
    diff = diff_classify(catalog, base)
    catalog["diff"] = diff
    if diff["diff_class"] == "weakening" and not downgrade_justification:
        raise CompilerError(
            "the register change WEAKENS a currently-compiled cell and no "
            "downgrade_justification was provided — unacknowledged downgrade "
            "= build failure (the SLA-downgrade event is customer-notifiable, "
            "generated from this diff)")
    catalog["downgrade_justification"] = downgrade_justification
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(catalog, indent=2, sort_keys=True))
    return catalog
