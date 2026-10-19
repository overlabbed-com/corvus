"""The decision-engine shim: a local service conforming to ENGINE-CONTRACT.md.

The estate's clef-decide lineage in miniature: the state in, the typed sites,
the typed answers out with per-option probabilities, fail-closed at BOTH ends
(a malformed site → 400 with the contract message; an out-of-enum answer →
422). The conformance fixtures (tests/test_decision_contract.py) prove the
both-ends fail-closure against this shim.

Run: python -m corvus.engine_shim --port 8933
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Corvus decision-engine shim", version="1.0.0")

VALID_TYPES = {"choice", "score", "noul"}


# THE SPIKE'S EXISTENCE-HIDING FIXTURE SUPPORT: the known fleets and the
# principal→fleet authorization. Unknown fleet → 404; known-but-not-yours
# → 404 IDENTICALLY (the existence-hiding rule: the two responses are
# indistinguishable). The v1-local posture: the principal is the Corvus
# service identity over loopback; the spike simulates the principal with
# the X-Corvus-Principal header.
KNOWN_FLEETS = {"fleet-alpha", "fleet-beta"}
PRINCIPAL_FLEETS = {"corvus-service": {"fleet-alpha"}}

# THE PROVENANCE LADDER (the ordering from the architect's schema):
# caller-stated < computed < engine-derived < attested
PROV_RANK = {"caller-stated": 0, "computed": 1, "engine-derived": 2, "attested": 3}


@app.post("/v1/fleets/{fleet_id}/decide")
async def decide(fleet_id: str, request: Request):
    body = await request.json()
    # THE EXISTENCE-HIDING RULE (R-SEC-5): the payload fleet_id is a routing
    # key; the authenticated principal determines scope. Unknown fleet → 404;
    # known-but-unauthorized → 404 IDENTICALLY (same body, same code).
    principal = request.headers.get("x-corvus-principal", "corvus-service")
    if fleet_id not in KNOWN_FLEETS or fleet_id not in PRINCIPAL_FLEETS.get(principal, set()):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found",
                               "message": "not found", "request_id": "spike"}})
    sites = body.get("sites") or {}
    state = body.get("state") or {}
    facts = body.get("facts") or {}
    if not sites:
        raise HTTPException(status_code=400, detail="contract: no sites submitted")

    # THE PROVENANCE-FLOOR CHECK (the boundary's mechanical form): each
    # site's required_facts declare a minimum class per field; a fact below
    # the floor → 400 with the STRUCTURED payload (failed_fact_id,
    # required_provenance_class, observed_provenance_class) — the
    # actionable remediation the adversarial review demanded.
    for site_id, site in sites.items():
        for fname, spec in (site.get("required_facts") or {}).items():
            floor = spec.get("min_class")
            if not floor:
                continue
            fact = facts.get(fname)
            observed = (fact or {}).get("provenance_class", "caller-stated")
            if fact is None or PROV_RANK.get(observed, 0) < PROV_RANK.get(floor, 0):
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "provenance_below_floor",
                                       "site_id": site_id,
                                       "failed_fact_id": fname,
                                       "required_provenance_class": floor,
                                       "observed_provenance_class": observed,
                                       "message": f"fact {fname!r} is below the "
                                                  f"declared floor for site {site_id!r}",
                                       "request_id": "spike"}})

    answers = {}
    for site_id, site in sites.items():
        # THE BOUNDARY: the malformed site is rejected HERE — 400 with the
        # contract message. It never reaches the engine core.
        stype = site.get("type")
        if stype not in VALID_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"contract: site {site_id} has unknown type {stype!r}; valid: {sorted(VALID_TYPES)}")
        if not site.get("instructions"):
            raise HTTPException(
                status_code=400,
                detail=f"contract: site {site_id} is missing instructions")
        criteria = site.get("criteria")
        if stype == "choice" and (not isinstance(criteria, dict) or not criteria):
            raise HTTPException(
                status_code=400,
                detail=f"contract: site {site_id} is a choice without criteria (the enum map)")
        if stype == "score" and not isinstance(criteria, list):
            raise HTTPException(
                status_code=400,
                detail=f"contract: site {site_id} is a score without the scale (the criteria list)")

        # The shim's deterministic "engine": the choice answers by the state's
        # simple signals (the conformance fixtures pin the mapping); the score
        # returns the scale midpoint; noul returns the state's value.
        #
        # THE SPIKE FINDING (2026-10-19): the original heuristic matched the
        # OPTION NAME against the serialized state and defaulted to
        # options[0] on no-match — a PERMISSIVE default (the first criterion
        # happened to be GO) that violates the fail-conservative principle,
        # and a name-vs-serialization match that cannot map state VALUES
        # (severity: critical) to option NAMES (STOP) — that mapping is the
        # site's criteria CONTENT, which lives in the register (WP0), not in
        # a substring heuristic. The fix: the recorded C1 rule (core.py's
        # deterministic conditions, restated) drives the answer; the
        # no-match default is the MOST CONSERVATIVE option (the last resort
        # fails toward safety, never toward permissiveness).
        if stype == "choice":
            options = list(criteria.keys())
            answer = None
            probs = {o: 1.0 / len(options) for o in options}
            # The recorded C1 rule (the deterministic conditions, restated
            # from core.py's degraded path): a recent critical/high/error
            # event on the target → STOP; an active change window or an
            # ESCALATE trust tier → CAUTION; else GO.
            severity = (state.get("recent_severity") or "").lower()
            has_active = bool(state.get("active_changes"))
            tier = (state.get("trust_tier") or "").upper()
            if severity in ("critical", "high", "error"):
                answer = "STOP" if "STOP" in criteria else options[-1]
            elif has_active or tier == "ESCALATE":
                answer = "CAUTION" if "CAUTION" in criteria else options[-1]
            elif "GO" in criteria:
                answer = "GO"
            if answer is None:
                # THE CONSERVATIVE DEFAULT: the no-match fallback is the
                # most conservative option (the LAST in the declared
                # ordering), never the first. The ordering lives in the
                # site's criteria content (the register); the shim's
                # heuristic takes the conservative floor.
                answer = options[-1]
                probs = {o: (0.6 if o == answer else 0.4 / max(1, len(options) - 1))
                         for o in options}
            else:
                probs = {x: (0.9 if x == answer else 0.1 / max(1, len(options) - 1))
                         for x in options}
            if answer not in options:
                # THE ANSWER END: the out-of-enum answer is an error — 422.
                raise HTTPException(
                    status_code=422,
                    detail=f"contract: site {site_id} produced out-of-enum answer {answer!r}")
            answers[site_id] = {"answer": answer, "probabilities": probs}
        elif stype == "score":
            scale = criteria or [0, 1]
            mid = (float(scale[0]) + float(scale[-1])) / 2
            answers[site_id] = {"answer": mid, "probabilities": {}}
        else:  # noul
            answers[site_id] = {"answer": state.get("value"), "probabilities": {}}

    return {"answers": answers, "engine": {"id": "corvus-shim", "latency_ms": 1}}


import json  # noqa: E402 (used in the handler above)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8933)
    args = ap.parse_args()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="error")
