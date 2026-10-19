"""The tests' path bootstrap + the engine-wired core fixture."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from corvus.config import FleetConfig
from corvus.core import CorvusCore
from corvus.decisions import DecisionClient
from corvus.state import State


@pytest.fixture
def core():
    cfg = FleetConfig(name="fleet-alpha", node_id="node-1", api_key="k",
                      custom_event_types=["deploy.canary"])
    return CorvusCore(cfg, State(":memory:"))


@pytest.fixture
def core_with_engine():
    """The core wired to a REAL running shim (the integration fixture)."""
    import threading
    import time

    import uvicorn

    from corvus.engine_shim import app
    t = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=8935, log_level="error"),
        daemon=True)
    t.start()
    time.sleep(1.0)
    cfg = FleetConfig(name="fleet-alpha", node_id="node-1", api_key="k")
    core = CorvusCore(cfg, State(":memory:"),
                      decisions=DecisionClient(base_url="http://127.0.0.1:8935", engine_key="k"))
    yield core, core.decisions
