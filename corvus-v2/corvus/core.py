"""The CCB's spine: the event ingest, the change windows, and the conflict
check — the product's most defensible surface as a first-class contract.

Embodies: ADR-001 (the single binary, the fleet config), ADR-002 (the
data-driven vocabulary, the strict OCSF shape), ADR-003 (the trust tiers in
the conflict answer), ADR-007 (the HLC ordering, the exact target matching,
the normalized targets). No homelab wiring anywhere (criterion 5).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import FleetConfig
from .hlc import HLC
from .state import State


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sign_event(payload: dict, key: str) -> str:
    """The HMAC-SHA256 event signing (salvaged from event_signing.py — the
    evidence chain's guarantee, per fleet key)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class CorvusCore:
    def __init__(self, config: FleetConfig, state: State, decisions: Any = None):
        self.config = config
        self.state = state
        self.hlc = HLC(config.node_id)
        self.decisions = decisions  # the DecisionClient (ADR: the engine seam)

    # ── the event ingest (ADR-002: the strict shape, the data vocabulary) ──

    def ingest_event(self, event: dict, authenticated_as: str | None = None) -> dict:
        etype = event.get("type", "")
        if etype not in self.config.event_types:
            known = sorted(self.config.event_types)
            raise ValueError(f"Unknown event type; valid_types={known}")
        if not event.get("target"):
            raise ValueError("Event requires a target")
        ts = self.hlc.now()
        row = {
            "id": str(uuid.uuid4()),
            "hlc_timestamp": ts.to_string(),
            "timestamp": _now_iso(),
            "source": event.get("source", "unknown"),
            "type": etype,
            "target": event["target"],
            "severity": event.get("severity", "info"),
            "data": json.dumps(event.get("data", {})),
            "authenticated_as": authenticated_as,
        }
        row["signature"] = sign_event(row, self.config.api_key)
        self.state.execute(
            "INSERT INTO ops_events (id, hlc_timestamp, timestamp, source, type, target,"
            " severity, data, authenticated_as, signature) VALUES (?,?,?,?,?,?,?,?,?,?)",
            tuple(row.values()),
        )
        return {"id": row["id"], "hlc_timestamp": row["hlc_timestamp"],
                "type": etype, "target": row["target"], "signature": row["signature"]}

    def query_events(self, target: str | None = None, limit: int = 100) -> list[dict]:
        if target:
            rows = self.state.execute(
                "SELECT * FROM ops_events WHERE target = ? ORDER BY hlc_timestamp DESC LIMIT ?",
                (target, limit),
            )
        else:
            rows = self.state.execute(
                "SELECT * FROM ops_events ORDER BY hlc_timestamp DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    # ── the change windows (the CCB's record) ─────────────────────────────

    def open_change(self, change: dict, authenticated_as: str | None = None) -> dict:
        cid = "CHG-" + uuid.uuid4().hex[:8].upper()
        targets = change.get("targets") or []
        if not targets:
            raise ValueError("Change requires at least one target")
        expires_at = change.get("expires_at")
        self.state.execute(
            "INSERT INTO ops_changes (id, created_at, created_by, status, description,"
            " rollback_plan, auto_expire, expires_at, authenticated_as)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, _now_iso(), change.get("created_by", authenticated_as or "unknown"),
             "active", change.get("description", ""), change.get("rollback_plan"),
             1 if change.get("auto_expire", True) else 0, expires_at, authenticated_as),
        )
        for t in targets:
            self.state.execute(
                "INSERT OR IGNORE INTO change_targets (change_id, target) VALUES (?,?)",
                (cid, t),
            )
        self.ingest_event({"type": "change.started", "target": targets[0],
                           "source": change.get("created_by", "unknown"),
                           "data": {"change_id": cid, "targets": targets}},
                          authenticated_as)
        return {"id": cid, "targets": targets, "status": "active"}

    def active_changes_for(self, target: str) -> list[dict]:
        rows = self.state.execute(
            "SELECT c.* FROM ops_changes c JOIN change_targets t ON c.id = t.change_id"
            " WHERE t.target = ? AND c.status = 'active'",
            (target,),
        )
        return [dict(r) for r in rows]

    # ── the conflict check: the first-class contract ──────────────────────

    def conflict_check(self, target: str, action_type: str | None = None,
                       actor: str | None = None) -> dict:
        """GO / CAUTION / STOP from the active changes, the incidents-class
        events on the target, and the trust tier. THE product decision."""
        active = self.active_changes_for(target)
        recent = self.state.execute(
            "SELECT type, severity, data FROM ops_events WHERE target = ? AND"
            " (type LIKE 'incident.%' OR severity IN ('critical','high','error'))"
            " ORDER BY hlc_timestamp DESC LIMIT 10",
            (target,),
        )
        # The trust tier (ADR-003): the per-(actor, action_type) tier from the
        # trust table if present; ESCALATE stays the safe default.
        tier_rows = self.state.execute(
            "SELECT tier, stats FROM ops_trust WHERE agent = ? AND action_type = ?",
            (actor or "unknown", action_type or "unknown"),
        )
        trust_tier = tier_rows[0]["tier"] if tier_rows else "ESCALATE"

        # The C1 decision site (the register): the engine decides when reachable;
        # the registered fail policy (fail-closed → CAUTION) applies when not.
        # The deterministic conditions below are the engine's criteria, restated
        # locally so the degraded path reproduces them exactly.
        local_reasons: list[str] = []
        if recent and any(r["severity"] in ("critical", "high", "error") for r in recent):
            local_reasons.append("recent critical/high event on target")
        if active:
            local_reasons.append(f"active change window: {active[0]['id']} by {active[0]['created_by']}")
        if trust_tier == "ESCALATE":
            local_reasons.append(f"trust tier ESCALATE for {actor or 'unknown'}/{action_type or 'unknown'}")

        recommendation = "GO"
        reasons: list[str] = []
        degraded = False
        if self.decisions is not None:
            site = {
                "type": "choice",
                "instructions": "May the actor proceed on this target right now?",
                "criteria": {
                    "GO": "no active changes, no recent critical events, trust is not ESCALATE",
                    "CAUTION": "an active change window, an ESCALATE trust tier, or a moderate recent event — proceed with attention",
                    "STOP": "a recent critical/high event, or an active change AND a critical condition on the target",
                },
            }
            state_in = {
                "target": target, "action_type": action_type, "actor": actor,
                "active_changes": [{"id": c["id"], "created_by": c["created_by"]} for c in active],
                "recent_severity": recent[0]["severity"] if recent else None,
                "trust_tier": trust_tier,
            }
            result = self.decisions.decide(
                self.config.name, state_in,
                [dict(site, site_id="C1")],
                fail_policies={"C1": "fail-closed:CAUTION"},
            )
            answer = result["answers"].get("C1", {}).get("answer", "CAUTION")
            degraded = bool(result.get("degraded"))
            if degraded:
                reasons.append("engine unreachable — the fail-closed default applied")
                if local_reasons:
                    reasons.extend(local_reasons)
                recommendation = "CAUTION" if answer == "CAUTION" and not local_reasons else "STOP" if any("critical" in r for r in local_reasons) else answer
                if local_reasons and any("critical" in r for r in local_reasons):
                    recommendation = "STOP"
                elif local_reasons:
                    recommendation = "CAUTION"
                else:
                    recommendation = answer
            else:
                recommendation = answer
                reasons.extend(local_reasons)
        else:
            # The no-engine mode: the deterministic ladder (the v2's original
            # behavior — the degraded path reproduces exactly this).
            if recent and any(r["severity"] in ("critical", "high", "error") for r in recent):
                recommendation = "STOP"
                reasons.append("recent critical/high event on target")
            if active:
                if recommendation == "GO":
                    recommendation = "CAUTION"
                    reasons.append(f"active change window: {active[0]['id']} by {active[0]['created_by']}")
                else:
                    recommendation = "STOP"
                    reasons.append("active change window AND recent critical event")
            if trust_tier == "ESCALATE" and recommendation == "GO":
                recommendation = "CAUTION"
                reasons.append(f"trust tier ESCALATE for {actor or 'unknown'}/{action_type or 'unknown'}")
        return {
            "target": target,
            "action_type": action_type,
            "actor": actor,
            "recommendation": recommendation,
            "reasons": reasons,
            "active_changes": [{"id": c["id"], "created_by": c["created_by"]} for c in active],
            "trust_tier": trust_tier,
            "engine_degraded": degraded,
            "checked_at": _now_iso(),
        }
