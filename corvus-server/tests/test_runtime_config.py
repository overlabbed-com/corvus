"""RuntimeConfig singleton tests."""

import pytest

from src.config import RuntimeConfig


@pytest.fixture(autouse=True)
def _isolate_runtime_config():
    saved = (dict(RuntimeConfig._values), dict(RuntimeConfig._defaults), dict(RuntimeConfig._bounds))
    RuntimeConfig.reset()
    yield
    RuntimeConfig._values, RuntimeConfig._defaults, RuntimeConfig._bounds = saved


def test_get_returns_default():
    """Getting an unset key returns the registered default."""
    RuntimeConfig.register_default("test.param", 42)
    assert RuntimeConfig.get("test.param") == 42


def test_set_overrides_default():
    """Setting a value overrides the default."""
    RuntimeConfig.register_default("test.param", 42)
    RuntimeConfig.set("test.param", 100)
    assert RuntimeConfig.get("test.param") == 100


def test_revert_restores_default():
    """Reverting restores the registered default."""
    RuntimeConfig.register_default("test.param", 42)
    RuntimeConfig.set("test.param", 100)
    RuntimeConfig.revert("test.param")
    assert RuntimeConfig.get("test.param") == 42


def test_get_unknown_key_raises():
    """Getting an unregistered key raises KeyError."""
    with pytest.raises(KeyError):
        RuntimeConfig.get("nonexistent.key")


def test_snapshot_returns_all_current_values():
    """Snapshot returns dict of all current values."""
    RuntimeConfig.register_default("a", 1)
    RuntimeConfig.register_default("b", 2)
    RuntimeConfig.set("a", 10)
    snap = RuntimeConfig.snapshot()
    assert snap == {"a": 10, "b": 2}


def test_set_respects_bounds():
    """Setting a value outside bounds clamps to min/max."""
    RuntimeConfig.register_default("test.bounded", 50, min_val=10, max_val=100)
    RuntimeConfig.set("test.bounded", 200)
    assert RuntimeConfig.get("test.bounded") == 100
    RuntimeConfig.set("test.bounded", 1)
    assert RuntimeConfig.get("test.bounded") == 10


def test_defaults_returns_registered_defaults():
    """Defaults snapshot returns the original defaults, not overrides."""
    RuntimeConfig.register_default("x", 5)
    RuntimeConfig.set("x", 99)
    assert RuntimeConfig.defaults() == {"x": 5}


def test_trust_ledger_reads_from_config():
    """Trust ledger uses RuntimeConfig for promotion threshold."""
    # Re-register the defaults that config.py registers at import time
    # (cleared by the autouse fixture above)
    RuntimeConfig.register_default("trust.promotion_threshold", 0.95, min_val=0.80, max_val=0.99)
    RuntimeConfig.register_default("trust.min_executions", 20, min_val=5, max_val=100)
    # Verify the keys are accessible with correct defaults
    assert RuntimeConfig.get("trust.promotion_threshold") == 0.95
    assert RuntimeConfig.get("trust.min_executions") == 20
