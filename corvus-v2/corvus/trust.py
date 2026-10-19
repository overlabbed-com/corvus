"""The trust ledger + the deterministic promotion rules (WP12): the
tier system's integrity — TRUST-SPEC's clauses 1–10 as the
implementation.

THE KEY (Clause 1): the strict triple (fleet, fleet-qualified agent,
action_type); per-fleet partitioned; ESCALATE is both the default and
the quarantine state.

THE OUTCOME CONTRACT (Clause 2, obligation-driven): rows are OWED —
every consequential action AND decline owes exactly one attested
outcome row at its due layer within its per-class window; a MISSING due
row IS the disqualifying event, detected fail-closed (the M3
formalization; the three-reconciliation family's evidence layer). The
outcome classes: CLEAN SUCCESS = one row; LOUD FAILURE WITH CLEAN
RECOVERY = near-creditable, weighted by the WHO field (autonomous =
creditable; operator-assisted = a DEDUCTION — the attention spent is
the cost); WRONG-LAYER ATTESTATION = a FAILURE row; SILENT FAILURE /
MISSING ROW = DISQUALIFYING.

THE PRECONDITIONS (Clause 3, all deterministic): the dead-man coverage
is an ELIGIBILITY precondition; the reversibility class must be in the
table (unknown = impossible); the drift-detection coverage (drift
invalidates ALL past attestation for the class); the never-promote
ceiling for the destructive/credential/exposure classes.

THE DIRECTIONALITY (Clause 6/R-SEC-12): promotion fails closed; DEMOTION
NEVER BLOCKS ON ENGINE HEALTH — the demotion executes Corvus-side from
attested incident linkage, independent of the engine.

THE ASYMMETRY (Clause 7): the promotion is slow and multi-evidence; the
demotion is fast and single-evidence. The one-step decay (the trust-spec
amendment): AUTO → SUPERVISED (the evidence is stale, not that the agent
sinned); the full reset stays reserved for the incidents and the
forgery.
"""
from __future__ import annotations

import time

# THE NEVER-PROMOTE CEILING (Clause 3): the frequency never earns it.
NEVER_PROMOTE_CLASSES = {"destructive", "credential", "exposure"}

# THE DUE-LAYER RULE (Clause 2): the per-class attestation layer.
DUE_LAYERS = {
    "deploy": "live-pod-readback",
    "config": "running-pod-config",
    "publish": "rendered-page",
    "remediation": "alert-resolved-and-stayed-resolved",
}


class TrustLedger:
    def __init__(self, store):
        # store: the AttestedStore — the tier changes are CHAIN MEMBERS
        # (Clause 10: append-only events, no second-class records).
        self.store = store
        self._tiers: dict[tuple, str] = {}
        self._outcomes: dict[tuple, list[dict]] = {}
        self._quarantined: set[str] = set()
        self._drift_invalidated: set[tuple] = set()

    def tier(self, fleet: str, agent: str, action_type: str) -> str:
        """THE TIER READ: the strict triple; the default ESCALATE (the safe
        default AND the quarantine state); the quarantined agent →
        ESCALATE always."""
        if agent in self._quarantined:
            return "ESCALATE"
        return self._tiers.get((fleet, agent, action_type), "ESCALATE")

    def record_outcome(self, fleet: str, agent: str, action_type: str,
                       outcome_class: str, evidence_layer: str,
                       who: str = "autonomous",
                       decision_id: str | None = None) -> dict:
        """THE OUTCOME ROW (Clause 2): the attested outcome at its layer,
        with the WHO field (recovery's attention cost) and the layer check
        (WRONG-LAYER = a FAILURE row, not a discounted success)."""
        due_layer = DUE_LAYERS.get(action_type)
        layer_ok = (due_layer is None) or (evidence_layer == due_layer)
        effective_class = outcome_class if layer_ok else "wrong-layer-attestation"
        row = {"fleet": fleet, "agent": agent, "action_type": action_type,
               "outcome_class": effective_class, "evidence_layer": evidence_layer,
               "layer_ok": layer_ok, "who": who, "ts": time.time()}
        self._outcomes.setdefault((fleet, agent, action_type), []).append(row)
        self.store.append("outcome", row, decision_id=decision_id)
        return row

    def due_missing(self, fleet: str, agent: str, action_type: str,
                    due_count: int) -> list[str]:
        """THE ROW-DUE DETECTOR (the recording-layer silent-decline detector
        at the evidence layer): the delivered rows vs the DUE rows — the
        missing due row IS the disqualifying event, detected fail-closed.
        A systematically silent agent is now VISIBLE (the coverage
        denominator: rows delivered-and-attested / rows DUE)."""
        delivered = len(self._outcomes.get((fleet, agent, action_type), []))
        if delivered >= due_count:
            return []
        missing = due_count - delivered
        return [f"{agent}/{action_type}: {missing} of {due_count} due outcome "
                f"rows missing — the disqualifying event (the silent-failure "
                f"class, detected fail-closed)"]

    def evaluate_promotion(self, fleet: str, agent: str, action_type: str,
                           preconditions: dict) -> dict:
        """THE DETERMINISTIC PROMOTION (Clause 3): every precondition
        checkable; any unmet → hold with the reason. The evidence bar:
        only CORRECT-LAYER attestations count toward the promotion (the
        never-promote-on-volume rule)."""
        reasons = []
        if agent in self._quarantined:
            reasons.append("the agent is quarantined — the trust ledger is frozen")
        if not preconditions.get("dead_man_coverage"):
            reasons.append("no dead-man signal for this action class — "
                           "INELIGIBLE (the silent-decline incident is the proof)")
        if preconditions.get("reversibility_class") in (None, "unknown"):
            reasons.append("the reversibility class is not in the table — "
                           "promotion on an unknown class is impossible")
        if (fleet, agent, action_type) in self._drift_invalidated:
            reasons.append("drift invalidated the past attestation for this "
                           "class — the attestation floor resets")
        if action_type in NEVER_PROMOTE_CLASSES or \
                preconditions.get("action_class") in NEVER_PROMOTE_CLASSES:
            reasons.append("the never-promote ceiling: the destructive/"
                           "credential/exposure classes — frequency never earns it")
        # THE VOLUME RULE: only correct-layer attestations count.
        rows = self._outcomes.get((fleet, agent, action_type), [])
        correct = [r for r in rows if r["layer_ok"]]
        wrong = len(rows) - len(correct)
        min_correct = preconditions.get("min_correct_layer_rows", 5)
        if len(correct) < min_correct:
            reasons.append(f"only {len(correct)} correct-layer attestations "
                           f"(need {min_correct}); {wrong} wrong-layer rows "
                           f"count as FAILURE, not toward N")
        if reasons:
            return {"decision": "hold", "reasons": reasons}
        return {"decision": "promote", "reasons": [],
                "evidence_count": len(correct)}

    def promote(self, fleet: str, agent: str, action_type: str,
                to_tier: str, evidence_ref: str) -> dict:
        self._tiers[(fleet, agent, action_type)] = to_tier
        return self.store.append(
            "decision", {"kind": "promotion", "agent": agent,
                         "action_type": action_type, "to_tier": to_tier,
                         "evidence_ref": evidence_ref},
            decision_id=evidence_ref)

    def demote(self, fleet: str, agent: str, action_type: str,
               reason: str, evidence_ref: str, to_tier: str = "SUPERVISED") -> dict:
        """THE DIRECTIONALITY (R-SEC-12): executes Corvus-side regardless of
        the engine health — a fail-closed T1 that froze demotion would pin
        a compromised agent at its stolen tier. THE ONE-STEP DECAY (the
        trust-spec amendment): the evidence is stale, not that the agent
        sinned; the full reset stays reserved for the incidents/forgery."""
        self._tiers[(fleet, agent, action_type)] = to_tier
        return self.store.append(
            "decision", {"kind": "demotion", "agent": agent,
                         "action_type": action_type, "to_tier": to_tier,
                         "reason": reason, "evidence_ref": evidence_ref},
            decision_id=evidence_ref)

    def invalidate_on_drift(self, fleet: str, agent: str, action_type: str) -> None:
        """THE DRIFT RULE: drift invalidates ALL past attestation for the
        class — the attestation floor resets."""
        self._drift_invalidated.add((fleet, agent, action_type))

    def quarantine(self, agent: str, reason: str) -> dict:
        """THE QUARANTINE (Clause 9/R-SEC-8): the credential revocation
        freezes the trust ledger (no auto-promotion) and forces all sites
        ESCALATE. The refusal stream is the sensor; the release requires
        the promotion evidence standard."""
        self._quarantined.add(agent)
        return self.store.append("decision",
                                 {"kind": "quarantine", "agent": agent,
                                  "reason": reason})
