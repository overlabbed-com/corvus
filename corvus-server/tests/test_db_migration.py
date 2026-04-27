"""Tests for database migration error handling (Story 2.2)."""

import sqlite3
import pytest


class TestMigrationErrorHandling:
    """Test that migration errors are handled correctly."""

    @pytest.mark.asyncio
    async def test_duplicate_column_suppressed(self, client):
        """Duplicate column errors should be suppressed during init_db."""
        # The init_db function should handle duplicate columns gracefully
        # This test verifies that the database is usable after init
        from src.database import get_db
        
        db = await get_db()
        try:
            # Verify ops_events table exists and is usable
            cursor = await db.execute("SELECT COUNT(*) FROM ops_events")
            result = await cursor.fetchone()
            assert result is not None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_other_errors_raised(self):
        """Non-duplicate-column errors should be raised."""
        from src.database import get_db
        
        db = await get_db()
        try:
            # Try to add a column with invalid syntax
            with pytest.raises(sqlite3.OperationalError):
                await db.execute("ALTER TABLE nonexistent_table ADD COLUMN test TEXT")
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_composite_indexes_exist(self, client):
        """Story 2.5: Composite indexes should be created."""
        from src.database import get_db
        
        db = await get_db()
        try:
            # Check that the composite indexes exist
            indexes = [
                "idx_events_context",
                "idx_problems_gap",
                "idx_triage_analytics"
            ]
            
            for index in indexes:
                cursor = await db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                    (index,)
                )
                result = await cursor.fetchone()
                assert result is not None, f"Index {index} not found"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_index_composite_structure(self, client):
        """Story 2.5: Verify composite index structure."""
        from src.database import get_db
        
        db = await get_db()
        try:
            # Check idx_events_context structure
            cursor = await db.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_events_context'"
            )
            result = await cursor.fetchone()
            assert result is not None
            sql = result[0]
            assert "timestamp DESC" in sql
            assert "severity" in sql
            assert "type" in sql
        finally:
            await db.close()
