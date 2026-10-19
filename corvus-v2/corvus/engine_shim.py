"""The decision-engine shim: a local service conforming to ENGINE-CONTRACT.md
v1.1 — the WP1 contract boundary (the spike promoted per the spike-promotion
rule).

The estate's clef-decide lineage in miniature: the state in, the typed sites,
the typed answers out with per-option probabilities, fail-closed at BOTH ends.
WP1 adds: the sites-as-array with duplicate detection, the canonical-form
request_hash, the quantization at the response assembly (the consumed surface
only on the wire — the full precision born, measured, and audited inside),
the idempotency_key + the replay, the facts-shape validation, the closed
error-enum envelope.

Run: python -m corvus.engine_shim --port 8933
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from corvus.capture import CaptureStore
from corvus.canonical import canonical_json, request_hash
from corvus.contract_codes import ERROR_CODES

app = FastAPI(title="Corvus decision-engine shim", version="1.1.0")

VALID_TYPES = {"choice", "score", "noul"}

# THE CLOSED ERROR ENUM (the contract v1.1): every error the boundary emits,
# compiler-verified against the fixture corpus (the error-enum coverage
# invariant — an uncovered code is a corpus gap = build failure).
# (the import itself lives at the module's top with the other imports)


def err(code: str, status: int, **fields):
    """The contract error envelope: {"error": {code, ...fields, request_id}}."""
    assert code in ERROR_CODES, f"uncoded error {code!r} — the enum is closed"
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, **fields,
                                           "request_id": "wp1"}})


# THE EXISTENCE-HIDING FIXTURE SUPPORT (R-SEC-5): unknown fleet → 404;
# known-but-unauthorized → 404 IDENTICALLY. The v1-local posture: the
# principal is the Corvus service identity over loopback; the spike
# simulates the principal with the X-Corvus-Principal header.
KNOWN_FLEETS = {"fleet-alpha", "fleet-beta"}
PRINCIPAL_FLEETS = {"corvus-service": {"fleet-alpha"}}

# THE PROVENANCE LADDER: caller-stated < computed < engine-derived < attested
PROV_RANK = {"caller-stated": 0, "computed": 1, "engine-derived": 2, "attested": 3}

# THE REGISTER (WP0's output): the resolution maps for the quantization.
_REGISTER_PATH = Path(__file__).parent.parent.parent / "decision-register.yaml"
_REGISTER: dict = {}
if _REGISTER_PATH.exists():
    import yaml
    _REGISTER = yaml.safe_load(_REGISTER_PATH.read_text()) or {}


def _site_resolution(site_id: str) -> dict | None:
    return (_REGISTER.get("sites", {}).get(site_id, {}) or {}).get("resolution")


# THE CAPTURE STORE (WP5): the bounded telemetry store + the PERSISTED
# replay index (the SQLite WAL — F10: a restart does not wipe the replay).
# The spike defaults to :memory:; the production config points
# CORVUS_CAPTURE_DB at the file.

_CAPTURE = CaptureStore(db_path=os.environ.get("CORVUS_CAPTURE_DB", ":memory:"),
                        max_rows=10_000)
_REPLAY_WINDOW_S = 300.0


def _quantize(site_id: str, member: str, probabilities: dict) -> tuple[str, str]:
    """The quantization step (engine-side, at the response assembly — BEFORE
    the trust boundary): the full-precision member → the consumed band via
    the catalog's resolution map; the confidence_band = the band's coarse
    form. The wire carries the consumed form ONLY — the full precision is
    born, measured, and audited inside the engine (R-SEC-20's split)."""
    res = _site_resolution(site_id)
    if not res:
        return member, "unquantized"
    band = (res.get("map") or {}).get(member, member)
    coarse = (res.get("coarse") or {}).get(band, band)
    return band, coarse


@app.post("/v1/fleets/{fleet_id}/decide")
async def decide(fleet_id: str, request: Request):
    body = await request.json()

    # THE EXISTENCE-HIDING RULE (R-SEC-5): unknown fleet → 404; known-but-
    # unauthorized → 404 IDENTICALLY (same body, same code).
    principal = request.headers.get("x-corvus-principal", "corvus-service")
    if fleet_id not in KNOWN_FLEETS or fleet_id not in PRINCIPAL_FLEETS.get(principal, set()):
        return err("not_found", 404, message="not found")

    # THE IDEMPOTENCY KEY + THE REPLAY (F5's recovery path): the same key
    # within the window → the CACHED response + the replay marker — the
    # recovery for the answered-but-unheard case (the engine solved,
    # captured, and the client never heard it).
    idem = body.get("idempotency_key")
    if idem:
        cached = _CAPTURE.replay_lookup(idem)
        if cached:
            replayed = dict(cached)
            replayed["replayed"] = True
            return replayed

    state = body.get("state") or {}
    facts = body.get("facts") or {}
    sites = body.get("sites")
    # THE SITES-AS-ARRAY (the contract v1.1, E1 — breaking, pre-implementation):
    # the sites arrive as an ARRAY of {site_id, ...}; the duplicate site_ids
    # are detected at the boundary (a dict cannot express them).
    if not isinstance(sites, list) or not sites:
        return err("no_sites", 400, message="contract: no sites submitted (the array form)")
    seen: set[str] = set()
    for entry in sites:
        sid = entry.get("site_id")
        if not sid:
            return err("no_sites", 400, message="contract: a site entry is missing site_id")
        if sid in seen:
            return err("duplicate_site", 400, site_id=sid,
                       message=f"contract: duplicate site id {sid!r}")
        seen.add(sid)

    # THE CANONICAL-FORM REQUEST_HASH: over the canonical JSON of
    # {facts, sites, state} — serializer-independent, replay-stable.
    rh = request_hash(state, facts, sites)

    # THE PROVENANCE-FLOOR CHECK: a fact below the declared minimum class →
    # 400 with the STRUCTURED payload.
    for entry in sites:
        sid = entry.get("site_id")
        for fname, spec in (entry.get("required_facts") or {}).items():
            floor = spec.get("min_class")
            if not floor:
                continue
            fact = facts.get(fname)
            observed = (fact or {}).get("provenance_class", "caller-stated")
            if fact is None or PROV_RANK.get(observed, 0) < PROV_RANK.get(floor, 0):
                return err("provenance_below_floor", 400, site_id=sid,
                           failed_fact_id=fname,
                           required_provenance_class=floor,
                           observed_provenance_class=observed,
                           message=f"fact {fname!r} is below the declared floor "
                                   f"for site {sid!r}")

    # THE FACTS-SHAPE VALIDATION: a fact whose payload carries a probability
    # distribution over a site's enum members is a shape violation — the
    # probabilities travel only as governance artifacts, never in the facts
    # channel (the non-propagation rule, enforced at the boundary).
    for entry in sites:
        sid = entry.get("site_id")
        criteria = entry.get("criteria")
        enum_members = set(criteria.keys()) if isinstance(criteria, dict) else set()
        if not enum_members:
            continue
        for fname, fact in facts.items():
            value = (fact or {}).get("value", fact) if isinstance(fact, dict) else fact
            if (isinstance(value, dict) and value
                    and set(value.keys()) <= enum_members
                    and all(isinstance(v, (int, float)) for v in value.values())
                    and abs(sum(value.values()) - 1.0) < 0.05):
                return err("probability_in_facts", 400, site_id=sid,
                           failed_fact_id=fname,
                           message=f"fact {fname!r} carries a probability "
                                   f"distribution — the probabilities do not "
                                   f"propagate across the DAG")

    answers_full: dict[str, dict] = {}
    answers_consumed: dict[str, dict] = {}
    for entry in sites:
        sid = entry.get("site_id")
        stype = entry.get("type")
        if stype not in VALID_TYPES:
            return err("unknown_type", 400, site_id=sid,
                       message=f"contract: site {sid!r} has unknown type {stype!r}; "
                               f"valid: {sorted(VALID_TYPES)}")
        if not entry.get("instructions"):
            return err("missing_instructions", 400, site_id=sid,
                       message=f"contract: site {sid!r} is missing instructions")
        criteria = entry.get("criteria")
        if stype == "choice" and (not isinstance(criteria, dict) or not criteria):
            return err("choice_without_criteria", 400, site_id=sid,
                       message=f"contract: site {sid!r} is a choice without criteria")
        if stype == "score" and not isinstance(criteria, list):
            return err("score_without_scale", 400, site_id=sid,
                       message=f"contract: site {sid!r} is a score without the scale")

        # The shim's deterministic engine (the recorded C1 rule; the
        # fail-conservative default — the spike's finding 1).
        if stype == "choice":
            options = list(criteria.keys())
            severity = (state.get("recent_severity") or "").lower()
            has_active = bool(state.get("active_changes"))
            tier = (state.get("trust_tier") or "").upper()
            if severity in ("critical", "high", "error"):
                answer = "STOP" if "STOP" in criteria else options[-1]
            elif has_active or tier == "ESCALATE":
                answer = "CAUTION" if "CAUTION" in criteria else options[-1]
            elif "GO" in criteria:
                answer = "GO"
            else:
                answer = options[-1]
            if answer not in options:
                return err("out_of_enum", 422, site_id=sid,
                           message=f"contract: site {sid!r} produced out-of-enum "
                                   f"answer {answer!r}")
            probs = {x: (0.9 if x == answer else 0.1 / max(1, len(options) - 1))
                     for x in options}
            answers_full[sid] = {"member": answer, "probabilities": probs}
            band, coarse = _quantize(sid, answer, probs)
            digest_src = canonical_json(answers_full[sid])
            answers_consumed[sid] = {
                "answer": band, "confidence_band": coarse,
                "provenance": {"request_hash": rh, "engine_version": "1.1.0",
                               "weight_version": "spike", "catalog_version": "2.0.0-sweep.1",
                               "answer_digest": hashlib_sha(digest_src)},
            }
        elif stype == "score":
            scale = criteria or [0, 1]
            mid = (float(scale[0]) + float(scale[-1])) / 2
            answers_full[sid] = {"member": mid, "probabilities": {}}
            answers_consumed[sid] = {
                "answer": mid, "confidence_band": "unquantized",
                "provenance": {"request_hash": rh, "engine_version": "1.1.0",
                               "weight_version": "spike", "catalog_version": "2.0.0-sweep.1",
                               "answer_digest": hashlib_sha(canonical_json(answers_full[sid]))},
            }
        else:  # noul
            answers_full[sid] = {"member": state.get("value"), "probabilities": {}}
            answers_consumed[sid] = {
                "answer": state.get("value"), "confidence_band": "unquantized",
                "provenance": {"request_hash": rh, "engine_version": "1.1.0",
                               "weight_version": "spike", "catalog_version": "2.0.0-sweep.1",
                               "answer_digest": hashlib_sha(canonical_json(answers_full[sid]))},
            }

    response = {
        "answers": answers_consumed,
        "request_hash": rh,
        "capture_status": "recorded",
        "engine": {"id": "corvus-shim", "version": "1.1.0", "latency_ms": 1},
    }
    # THE CAPTURE ENQUEUE (B4): the full row — the state, the facts, the
    # sites (the canonical form), the dual-precision answers — the
    # re-decide substrate. The status is immediate; the decision path
    # never waits on the durable write's fate.
    capture_status = _CAPTURE.enqueue({
        "request_hash": rh, "idempotency_key": idem,
        "state": state, "facts": facts, "sites": sites,
        "answers_full": answers_full, "answers_consumed": answers_consumed,
        "engine_version": "1.1.0", "weights_version": "spike",
        "catalog_version": "2.0.0-sweep.1",
    })
    response["capture_status"] = capture_status
    if idem:
        _CAPTURE.replay_put(idem, response)
    return response


def hashlib_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8933)
    ap.add_argument("--host", default=os.environ.get("CORVUS_BIND_HOST", "127.0.0.1"))
    args = ap.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="error")
