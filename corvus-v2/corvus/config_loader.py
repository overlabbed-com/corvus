"""WP7 — the config loader: the delivery-indifferent interface (C6).

The loader's indifference was THE SaaS seam (the local deployment is the
SaaS deployment with git instead of API for config delivery). The loader
reads the fleet config + the register from a PATH — who shipped the file
(GitOps, the API control plane, or the BYO mounted artifact) is invisible
to the engine. Three delivery modes, one interface:

1. git-shipped (homelab/local — the estate's pattern)
2. API-managed (SaaS — the tenant control plane writes the same shape)
3. BYO env + mounted artifacts (the env-var culture: the operator mounts
   the files; no control-plane dependency)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigLoader:
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)

    def load_fleet_config(self, fleet_id: str) -> dict[str, Any]:
        """The fleet config: the mode (observe/enforce — the fleet config,
        NOT the contract), the quotas, the fail-policy overrides. The file
        shape is delivery-mode-invariant."""
        path = self.config_dir / f"{fleet_id}.json"
        if not path.exists():
            return {"mode": "observe", "quotas": {}, "fail_policies": {}}
        return json.loads(path.read_text())

    def load_register(self) -> dict:
        """The register: the compiler's SSOT (the catalog is DERIVED — the
        register seeds the catalog AFTER repair, audit first freeze
        second)."""
        path = self.config_dir / "decision-register.yaml"
        if not path.exists():
            return {}
        import yaml
        return yaml.safe_load(path.read_text()) or {}
