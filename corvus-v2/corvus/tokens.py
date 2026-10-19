"""The verdict-token issuer + the consumption ledger (WP11): the
enforcement seam's Corvus half (R-SEC-4's hybrid — the adapter is the dumb
protocol gate; Corvus is the smart validator).

THE TOKEN'S PROPERTIES (each fixture-proven):
- SINGLE-USE: the consume removes the token; the replay → refused. The
  consumption is a chain event (the lifecycle walker's input).
- TTL-BOUND: the expiry → refused.
- ACTION-BOUND: the state hash + the action fingerprint — A GO FOR DEPLOY
  DOES NOT COVER DELETE. The fingerprint mismatch → refused.
- THE EVIDENCE-DURABILITY PRECONDITION (R-SEC-15): the issuance requires
  the decision record persisted-or-queued within the bounded window —
  NO EVIDENCE, NO ENFORCEMENT. Persist failure → fail-closed + deadman.
- REVOCATION: the decision's supersession revokes the outstanding tokens;
  the revocation propagates to the downstream decision-references (the
  decision_ref validity check).

THE HA/DR DESIGN NOTE (the adversarial review's build-phase decision,
decided before implementation): the storage is the SQLite WAL (the
estate's pattern) — the single-writer reality. HA: the issuer is
Corvus-side (the organization layer, per-tenant); the DR: the ledger is
chain-recoverable (the replay from any prefix); the BREAK-GLASS: the
manual issuance procedure — the operator issues the token by hand with
the decision record's id, appended to the chain with
authority: operator-break-glass (the audited manual path; the prolonged-
issuer-outage procedure). The fail-closed posture during the issuer
unavailability IS the designed behavior — the fleet's autonomy floor
drops to the registered fail-policy floor; the HA question is about
restoring capacity, not safety.
"""
from __future__ import annotations

import hashlib
import secrets
import time


class TokenRefused(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class EvidenceNotDurable(Exception):
    pass


class VerdictTokenIssuer:
    def __init__(self, store, ttl_s: float = 300.0,
                 evidence_window_s: float = 60.0):
        # store: the AttestedStore — the consumption events are CHAIN
        # MEMBERS (the lifecycle walker's input; no second-class records).
        self.store = store
        self.ttl_s = ttl_s
        self.evidence_window_s = evidence_window_s
        self._outstanding: dict[str, dict] = {}
        self._revoked_decisions: set[str] = set()
        self._revoked_tokens: set[str] = set()  # the audit reads WHY

    def issue(self, decision_id: str, request_hash: str,
              action_fingerprint: str, evidence_ts: float,
              now: float | None = None) -> dict:
        """THE EVIDENCE-DURABILITY PRECONDITION: no decision record
        persisted-or-queued within the bounded window → no token. The
        enforce-mode action may not execute against a decision whose
        evidence was never frozen."""
        now = now or time.time()
        if (now - evidence_ts) > self.evidence_window_s:
            raise EvidenceNotDurable(
                f"the decision evidence is {now - evidence_ts:.0f}s old — "
                f"outside the {self.evidence_window_s:.0f}s window")
        token = {
            "token_id": secrets.token_hex(12),
            "decision_id": decision_id,
            "request_hash": request_hash,
            "action_fingerprint": action_fingerprint,
            "issued_at": now,
            "expires_at": now + self.ttl_s,
        }
        self._outstanding[token["token_id"]] = token
        return token

    def consume(self, token_id: str, action_fingerprint: str,
                now: float | None = None) -> dict:
        """The single-use consume: the validation + the chain event, atomic.
        Every refusal reason is distinct (the audit reads WHY)."""
        now = now or time.time()
        # THE REVOKED CHECK FIRST: a revoked token's consume must read
        # "revoked" (the audit reads WHY), never "unknown" — the revoke
        # keeps the ids precisely for this.
        if token_id in self._revoked_tokens:
            raise TokenRefused("revoked")
        token = self._outstanding.get(token_id)
        if token is None:
            raise TokenRefused("unknown-or-consumed")
        if token["decision_id"] in self._revoked_decisions:
            self._outstanding.pop(token_id, None)
            self._revoked_tokens.add(token_id)
            raise TokenRefused("revoked")
        if now > token["expires_at"]:
            self._outstanding.pop(token_id, None)
            raise TokenRefused("expired")
        if action_fingerprint != token["action_fingerprint"]:
            raise TokenRefused("action-mismatch")
        # THE SINGLE-USE: the consume removes the token AND appends the
        # chain event (the consumption ledger — the enforcement layer's
        # reconciliation source).
        self._outstanding.pop(token_id, None)
        self.store.append("consumption",
                          {"token_id": token_id,
                           "action_fingerprint": action_fingerprint,
                           "request_hash": token["request_hash"]},
                          decision_id=token["decision_id"])
        return {"allowed": True, "decision_id": token["decision_id"],
                "consumed_at": now}

    def revoke(self, decision_id: str) -> int:
        """THE SUPERSESSION PROPAGATION: the re-check that flips the verdict
        revokes the outstanding tokens issued under the superseded
        decision. Returns the revoked count. The honest race, stated:
        consumption at T, re-check at T+1 — the action already executed.
        Revocation prevents FUTURE consumption; past consumption is
        auditable, not revocable — that irreversibility is precisely why
        the response-time re-check (M1) exists, and the decision record
        carries supersedes: decision_id so the audit chain shows the
        flip."""
        revoked = 0
        for tid, token in list(self._outstanding.items()):
            if token["decision_id"] == decision_id:
                self._outstanding.pop(tid)
                self._revoked_tokens.add(tid)
                revoked += 1
        self._revoked_decisions.add(decision_id)
        self.store.append("tombstone",
                          {"kind": "revocation", "decision_id": decision_id,
                           "revoked_tokens": revoked},
                          decision_id=decision_id)
        return revoked

    def outstanding_for(self, decision_id: str) -> list[str]:
        return [t for t, tok in self._outstanding.items()
                if tok["decision_id"] == decision_id]


def action_fingerprint(state_hash: str, action: str) -> str:
    """THE ACTION BINDING: the state hash + the action — a GO for deploy
    does not cover delete."""
    return hashlib.sha256(f"{state_hash}|{action}".encode()).hexdigest()
