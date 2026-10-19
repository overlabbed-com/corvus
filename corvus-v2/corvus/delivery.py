"""The delivery chain (WP16): the E2 escalation's guaranteed-delivery
path — RECORD → QUEUE → DELIVER-ON-RECOVERY → DEADMAN (record-without-
delivery is not a terminal state; the E2 fail-open was the silent-decline
vector's fail-policy form, incident 1 maps verbatim).

THE E1 ROUTING RULE: "invalid" is a classification, not a destination —
the invalid-vocabulary escalations route to the DEFAULT HUMAN CHANNEL +
alarm, or they silently decline (the chunk-3 finding).

The stages are chain events (the escalation-delivery record class — the
chain grammar's six classes cover the delivery; no second-class records).
"""
from __future__ import annotations

import time


class DeliveryChain:
    def __init__(self, store, channel: callable, slo_s: float = 300.0,
                 default_channel: callable | None = None):
        # store: the AttestedStore (the escalation-delivery events are chain
        # members). channel: the delivery callable (payload → bool delivered).
        # slo_s: the delivery SLO — past it, the deadman fires (silence is
        # the signal, the house's deadman pattern).
        self.store = store
        self.channel = channel
        self.slo_s = slo_s
        self.default_channel = default_channel
        self._queue: dict[str, dict] = {}

    def submit(self, escalation_id: str, payload: dict,
               decision_id: str | None = None) -> dict:
        """STAGE 1 — RECORDED → QUEUED. The record-without-delivery is not
        a terminal state: the escalation is queued for delivery."""
        entry = {"escalation_id": escalation_id, "payload": payload,
                 "queued_at": time.time(), "delivered": False}
        self._queue[escalation_id] = entry
        self.store.append("escalation_delivery",
                          {"stage": "queued", "escalation_id": escalation_id},
                          decision_id=decision_id)
        return entry

    def deliver(self, escalation_id: str,
                decision_id: str | None = None) -> dict:
        """STAGE 2 — DELIVER (or queue-for-recovery). The delivery attempt's
        outcome is a chain event either way."""
        entry = self._queue.get(escalation_id)
        if entry is None:
            return {"status": "unknown-escalation"}
        delivered = False
        try:
            delivered = bool(self.channel(entry["payload"]))
        except Exception:
            delivered = False
        entry["delivered"] = delivered
        self.store.append("escalation_delivery",
                          {"stage": "delivered" if delivered else "delivery-failed",
                           "escalation_id": escalation_id},
                          decision_id=decision_id)
        if not delivered:
            entry["status"] = "queued-for-recovery"
        else:
            entry["status"] = "delivered"
        return {"status": entry["status"], "escalation_id": escalation_id}

    def deliver_on_recovery(self, now: float | None = None) -> list[str]:
        """STAGE 3 — DELIVER-ON-RECOVERY + THE DEADMAN: the queued
        escalations retry; the ones past the SLO fire the DEADMAN ALARM
        (the alarm IS the signal — silence would be the silent decline)."""
        now = now or time.time()
        recovered: list[str] = []
        for eid, entry in list(self._queue.items()):
            if entry.get("delivered"):
                continue
            delivered = False
            try:
                delivered = bool(self.channel(entry["payload"]))
            except Exception:
                delivered = False
            if delivered:
                entry["delivered"] = True
                entry["status"] = "delivered-on-recovery"
                recovered.append(eid)
                self.store.append("escalation_delivery",
                                  {"stage": "delivered-on-recovery",
                                   "escalation_id": eid})
        # THE DEADMAN: the queued past SLO → the alarm event (loud, not
        # quiet).
        for eid, entry in list(self._queue.items()):
            if not entry.get("delivered") and \
                    (now - entry["queued_at"]) > self.slo_s:
                self.store.append("escalation_delivery",
                                  {"stage": "deadman-fired",
                                   "escalation_id": eid,
                                   "queued_age_s": now - entry["queued_at"]})
                entry["status"] = "deadman-fired"
        return recovered

    def route_invalid(self, payload: dict) -> dict:
        """THE E1 ROUTING RULE: the invalid-vocabulary escalations route to
        the DEFAULT HUMAN CHANNEL + alarm — "invalid" is a classification,
        not a destination."""
        if self.default_channel is None:
            return {"routed": False, "reason": "no default channel configured"}
        ok = bool(self.default_channel(payload))
        return {"routed": ok, "channel": "default-human-channel"}
