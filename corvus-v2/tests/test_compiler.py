"""The compiler's tests — each invariant with its negative case, the
monotonicity diff-classify, the coverage invariant.

The C1-class conflation test is the regression guard for ledger entry 22:
the invariant that caught the WP0 YAML's verdict-enum error, kept sharp.
"""
import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.compiler import CompilerError, build, compile_catalog, diff_classify

REPO = Path(__file__).parent.parent.parent
REGISTER = yaml.safe_load((REPO / "decision-register.yaml").read_text())
FIXTURES = (Path(__file__).parent / "test_decision_contract.py").read_text()


def test_valid_register_compiles():
    catalog = compile_catalog(REGISTER, FIXTURES)
    assert catalog["catalog_version"].startswith("cat-")
    assert len(catalog["sites"]) == 19


def test_fail_answer_outside_enum_rejected():
    """THE C1-CATCHER (ledger entry 22): the fail default outside the site's
    enum is the exact WP0 conflation — the invariant must stay sharp."""
    bad = copy.deepcopy(REGISTER)
    bad["sites"]["C1"]["fail_policy"]["default"]["answer"] = "CAUTION"  # not in {GO, CAUTION, STOP, DEFER}? CAUTION IS a member — use a foreign value
    bad["sites"]["C1"]["fail_policy"]["default"]["answer"] = "MAYBE"
    with pytest.raises(CompilerError, match="not an enum member"):
        compile_catalog(bad)


def test_on_unknown_outside_enum_rejected():
    bad = copy.deepcopy(REGISTER)
    bad["sites"]["C2"]["on_unknown"] = "maybe"
    with pytest.raises(CompilerError, match="on_unknown"):
        compile_catalog(bad)


def test_ordering_must_cover_enum():
    bad = copy.deepcopy(REGISTER)
    bad["sites"]["C1"]["resolution"]["ordering"] = ["GO", "CAUTION"]  # partial
    with pytest.raises(CompilerError, match="does not cover the enum"):
        compile_catalog(bad)


def test_resolution_le_granularity():
    bad = copy.deepcopy(REGISTER)
    bad["sites"]["C2"]["resolution"]["bands"] = ["b1", "b2", "b3", "b4", "b5", "b6"]
    with pytest.raises(CompilerError, match="finer than the action space"):
        compile_catalog(bad)


def test_score_requires_bins():
    """The v2 register has no score sites (C2 became a choice) — the test
    synthesizes one, then empties its bins."""
    bad = copy.deepcopy(REGISTER)
    bad["sites"]["SPIKE-SCORE"] = {
        "type": "score", "solver": "model", "question": "spike",
        "criteria": [0, 1, 2, 3], "resolution": {"bands": [0, 1, 2, 3]},
        "fail_policy": {"default": {"answer": 3}}, "on_unknown": 3,
    }
    bad["sites"]["SPIKE-SCORE"]["criteria"] = []
    with pytest.raises(CompilerError, match="must declare its bins"):
        compile_catalog(bad)


def test_resolution_map_must_be_total():
    bad = copy.deepcopy(REGISTER)
    del bad["sites"]["C1"]["resolution"]["map"]["DEFER"]
    with pytest.raises(CompilerError, match="not total"):
        compile_catalog(bad)


def test_error_enum_coverage_invariant():
    """Every closed-enum code is triggered by ≥1 fixture (the waived codes
    excepted); an uncovered code = build failure."""
    # The real corpus passes (the waivers tracked in compiler._coverage):
    compile_catalog(REGISTER, FIXTURES)
    # A corpus missing a code fails:
    stripped = FIXTURES.replace('"duplicate_site"', '"something_else"')
    with pytest.raises(CompilerError, match="does not trigger"):
        compile_catalog(REGISTER, stripped)


def test_diff_first_build_is_additive():
    catalog = compile_catalog(REGISTER)
    diff = diff_classify(catalog, None)
    assert diff["diff_class"] == "additive"


def test_diff_weakening_requires_justification():
    base = compile_catalog(copy.deepcopy(REGISTER))
    worse = copy.deepcopy(REGISTER)
    # C1's fail default: CAUTION → GO — a step DOWN the declared ordering
    # [GO, DEFER, CAUTION, STOP] = the weakening (the permissive drift).
    worse["sites"]["C1"]["fail_policy"]["default"]["answer"] = "GO"
    worse["sites"]["C1"]["fail_policy"]["modes"]["unavailable"]["answer"] = "GO"
    worse_catalog = compile_catalog(worse)
    diff = diff_classify(worse_catalog, base)
    assert diff["diff_class"] == "weakening"
    assert diff["sites"]["C1"] == "weakening"


def test_diff_strengthening_is_not_weakening():
    base = compile_catalog(copy.deepcopy(REGISTER))
    better = copy.deepcopy(REGISTER)
    # C1's fail default: CAUTION → STOP — a step UP the ordering = the
    # strengthening (the ratchet's tightening direction).
    better["sites"]["C1"]["fail_policy"]["default"]["answer"] = "STOP"
    better["sites"]["C1"]["fail_policy"]["modes"]["unavailable"]["answer"] = "STOP"
    better_catalog = compile_catalog(better)
    diff = diff_classify(better_catalog, base)
    assert diff["diff_class"] != "weakening"


def test_build_gate_fails_on_unacknowledged_weakening(tmp_path):
    base = compile_catalog(copy.deepcopy(REGISTER))
    base_path = tmp_path / "catalog.json"
    base_path.write_text(json.dumps(base))
    worse = copy.deepcopy(REGISTER)
    worse["sites"]["C1"]["fail_policy"]["default"]["answer"] = "GO"
    worse["sites"]["C1"]["fail_policy"]["modes"]["unavailable"]["answer"] = "GO"
    worse_path = tmp_path / "register-worse.yaml"
    worse_path.write_text(yaml.dump(worse))
    with pytest.raises(CompilerError, match="unacknowledged downgrade"):
        build(worse_path, base_path=base_path)
    # With the justification, the build passes and the ack rides the artifact:
    catalog = build(worse_path, base_path=base_path,
                    downgrade_justification="the sweep's deliberate P2-style "
                                            "rebalancing; customer-notifiable")
    assert catalog["downgrade_justification"]
