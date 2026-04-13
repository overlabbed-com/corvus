"""Configuration drift detection sweep task.

Compares declared state (from GitOps) with running state (from container inspection)
and creates gap problems when drift is detected.

Schedule: Every 10 minutes
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from src.database import get_db
from src.discovery.deploy_manager import DeclaredConfig, DriftReport, check_drift

logger = logging.getLogger(__name__)


async def run_drift_detection_loop() -> None:
    """Main loop for drift detection sweep.
    
    Runs every 10 minutes, checking all registered services for drift.
    Creates gap problems when drift is detected.
    """
    logger.info("Starting drift detection sweep loop")
    
    while True:
        try:
            await _run_drift_sweep()
        except Exception as e:
            logger.error(f"Drift detection sweep failed: {e}", exc_info=True)
        
        # Wait 10 minutes
        await asyncio.sleep(600)


async def _run_drift_sweep() -> None:
    """Run a single drift detection sweep."""
    logger.info("Starting drift detection sweep")
    
    db = await get_db()
    try:
        # Get all services with declared state
        cursor = await db.execute(
            """SELECT name, declared_image, declared_healthcheck, 
                      declared_env_hash, declared_networks, last_declared_at
               FROM ops_cmdb 
               WHERE declared_image IS NOT NULL"""
        )
        rows = await cursor.fetchall()
        
        if not rows:
            logger.info("No services with declared state found")
            return
        
        logger.info(f"Checking {len(rows)} services for drift")
        
        drift_count = 0
        for row in rows:
            service_name = row["name"]
            
            # Build declared config from database row
            declared = DeclaredConfig(
                image=row["declared_image"],
                healthcheck=row["declared_healthcheck"],
                env_hash=row["declared_env_hash"],
                networks=row["declared_networks"] if row["declared_networks"] else None,
            )
            
            # Check drift (running state will be None until container inspection is implemented)
            report = await check_drift(
                service_name=service_name,
                declared=declared,
                running=None,  # TODO: Implement container inspection
            )
            
            # For now, skip drift detection without running state
            # This will be enabled when container inspection is implemented
            if report.has_drift:
                drift_count += 1
                logger.warning(f"Drift detected in {service_name}: {report.drift_fields}")
                
                # Create gap problem for drift
                await _create_drift_gap_problem(service_name, report)
        
        logger.info(f"Drift sweep complete: {drift_count} services with drift")
        
    finally:
        await db.close()


async def _create_drift_gap_problem(
    service_name: str,
    report: DriftReport,
) -> None:
    """Create a gap problem for detected drift.
    
    Args:
        service_name: Service with drift
        report: Drift report with details
    """
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()
        
        # Generate problem title and description
        drift_fields = ", ".join(report.drift_fields)
        title = f"Config drift detected: {service_name}"
        description = (
            f"Running configuration differs from declared GitOps state.\n\n"
            f"Drift fields: {drift_fields}\n"
            f"Severity: {report.severity}\n\n"
            f"Declared:\n"
            f"  Image: {report.declared.image if report.declared else 'N/A'}\n"
            f"  Healthcheck: {report.declared.healthcheck if report.declared else 'N/A'}\n\n"
            f"Running:\n"
            f"  Image: {report.running.image if report.running else 'Unknown'}\n"
            f"  Healthcheck: {report.running.healthcheck if report.running else 'Unknown'}\n\n"
            f"Recommended action: Re-deploy from GitOps to restore declared state"
        )
        
        # Check if gap problem already exists
        cursor = await db.execute(
            """SELECT id FROM ops_problems 
               WHERE pattern = ? AND target = ? AND status = 'identified'""",
            (f"gap:coverage:config-drift", service_name),
        )
        existing = await cursor.fetchone()
        
        if existing:
            # Update existing problem
            await db.execute(
                """UPDATE ops_problems SET
                   title = ?, description = ?, updated_at = ?
                   WHERE id = ?""",
                (title, description, now, existing["id"]),
            )
            logger.info(f"Updated existing drift problem for {service_name}")
        else:
            # Create new problem
            problem_id = f"PROB-DRIFT-{service_name.replace('-', '_')}"
            await db.execute(
                """INSERT INTO ops_problems
                   (id, created_at, status, title, pattern, severity, target, recommended_fix)
                   VALUES (?, ?, 'identified', ?, ?, ?, ?, ?)""",
                (
                    problem_id,
                    now,
                    title,
                    f"gap:coverage:config-drift",
                    "high" if report.severity == "high" else "medium",
                    service_name,
                    "Re-deploy service from GitOps to restore declared configuration",
                ),
            )
            logger.info(f"Created drift gap problem {problem_id} for {service_name}")
        
        await db.commit()
        
    finally:
        await db.close()


async def run_drift_sweep_once() -> None:
    """Run a single drift sweep (for testing or manual trigger)."""
    await _run_drift_sweep()
