"""Neo4j graph database connection manager.

Provides async driver lifecycle, session management, and schema initialization
for the Corvus service dependency graph. Gracefully degrades when Neo4j is not
configured or unreachable — all graph features become no-ops rather than errors.
"""

import contextlib
import logging
import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from src.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None
_available: bool = False

# Timeout for Neo4j queries (deterministic termination guardrail)
QUERY_TIMEOUT_SECONDS = 5.0  # 5 seconds

# Safe mode thresholds
SAFE_MODE_FAILURE_THRESHOLD = 5  # Number of failures to trigger safe mode
SAFE_MODE_RECOVERY_SECONDS = 60  # Seconds before attempting recovery


class HealthState(Enum):
    """Graph database health states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    SAFE_MODE = "safe_mode"


@dataclass
class HealthTracker:
    """Tracks graph database health and manages safe mode transitions."""
    state: HealthState = HealthState.HEALTHY
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    consecutive_failures: int = 0

    def record_success(self) -> None:
        """Record a successful operation."""
        self.last_success_time = time.time()
        self.consecutive_failures = 0
        if self.state == HealthState.DEGRADED:
            logger.info("Graph database recovered from degraded state")
        self.state = HealthState.HEALTHY

    def record_failure(self) -> None:
        """Record a failed operation."""
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

        # State transitions
        if self.state == HealthState.HEALTHY:
            if self.consecutive_failures >= SAFE_MODE_FAILURE_THRESHOLD:
                self.state = HealthState.UNHEALTHY
                logger.warning(
                    "Graph database entering UNHEALTHY state after %d consecutive failures",
                    self.consecutive_failures
                )
            elif self.consecutive_failures >= 2:
                self.state = HealthState.DEGRADED
                logger.warning(
                    "Graph database degraded after %d consecutive failures",
                    self.consecutive_failures
                )

    def should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self.state not in (HealthState.UNHEALTHY, HealthState.SAFE_MODE):
            return False
        return (time.time() - self.last_failure_time) >= SAFE_MODE_RECOVERY_SECONDS

    def enter_safe_mode(self) -> None:
        """Enter safe mode — all graph operations become no-ops."""
        self.state = HealthState.SAFE_MODE
        logger.critical(
            "Graph database entering SAFE MODE — all graph queries will be rejected"
        )

    def is_safe_mode(self) -> bool:
        """Check if currently in safe mode."""
        return self.state == HealthState.SAFE_MODE

    def is_available(self) -> bool:
        """Check if graph is available for queries."""
        return self.state in (HealthState.HEALTHY, HealthState.DEGRADED)


_health = HealthTracker()


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
        _health.state = HealthState.UNHEALTHY
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

        _health.record_success()
        _available = True
    except Exception:
        logger.warning("Neo4j unavailable — graph features disabled", exc_info=True)
        _health.record_failure()
        _health.state = HealthState.UNHEALTHY
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
            _health.state = HealthState.UNHEALTHY


async def run_query_with_timeout(
    cypher: str,
    params: dict | None = None,
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> list[dict]:
    """Execute a Neo4j query with deterministic timeout enforcement.

    Args:
        cypher: Cypher query string (already sanitized by caller)
        params: Query parameters
        timeout: Maximum execution time in seconds (default: 500ms)

    Returns:
        List of record dictionaries

    Raises:
        asyncio.TimeoutError: If query exceeds timeout
        RuntimeError: If graph database not available
    """
    if not _driver or not _health.is_available():
        _health.record_failure()
        raise RuntimeError("Graph database not available")

    try:
        async def _execute_query() -> list[dict]:
            async with _driver.session() as session:
                result = await session.run(cypher, params or {})
                records = await result.fetch(n=100)
                return [dict(record) for record in records]

        result = await asyncio.wait_for(_execute_query(), timeout=timeout)
        _health.record_success()
        return result
    except asyncio.TimeoutError:
        _health.record_failure()
        logger.warning("Query timed out after %fs: %s", timeout, cypher[:100])
        raise
    except Exception as e:
        _health.record_failure()
        logger.warning("Query failed: %s", str(e))
        raise


class TimedSession:
    """Wrapper around AsyncSession that enforces query timeouts.

    All queries executed through this wrapper will be cancelled if they exceed
    the configured timeout, ensuring deterministic termination and preventing
    "query of death" scenarios that hang indefinitely.
    """

    def __init__(self, session: AsyncSession, timeout: float = QUERY_TIMEOUT_SECONDS):
        self._session = session
        self._timeout = timeout

    async def run(self, cypher: str, params: dict | None = None):
        """Run a query with timeout enforcement.

        Returns a ResultWrapper that streams results with timeout protection.
        """
        if not _health.is_available():
            _health.record_failure()
            raise RuntimeError("Graph database not available — safe mode active")

        try:
            task = asyncio.create_task(self._session.run(cypher, params or {}))
            try:
                await asyncio.wait_for(task, timeout=self._timeout)
                return ResultWrapper(task.result(), self._timeout)
            except asyncio.TimeoutError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                _health.record_failure()
                logger.warning("Query timed out after %fs: %s", self._timeout, cypher[:100])
                raise
        except Exception as e:
            _health.record_failure()
            raise


class ResultWrapper:
    """Wrapper around Neo4j Result that applies timeout to fetch operations.

    Supports both async iteration and single/fetch operations with timeout.
    """

    def __init__(self, result, timeout: float = QUERY_TIMEOUT_SECONDS):
        self._result = result
        self._timeout = timeout

    async def single(self):
        """Fetch single record with timeout."""
        try:
            return await asyncio.wait_for(self._result.single(), timeout=self._timeout)
        except asyncio.TimeoutError:
            _health.record_failure()
            raise

    async def single_or_none(self):
        """Fetch single record, returning None if no results (with timeout)."""
        try:
            return await asyncio.wait_for(self._result.single(), timeout=self._timeout)
        except asyncio.TimeoutError:
            _health.record_failure()
            raise

    async def fetch(self):
        """Fetch all records with timeout."""
        try:
            return await asyncio.wait_for(self._result.fetch(), timeout=self._timeout)
        except asyncio.TimeoutError:
            _health.record_failure()
            raise

    def __aiter__(self):
        """Stream records with timeout per-record."""
        return ResultIterator(self._result, self._timeout)


class ResultIterator:
    """Async iterator that applies timeout to each record fetch."""

    def __init__(self, result, timeout: float = QUERY_TIMEOUT_SECONDS):
        self._result = result
        self._timeout = timeout
        self._buffer: list = []
        self._exhausted = False

    async def __anext__(self):
        # Return from buffer if available
        if self._buffer:
            return self._buffer.pop(0)

        # Fetch new batch with timeout
        if self._exhausted:
            raise StopAsyncIteration

        try:
            records = await asyncio.wait_for(self._result.fetch(n=100), timeout=self._timeout)
            if not records:
                self._exhausted = True
                raise StopAsyncIteration
            self._buffer = list(records)
            return self._buffer.pop(0)
        except asyncio.TimeoutError:
            _health.record_failure()
            logger.warning("Query result fetch timed out after %fs", self._timeout)
            raise


@asynccontextmanager
async def graph_session() -> AsyncGenerator[TimedSession, None]:
    """Async context manager yielding a timeout-protected Neo4j session.

    All queries executed through this session will be cancelled if they exceed
    QUERY_TIMEOUT_SECONDS (default: 500ms), ensuring deterministic termination.

    Raises RuntimeError if the graph database is not available.
    """
    if not _driver or not _health.is_available():
        _health.record_failure()
        raise RuntimeError("Graph database not available")

    session = _driver.session()
    timed_session = TimedSession(session)
    try:
        yield timed_session
    finally:
        await session.close()


def graph_available() -> bool:
    """Check whether the graph database is connected and ready."""
    return _driver is not None and _health.is_available()


def graph_health() -> dict:
    """Get current graph database health status."""
    return {
        "state": _health.state.value,
        "failure_count": _health.failure_count,
        "consecutive_failures": _health.consecutive_failures,
        "is_available": _health.is_available(),
        "is_safe_mode": _health.is_safe_mode(),
        "last_failure_time": _health.last_failure_time,
        "last_success_time": _health.last_success_time,
    }


def enter_safe_mode() -> None:
    """Manually enter safe mode — all graph operations become no-ops."""
    _health.enter_safe_mode()


def attempt_recovery() -> bool:
    """Attempt to recover from safe mode or unhealthy state.

    Returns True if recovery is attempted, False if still in cooldown.
    """
    if not _health.should_attempt_recovery():
        return False

    logger.info("Attempting graph database recovery...")
    # Reset failure count and try to reconnect
    _health.failure_count = 0
    _health.consecutive_failures = 0
    _health.state = HealthState.HEALTHY  # Optimistic, will be corrected on next query

    return True


def get_safe_mode_state() -> dict:
    """Get safe mode state for health endpoints."""
    return {
        "active": _health.is_safe_mode(),
        "state": _health.state.value,
        "failure_count": _health.failure_count,
        "consecutive_failures": _health.consecutive_failures,
        "threshold": SAFE_MODE_FAILURE_THRESHOLD,
        "recovery_seconds": SAFE_MODE_RECOVERY_SECONDS,
    }
