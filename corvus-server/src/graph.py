"""Neo4j graph database connection manager.

Provides async driver lifecycle, session management, and schema initialization
for the Corvus service dependency graph. Gracefully degrades when Neo4j is not
configured or unreachable — all graph features become no-ops rather than errors.
"""

import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from src.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None
_available: bool = False

# Constraints and indexes applied on first connect
_CONSTRAINTS = [
    "CREATE CONSTRAINT service_name IF NOT EXISTS FOR (s:Service) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT host_name IF NOT EXISTS FOR (h:Host) REQUIRE h.name IS UNIQUE",
    "CREATE CONSTRAINT gpu_host_index IF NOT EXISTS FOR (g:GPU) REQUIRE (g.host, g.index) IS UNIQUE",
    "CREATE CONSTRAINT network_name IF NOT EXISTS FOR (n:Network) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT ci_type_name IF NOT EXISTS FOR (c:CI) REQUIRE (c.type, c.name) IS UNIQUE",
    "CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE",
]

_INDEXES = [
    "CREATE INDEX ci_service IF NOT EXISTS FOR (c:CI) ON (c.service)",
    "CREATE INDEX ci_type IF NOT EXISTS FOR (c:CI) ON (c.type)",
]


async def init_graph() -> None:
    """Initialize the Neo4j async driver and apply schema constraints.

    If NEO4J_PASSWORD is empty, graph features are disabled with a warning.
    If the server is unreachable, graph features are disabled gracefully.
    """
    global _driver, _available

    if not NEO4J_PASSWORD:
        logger.warning("NEO4J_PASSWORD not set — graph features disabled")
        _available = False
        return

    try:
        _driver = AsyncGraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            max_connection_pool_size=25,
        )
        # Verify connectivity
        await _driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", NEO4J_URI)

        # Apply constraints and indexes
        async with _driver.session() as session:
            for stmt in _CONSTRAINTS + _INDEXES:
                await session.run(stmt)
            logger.info(
                "Applied %d constraints and %d indexes",
                len(_CONSTRAINTS),
                len(_INDEXES),
            )

        _available = True
    except Exception:
        logger.warning("Neo4j unavailable — graph features disabled", exc_info=True)
        _available = False
        if _driver:
            with contextlib.suppress(Exception):
                await _driver.close()
            _driver = None


async def close_graph() -> None:
    """Close the Neo4j driver and release resources."""
    global _driver, _available
    if _driver:
        try:
            await _driver.close()
            logger.info("Neo4j driver closed")
        except Exception:
            logger.debug("Error closing Neo4j driver", exc_info=True)
        finally:
            _driver = None
            _available = False


@asynccontextmanager
async def graph_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager yielding a Neo4j session.

    Raises RuntimeError if the graph database is not available.
    """
    if not _driver or not _available:
        raise RuntimeError("Graph database not available")

    session = _driver.session()
    try:
        yield session
    finally:
        await session.close()


def graph_available() -> bool:
    """Check whether the graph database is connected and ready."""
    return _available
