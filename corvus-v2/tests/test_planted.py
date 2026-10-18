"""The prove-collection control: a planted must-pass test. Its presence in
the CI's run log (11 passed) proves the test gate COLLECTS new tests — the
guard against a gate that ships green while never running what was added.
Deleted after the verdict (the throwaway)."""
from corvus.config import FleetConfig
from corvus.core import CorvusCore
from corvus.state import State


def test_planted_must_run_in_ci():
    cfg = FleetConfig(name="plant-fleet", node_id="n", api_key="k")
    core = CorvusCore(cfg, State(":memory:"))
    r = core.ingest_event({"type": "session.started", "target": "planter"})
    assert r["type"] == "session.started"
