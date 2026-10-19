"""The canonical-form serializer + the request_hash (WP1).

RFC 8785/JCS-class: the object keys sorted recursively, the list order
preserved, the numbers in the fixed repr form. The request_hash binds
state + facts + sites over this CANONICAL form — not the raw received
bytes — so the hash is serializer-independent and the replay/re-decide
reconstructs byte-identical inputs (the shadow re-scoring's substrate;
the same-base control for the weight comparison).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonicalize(value: Any) -> Any:
    """The JCS-class canonical form: the dicts sorted by key, recursively."""
    if isinstance(value, dict):
        return {k: canonicalize(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [canonicalize(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        # The fixed number formatting: the repr form is stable for the same
        # value; integers stay integers (the JCS distinction).
        if value == int(value) and abs(value) < 1e15:
            return int(value)
        return float(format(value, ".17g"))
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(canonicalize(value), separators=(",", ":"), ensure_ascii=False)


def request_hash(state: dict, facts: dict, sites: list) -> str:
    """The canonical-form request_hash: sha256 over the canonical JSON of
    {facts, sites, state} — the sole cross-store key (the engine telemetry
    <=> the Corvus evidence <=> the chain)."""
    payload = canonical_json({"facts": facts, "sites": sites, "state": state})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
