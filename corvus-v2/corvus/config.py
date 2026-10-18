"""The fleet configuration (ADR-001: the fleet identity is configuration).

Generic — no homelab wiring anywhere (criterion 5). The vocabulary is data
(ADR-002): the built-in lifecycle types ship; the fleet registers custom
types in its config.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# The built-in event vocabulary: the core lifecycle families (the old code's
# well-designed types, reviewed keep). Fleets extend via event_types.json.
BUILTIN_EVENT_TYPES = [
    # Change lifecycle
    "change.started", "change.completed", "change.failed", "change.expired",
    # Incident lifecycle
    "incident.opened", "incident.investigating", "incident.resolved",
    "incident.escalated",
    # Remediation
    "remediation.restart", "remediation.config_fix", "remediation.credential_rotation",
    # Detection
    "sweep.completed", "sweep.anomaly", "anomaly.detected",
    # Investigation
    "llm.investigation_started", "llm.investigation_completed",
    # Decisions
    "action.approved", "action.denied",
    # Trust (ADR-003: the tier changes are auditable events)
    "trust.promoted", "trust.demoted",
    # Sessions
    "session.started", "session.ended",
]


@dataclass
class FleetConfig:
    name: str                    # the fleet's identity (ADR-001)
    node_id: str                 # this deployment's HLC node identity
    api_key: str                 # the HMAC signing key (per-fleet, per ADR-002)
    custom_event_types: list[str] = field(default_factory=list)

    @property
    def event_types(self) -> frozenset:
        return frozenset(BUILTIN_EVENT_TYPES) | frozenset(self.custom_event_types)


def load_config(config_path: str | None = None) -> FleetConfig:
    """Load the fleet config: the JSON file if given, else the environment.

    The env contract (the product's 12-factor shape):
      CORVUS_FLEET_NAME, CORVUS_NODE_ID, CORVUS_API_KEY,
      CORVUS_CUSTOM_EVENT_TYPES (a JSON array)
    """
    if config_path and os.path.exists(config_path):
        with open(config_path) as fh:
            raw = json.loads(fh.read())
        return FleetConfig(
            name=raw["name"], node_id=raw.get("node_id", raw["name"]),
            api_key=raw["api_key"],
            custom_event_types=raw.get("custom_event_types", []),
        )
    return FleetConfig(
        name=os.environ.get("CORVUS_FLEET_NAME", "default-fleet"),
        node_id=os.environ.get("CORVUS_NODE_ID", "local"),
        api_key=os.environ.get("CORVUS_API_KEY", "dev-key-change-me"),
        custom_event_types=json.loads(os.environ.get("CORVUS_CUSTOM_EVENT_TYPES", "[]")),
    )
