"""Test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Use temp directory for test database
_test_dir = tempfile.mkdtemp()
os.environ["CORVUS_DATA_DIR"] = _test_dir

# Enable dev mode so tests run without auth by default.
# Tests that need auth (test_auth_middleware.py) configure keys via monkeypatch.
os.environ["CORVUS_DEV_MODE"] = "true"

from src import config  # noqa: E402
from src.app import app  # noqa: E402
from src.database import init_db  # noqa: E402
from src.middleware import auth as _auth_module  # noqa: E402

config.API_KEYS.clear()
_auth_module.API_KEYS.clear()
from src.modules.loader import load_modules, register_module_routers  # noqa: E402
from src.modules.loader import registry as module_registry  # noqa: E402
from src.runbooks.loader import registry  # noqa: E402

# Load runbooks once at module level
_runbook_dir = Path(__file__).parent.parent / "runbooks"
if _runbook_dir.exists() and not registry.list_all():
    registry.load_directory(_runbook_dir)

# Load modules once at module level
_modules_dir = Path(__file__).parent.parent / "modules"
if _modules_dir.exists() and not module_registry.list_all():
    load_modules(_modules_dir)
    register_module_routers(app)


@pytest.fixture
async def client():
    """Async test client with fresh database."""
    await init_db()

    # Clear all data between tests for isolation
    from src.database import get_db

    db = await get_db()
    try:
        for table in (
            "ops_changes",
            "ops_events",
            "ops_incidents",
            "ops_problems",
            "ops_cmdb",
            "ops_audit_log",
            "ops_triage_log",
            "ops_pending_steps",
            "ops_plan_steps",
            "ops_plans",
            "ops_trust_ledger",
            "ops_knowledge",
            "ops_knowledge_fts",
        ):
            await db.execute(f"DELETE FROM {table}")  # nosec B608 - Table name from allowlist
        await db.commit()
    finally:
        await db.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
