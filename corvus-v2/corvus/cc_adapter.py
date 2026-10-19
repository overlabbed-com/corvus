"""The Claude Code adapter (WP13): the hooks' replacement per the
transition plan — the v1 hook archive's integration surface, rebuilt on
the v2 edges.

THE V1 SURFACE (from the decommission archive — the inventory this
adapter covers):
- PreToolUse(Bash) → the conflict check (corvus-governance.py's role)
- PreToolUse(docker/portainer restart-class) → the same gate
- UserPromptSubmit → the workflow classification (corvus-lifecycle.py)
- PostToolUse(Bash) → the event emission (corvus-event-emit.py)
- PostToolUse(docker/portainer restart-class) → the same

THE V2 SHAPE: the same interception points; the ask goes to the v2
engine (the DecisionClient → C1); the outcome lands in the attested
store; the verdict-token consume gates the ENFORCE mode.

THE MODE CONTRACT: the observe mode NEVER blocks (the exit-0 with the
observe annotation — the answer recorded, the action proceeds); the
enforce mode gates (the deny without a valid verdict token — the
adapter is the dumb protocol gate, R-SEC-4's half). The mode lives in
the FLEET CONFIG (the engine is mode-blind).

THE CC PROTOCOL: the hook JSON on stdin; the JSON on stdout
({continue: true} | {decision: "block", reason} for PreToolUse).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time


class CCAdapter:
    def __init__(self, client, observe_mode, token_issuer=None,
                 mode: str = "observe"):
        # client: the DecisionClient (WP1). observe_mode: the ObserveMode
        # (WP15 — the attempt records, the coverage accrual). token_issuer:
        # the VerdictTokenIssuer (WP11 — the enforce mode's gate). The mode:
        # the FLEET CONFIG's (observe|enforce).
        self.client = client
        self.observe_mode = observe_mode
        self.token_issuer = token_issuer
        self.mode = mode
        # The restart-class tools (the v1's second PreToolUse registration):
        # the docker/portainer mutations ride the same gate.
        self.gated_tools = {"Bash", "DockerRestart", "PortainerRestart"}

    def pre_tool_use(self, hook_input: dict) -> dict:
        """THE PRE-ACTION GATE: the intercepted tool call → the C1 ask →
        the observe record → the mode's verdict."""
        tool_name = hook_input.get("tool_name", "")
        tool_input = hook_input.get("tool_input", {}) or {}
        if tool_name not in self.gated_tools:
            return {"continue": True}
        target = tool_input.get("target") or tool_input.get("command", "")[:80]
        action_type = tool_input.get("action_type", "deploy")
        agent = hook_input.get("agent", "claude-code")
        fleet = hook_input.get("fleet", "fleet-alpha")
        try:
            result = self.client.decide(
                fleet, {"target": target, "action_type": action_type},
                [{"site_id": "C1", "type": "choice",
                  "instructions": "May the actor proceed on this target right now?",
                  "criteria": {"GO": "clean", "CAUTION": "attention",
                               "STOP": "critical"}}],
                fail_policies={"C1": "fail-closed:CAUTION"})
            engine_answer = result["answers"].get("C1", {})
            decision_id = result.get("request_hash")
        except Exception as exc:  # the engine unreachable: the fail policy applied  # noqa: BLE001
            self.observe_mode.record_attempt(fleet, agent, "C1",
                                             engine_error=str(exc)[:200])
            # THE OBSERVE MODE NEVER BLOCKS — even on the engine outage, the
            # attempt is recorded and the action proceeds (the F9 fix: the
            # gap is visible, not silent).
            return {"continue": True,
                    "observe": {"outcome": "engine-unavailable",
                                "fail_policy_applied": True}}
        if self.mode == "observe":
            self.observe_mode.record_attempt(fleet, agent, "C1",
                                             engine_answer=engine_answer,
                                             decision_id=decision_id)
            # THE OBSERVE MODE NEVER BLOCKS: the exit-0 with the annotation.
            return {"continue": True,
                    "observe": {"answer": engine_answer.get("answer"),
                                "recorded": True}}
        # THE ENFORCE MODE: the verdict-token gate (the adapter is the dumb
        # protocol gate — no valid token, no execution).
        if self.token_issuer is None:
            return {"decision": "block",
                    "reason": "enforce mode without the token issuer — "
                              "fail-closed (the misconfiguration, not a bypass)"}
        state_hash = hashlib.sha256(json.dumps(
            {"target": target, "action_type": action_type},
            sort_keys=True).encode()).hexdigest()[:16]
        fp = hashlib.sha256(f"{state_hash}|{action_type}".encode()).hexdigest()
        try:
            token = self.token_issuer.issue(
                decision_id=decision_id, request_hash=result.get("request_hash", ""),
                action_fingerprint=fp, evidence_ts=time.time())
            consume = self.token_issuer.consume(token["token_id"], fp)
            return {"continue": True,
                    "enforce": {"decision_id": decision_id,
                                "consumed": consume["allowed"]}}
        except Exception as exc:  # noqa: BLE001
            return {"decision": "block",
                    "reason": f"the enforcement gate refused: {exc}"}

    def post_tool_use(self, hook_input: dict) -> dict:
        """THE OUTCOME EMISSION: the action's outcome lands in the attested
        store (the v1 event-emit's role, now chain-membered)."""
        tool_name = hook_input.get("tool_name", "")
        outcome = hook_input.get("outcome", {})
        record = {"kind": "cc-outcome", "tool_name": tool_name,
                  "outcome": outcome, "ts": None}
        entry = self.observe_mode.store.append("outcome", record)
        return {"continue": True, "recorded": {"seq": entry["seq"]}}

    def handle(self, hook_event: str, hook_input: dict) -> dict:
        """The CC hook dispatch (the settings.json's command target)."""
        if hook_event == "PreToolUse":
            return self.pre_tool_use(hook_input)
        if hook_event == "PostToolUse":
            return self.post_tool_use(hook_input)
        return {"continue": True}


def main():
    """The CC hook entry: the JSON on stdin, the JSON on stdout. The
    settings.json wiring pipes the hook JSON to this handler with the
    event name; the DEPLOYED wiring (OPS-READINESS's shape) injects the
    configured adapter — the local stub always continues."""
    sys.stdin.read()
    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
