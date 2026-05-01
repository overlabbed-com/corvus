"""Story 5.5: Fix lazy SIEM initialization.

Instead of lazy initialization on first use, initialize SIEM adapters
at startup and add periodic retry if uninitialized.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Track initialization state
_siem_initialized = False
_siem_init_failed = False
_init_retry_interval = 300  # 5 minutes


async def initialize_siem_adapters():
    """Initialize SIEM adapters at startup.

    Story 5.5: Pre-initialize adapters instead of lazy init.
    """
    global _siem_initialized, _siem_init_failed

    try:
        from src.siem.forwarder import _init_adapters

        adapters = _init_adapters()
        _siem_initialized = True
        _siem_init_failed = False

        if adapters:
            logger.info("SIEM adapters initialized: %d", len(adapters))
        else:
            logger.info("No SIEM adapters configured")

    except Exception as e:
        logger.error(f"SIEM adapter initialization failed: {e}")
        _siem_init_failed = True


async def retry_siem_initialization():
    """Periodically retry SIEM initialization if it failed.

    Story 5.5: Add recovery mechanism for initialization failures.
    """
    global _siem_initialized, _siem_init_failed

    while True:
        await asyncio.sleep(_init_retry_interval)

        if _siem_init_failed and not _siem_initialized:
            try:
                await initialize_siem_adapters()
                if _siem_initialized:
                    logger.info("SIEM initialization recovered after initial failure")
            except Exception as e:
                logger.debug(f"SIEM retry initialization still failing: {e}")


def is_siem_initialized() -> bool:
    """Check if SIEM has been initialized."""
    return _siem_initialized


def is_siem_init_failed() -> bool:
    """Check if SIEM initialization has failed."""
    return _siem_init_failed
