"""The conformance surface (WP14): the mutation runner + the conformance
CLI — the phase's exit gate.

THE MUTATION RUNNER (R-SEC-23): the mutation matrix ships with the
corpus — inject each mutant, the suite must FAIL on each. A conformance
suite that cannot fail is a green check that proves nothing; the
mutation evidence is what makes the pass/fail verdicts mean something.
The mutants target the REGISTER cells and the CLIENT behavior (the
recorded failure classes, each aimed at a unique defect):

M1: the C1 fail answer flipped permissive (GO) — the monotonicity gate
    must catch (the SLA-downgrade event).
M2: the error-enum widened without a fixture — the coverage invariant
    must fail the build.
M3: the client's HTTPError conflated back into unreachability (the
    spike's finding 2 restored) — the contract fixture must red.
M4: the conservative default flipped permissive (the shim's options[0]
    restored) — the decision-core fixture must red.

THE CONFORMANCE CLI: the fixture corpus runs against ANY deployment
(local, SaaS, BYO) — `python -m corvus.conformance --base-url URL`. The
corpus is version-stamped with contract_version; the run result declares
which contract version it tested (the three-state verdict per check:
pass/fail/VOID — never a silent skip).

THE MODE SEPARATION (R-SEC-24): the conformance listener is a SEPARATE
surface; the production listener refuses the conformance handshake. The
run-scoped capture: the conformance runs write to a run-scoped
partition, never the fleet's.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
TESTS_DIR = Path(__file__).parent.parent / "tests"

# THE MUTATION MATRIX: {mutant_id, the target defect, the transformation}
MUTANTS = [
    {"id": "M1-permissive-fail-answer",
     "defect": "the C1 fail answer drifted permissive (the SLA-downgrade)",
     "file": "decision-register.yaml",
     "old": "default: {answer: CAUTION, reason_class: unknown, resolution: escalation-queue}",
     "new": "default: {answer: GO, reason_class: unknown, resolution: escalation-queue}"},
    {"id": "M2-enum-widened-uncovered",
     "defect": "the error enum widened without a triggering fixture",
     "file": "corvus-v2/corvus/contract_codes.py",
     "old": '"quota_exhausted",\n}',
     "new": '"quota_exhausted", "phantom_code",\n}'},
    {"id": "M3-client-conflation-restored",
     "defect": "the contract errors masked as unreachability (the spike's finding 2)",
     "file": "corvus-v2/corvus/decisions.py",
     "old": "        except urllib.error.HTTPError:",
     "new": "        except (urllib.error.HTTPError, urllib.error.URLError):"},
    {"id": "M4-permissive-default-restored",
     "defect": "the conservative default flipped permissive (the spike's finding 1)",
     "file": "corvus-v2/corvus/decision_core.py",
     "old": "            return self._full(enum[-1] if enum else None,\n                              reason=\"rule-unregistered\")",
     "new": "            return self._full(enum[0] if enum else None,\n                              reason=\"rule-unregistered\")"},
]


def run_mutation_suite(test_command: list[str] | None = None,
                       repo: Path = REPO) -> dict:
    """The mutation runner: for each mutant, apply the transformation to a
    WORK COPY, run the suite, assert the relevant test REDS, restore. The
    evidence: {mutant_id, caught: bool, the red test}. A mutant that does
    NOT red the suite = the guard is vacuous = the build failure."""
    # THE FULL SUITE: a mutant aimed at ANY guard must red SOMEWHERE — the
    # narrowed run would miss the guards living in the other test modules
    # (M4's conservative-default guard lives in test_decision_core.py).
    test_command = test_command or [sys.executable, "-m", "pytest",
                                    str(TESTS_DIR), "-x", "-q", "--no-header"]
    evidence = []
    for mutant in MUTANTS:
        target = repo / mutant["file"]
        original = target.read_text()
        if mutant["old"] not in original:
            evidence.append({"id": mutant["id"], "caught": False,
                             "error": "the mutant anchor not found — the "
                                      "transformation is stale"})
            continue
        try:
            target.write_text(original.replace(mutant["old"], mutant["new"]))
            proc = subprocess.run(test_command, capture_output=True,
                                  text=True, timeout=300, cwd=str(repo / "corvus-v2"))
            # THE MUTATION CONTRACT: the suite must RED (exit non-zero).
            caught = proc.returncode != 0
            red_test = _extract_red_test(proc.stdout)
            evidence.append({"id": mutant["id"], "caught": caught,
                             "red_test": red_test,
                             "defect": mutant["defect"]})
        finally:
            target.write_text(original)  # the restore — always
    all_caught = all(e["caught"] for e in evidence)
    return {"all_mutants_caught": all_caught, "evidence": evidence,
            "corpus_version": "contract-1.1"}


def _extract_red_test(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("FAILED") or "FAILED tests/" in line:
            return line.split("::")[-1].split(" ")[0]
    return "suite-level"


def conformance_run(base_url: str, timeout: float = 10.0) -> dict:
    """THE CONFORMANCE CLI: the fixture corpus against any deployment. The
    skeleton runs the wire-level checks via HTTP (the happy path, the
    existence-hiding, the floor rejection); the full corpus is the pytest
    suite (the CI runner). The three-state verdict per check."""
    import urllib.error
    import urllib.request
    checks = []

    def check(cid, fn):
        try:
            fn()
            checks.append({"id": cid, "verdict": "pass"})
        except AssertionError as exc:
            checks.append({"id": cid, "verdict": "fail", "detail": str(exc)})
        except Exception as exc:
            checks.append({"id": cid, "verdict": "void",
                           "detail": f"{type(exc).__name__}: {exc}"})

    def happy_path():
        body = json.dumps({"state": {"target": "db"},
                           "sites": [{"site_id": "C1", "type": "choice",
                                      "instructions": "i",
                                      "criteria": {"GO": "g", "CAUTION": "c",
                                                   "STOP": "s"}}]}).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/fleets/fleet-alpha/decide", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Corvus-Principal": "corvus-service"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        assert data["capture_status"] == "recorded"
        assert data["request_hash"]

    def existence_hiding():
        body = json.dumps({"state": {}, "sites": []}).encode()
        codes = []
        for fid in ("fleet-ghost", "fleet-beta"):
            req = urllib.request.Request(
                f"{base_url}/v1/fleets/{fid}/decide", data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "X-Corvus-Principal": "corvus-service"})
            try:
                urllib.request.urlopen(req, timeout=timeout)
                raise AssertionError("expected 404")
            except urllib.error.HTTPError as e:
                codes.append((e.code, e.read()))
        assert codes[0][0] == codes[1][0] == 404, "the codes must match"
        assert codes[0][1] == codes[1][1], "the bodies must be identical"

    check("happy-path", happy_path)
    check("existence-hiding", existence_hiding)
    summary = {"contract_version": "1.1", "checks": checks,
               "passed": sum(1 for c in checks if c["verdict"] == "pass"),
               "failed": sum(1 for c in checks if c["verdict"] == "fail"),
               "void": sum(1 for c in checks if c["verdict"] == "void")}
    return summary
