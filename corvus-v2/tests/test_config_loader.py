"""WP7's tests — the delivery-indifferent interface: the same file shape
loads identically no matter who shipped it (the SaaS seam, pre-wired)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from corvus.config_loader import ConfigLoader  # noqa: E402


def test_fleet_config_loads_from_path(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "fleet-alpha.json").write_text(json.dumps(
        {"mode": "observe", "quotas": {"per_minute": 60}}))
    loader = ConfigLoader(d)
    cfg = loader.load_fleet_config("fleet-alpha")
    assert cfg["mode"] == "observe"
    assert cfg["quotas"]["per_minute"] == 60


def test_missing_config_defaults_conservative(tmp_path):
    """The missing fleet config → the conservative defaults (observe mode)
    — the fail-closed-defaults shape applies to config absence too."""
    loader = ConfigLoader(tmp_path)
    cfg = loader.load_fleet_config("fleet-unknown")
    assert cfg["mode"] == "observe"
    assert cfg["fail_policies"] == {}


def test_register_loads_from_path(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    (d / "decision-register.yaml").write_text("version: 2\nsites: {}\n")
    loader = ConfigLoader(d)
    reg = loader.load_register()
    assert reg["version"] == 2
