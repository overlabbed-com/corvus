"""Gap sweep orchestrator — runs all periodic gap checks.

Thin wrapper that imports and calls individual gap detection functions.
Used by the /ops/gaps/sweep endpoint and the background sweep loop.
"""

import logging

from src.tasks.gap_detection import (
    check_cmdb_gaps,
    check_compliance_gaps,
    check_generic_fallback_triages,
    check_stale_findings,
    check_trust_gaps,
    check_unseen_services,
)
from src.tasks.trust_ledger import run_promotion_sweep

logger = logging.getLogger(__name__)


async def run_gap_sweep() -> dict:
    """Run all periodic gap checks. Returns summary."""
    results: dict[str, int] = {}

    unseen = await check_unseen_services()
    results["unseen_services"] = len(unseen)

    stale = await check_stale_findings()
    results["stale_findings"] = len(stale)

    cmdb = await check_cmdb_gaps()
    results["cmdb_gaps"] = len(cmdb)

    trust = await check_trust_gaps()
    results["trust_gaps"] = len(trust)

    fallbacks = await check_generic_fallback_triages()
    results["generic_fallbacks"] = len(fallbacks)

    compliance = await check_compliance_gaps()
    results["compliance_gaps"] = len(compliance)

    # Run trust promotion sweep (piggybacks on gap sweep schedule)
    promotion_result = await run_promotion_sweep()
    results["trust_promotions"] = promotion_result.get("promoted", 0)

    total = sum(v for k, v in results.items() if k != "trust_promotions")
    results["total_new_gaps"] = total

    if total:
        logger.info("Gap sweep found %d new gaps: %s", total, results)

    return results
