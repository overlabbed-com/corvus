"""Tests for idempotent schema migrations in init_db()."""

import tempfile
from pathlib import Path

import aiosqlite
import pytest


async def _column_exists(db_path: Path, table: str, column: str) -> bool:
    async with (
        aiosqlite.connect(str(db_path)) as db,
        db.execute(f"PRAGMA table_info({table})") as cursor,
    ):
        return any(row[1] == column for row in await cursor.fetchall())


@pytest.mark.asyncio
async def test_init_db_backfills_signature_column_on_existing_ops_events(monkeypatch):
    """init_db() must add `signature` to ops_events on DBs that predate GAP-8.

    Regression: deployed DBs that were created before the `signature` column
    was added to the schema kept the old ops_events definition. Event
    emission crashed with `OperationalError: table ops_events has no column
    named signature`. The fix is an idempotent `ALTER TABLE ... ADD COLUMN`
    in init_db()'s patch list.
    """
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("CORVUS_DATA_DIR", tmpdir)

    # Reimport config + database so DB_PATH picks up the temp dir.
    import importlib

    import src.config
    import src.database

    importlib.reload(src.config)
    importlib.reload(src.database)

    db_path = Path(tmpdir) / "corvus.db"

    # Seed a pre-GAP-8 ops_events table — current schema minus the
    # signature column. Matches the shape of deployed DBs that were
    # created before GAP-8 landed but have had mesh migration 001
    # applied (inline or via a prior init_db run).
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("""
            CREATE TABLE ops_events (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                source TEXT NOT NULL,
                type TEXT NOT NULL,
                target TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                data TEXT NOT NULL DEFAULT '{}',
                related_incident_id TEXT,
                related_change_id TEXT,
                related_problem_id TEXT,
                parent_event_id TEXT,
                authenticated_as TEXT,
                node_id TEXT DEFAULT 'local',
                hlc_timestamp TEXT,
                mesh_sync_status TEXT DEFAULT 'pending',
                synced_peers TEXT DEFAULT '[]'
            )
        """)
        await db.commit()

    assert not await _column_exists(db_path, "ops_events", "signature"), (
        "precondition: seeded table must not have signature column"
    )

    await src.database.init_db()

    assert await _column_exists(db_path, "ops_events", "signature"), (
        "init_db() must backfill the signature column on pre-GAP-8 DBs"
    )


@pytest.mark.asyncio
async def test_init_db_is_idempotent_on_fresh_db(monkeypatch):
    """init_db() must be safe to call twice on a fresh DB (no duplicate-column errors)."""
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("CORVUS_DATA_DIR", tmpdir)

    import importlib

    import src.config
    import src.database

    importlib.reload(src.config)
    importlib.reload(src.database)

    await src.database.init_db()
    # Second call should be a no-op — all ALTERs must silently pass since
    # the columns already exist from the first call.
    await src.database.init_db()

    db_path = Path(tmpdir) / "corvus.db"
    assert await _column_exists(db_path, "ops_events", "signature")
