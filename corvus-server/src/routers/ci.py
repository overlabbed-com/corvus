"""Configuration Item (CI) API endpoints."""

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from src.database import get_db
from src.graph import graph_available, graph_session
from src.models.ci import (
    CIExpiryQueryResponse,
    CIExpiryResponse,
    CIImpactResponse,
    CIRequest,
    CIResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/cmdb/ci", tags=["cmdb-ci"])


@router.post("", status_code=201)
async def register_ci(ci: CIRequest, request: Request):
    """Register a new Configuration Item."""
    db = await get_db()
    try:
        now = datetime.now(UTC).isoformat()

        # Check if CI already exists
        cursor = await db.execute("SELECT * FROM ops_ci WHERE name = ?", (ci.name,))
        existing = await cursor.fetchone()

        if existing:
            # Update existing CI
            await db.execute(
                """UPDATE ops_ci SET
                   ci_type = ?, service_name = ?, expires_at = ?,
                   parent_ci = ?, operational_status = ?,
                   metadata = ?, updated_at = ?
                   WHERE name = ?""",
                (
                    ci.ci_type,
                    ci.service_name,
                    ci.expires_at,
                    ci.parent_ci,
                    ci.operational_status,
                    json.dumps(ci.metadata),
                    now,
                    ci.name,
                ),
            )
            logger.info(f"Updated CI: {ci.name}")
        else:
            # Insert new CI
            await db.execute(
                """INSERT INTO ops_ci
                   (name, ci_type, service_name, expires_at, parent_ci,
                    operational_status, metadata, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ci.name,
                    ci.ci_type,
                    ci.service_name,
                    ci.expires_at,
                    ci.parent_ci,
                    ci.operational_status,
                    json.dumps(ci.metadata),
                    now,
                    now,
                ),
            )
            logger.info(f"Registered CI: {ci.name} (type: {ci.ci_type})")

        await db.commit()

        # Create CI node in Neo4j if available
        if graph_available():
            try:
                async with graph_session() as session:
                    await session.run(
                        """
                        MERGE (ci:CI {name: $name})
                        SET ci.ci_type = $ci_type,
                            ci.service_name = $service_name,
                            ci.expires_at = $expires_at,
                            ci.parent_ci = $parent_ci,
                            ci.operational_status = $operational_status,
                            ci.metadata = $metadata,
                            ci.updated_at = $updated_at
                        """,
                        name=ci.name,
                        ci_type=ci.ci_type,
                        service_name=ci.service_name,
                        expires_at=ci.expires_at,
                        parent_ci=ci.parent_ci,
                        operational_status=ci.operational_status,
                        metadata=json.dumps(ci.metadata),
                        updated_at=now,
                    )

                    # Link to service if specified
                    if ci.service_name:
                        await session.run(
                            """
                            MATCH (s:Service {name: $service_name})
                            MATCH (ci:CI {name: $ci_name})
                            MERGE (s)-[:USES]->(ci)
                            """,
                            service_name=ci.service_name,
                            ci_name=ci.name,
                        )

                    # Link to parent CI if specified
                    if ci.parent_ci:
                        await session.run(
                            """
                            MATCH (ci:CI {name: $name})
                            MATCH (parent:CI {name: $parent_ci})
                            MERGE (ci)-[:BELONGS_TO]->(parent)
                            """,
                            name=ci.name,
                            parent_ci=ci.parent_ci,
                        )
            except Exception as e:
                logger.warning(f"Failed to update Neo4j for CI {ci.name}: {e}")

        # Return updated CI
        cursor = await db.execute("SELECT * FROM ops_ci WHERE name = ?", (ci.name,))
        row = await cursor.fetchone()
        return CIResponse.from_row(row)
    finally:
        await db.close()


@router.get("")
async def list_cis(
    ci_type: str = Query(None, description="Filter by CI type"),
    status: str = Query(None, description="Filter by operational status"),
    expiring: bool = Query(None, description="Show only expiring CIs (within 30 days)"),
):
    """List all Configuration Items with optional filters."""
    db = await get_db()
    try:
        query = "SELECT * FROM ops_ci WHERE 1=1"
        params = []

        if ci_type:
            query += " AND ci_type = ?"
            params.append(ci_type)

        if status:
            query += " AND operational_status = ?"
            params.append(status)

        if expiring:
            now = datetime.now(UTC)
            cutoff = now + timedelta(days=30)
            query += " AND expires_at IS NOT NULL AND expires_at <= ?"
            params.append(cutoff.isoformat())

        query += " ORDER BY expires_at DESC NULLS LAST, name"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        return [CIResponse.from_row(row) for row in rows]
    finally:
        await db.close()


@router.get("/expiring")
async def get_expiring_cis(
    days: int = Query(30, ge=1, le=365, description="Days to look ahead"),
    request: Request = None,
):
    """Get CIs expiring within specified days."""
    db = await get_db()
    try:
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days)

        # Query CIs expiring between now and cutoff
        cursor = await db.execute(
            """SELECT * FROM ops_ci
               WHERE expires_at IS NOT NULL
               AND expires_at > ?
               AND expires_at <= ?
               ORDER BY expires_at""",
            (now.isoformat(), cutoff.isoformat()),
        )
        rows = await cursor.fetchall()

        expiring = []
        for row in rows:
            try:
                expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                days_left = (expiry - now).days
                expiring.append(
                    CIExpiryResponse(
                        name=row["name"],
                        ci_type=row["ci_type"],
                        expires_at=row["expires_at"],
                        days_left=days_left,
                        service_name=row["service_name"],
                        operational_status=row["operational_status"],
                    )
                )
            except (ValueError, TypeError):
                continue

        # Query already expired CIs
        cursor = await db.execute(
            """SELECT * FROM ops_ci
               WHERE expires_at IS NOT NULL
               AND expires_at < ?
               AND operational_status != 'expired'
               ORDER BY expires_at""",
            (now.isoformat(),),
        )
        expired_rows = await cursor.fetchall()

        expired = []
        for row in expired_rows:
            try:
                expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                days_left = (expiry - now).days
                expired.append(
                    CIExpiryResponse(
                        name=row["name"],
                        ci_type=row["ci_type"],
                        expires_at=row["expires_at"],
                        days_left=days_left,
                        service_name=row["service_name"],
                        operational_status=row["operational_status"],
                    )
                )
            except (ValueError, TypeError):
                continue

        # Categorize by urgency
        expiring_7 = [ci for ci in expiring if ci.days_left <= 7]
        expiring_30 = [ci for ci in expiring if 7 < ci.days_left <= 30]
        expiring_90 = [ci for ci in expiring if 30 < ci.days_left <= 90]

        return CIExpiryQueryResponse(
            expiring_in_7_days=expiring_7,
            expiring_in_30_days=expiring_30,
            expiring_in_90_days=expiring_90,
            already_expired=expired,
        )
    finally:
        await db.close()


@router.get("/{name}")
async def get_ci(name: str, request: Request):
    """Get CI details by name."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM ops_ci WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="CI not found")

        # Get relationships from Neo4j if available
        relationships = {}
        if graph_available():
            try:
                async with graph_session() as session:
                    # Find services using this CI
                    result = await session.run(
                        """
                        MATCH (s:Service)-[:USES]->(ci:CI {name: $ci_name})
                        RETURN s.name as service_name
                        """,
                        ci_name=name,
                    )
                    services_using = [r["service_name"] async for r in result]

                    # Find parent CI
                    result = await session.run(
                        """
                        MATCH (ci:CI {name: $ci_name})-[:BELONGS_TO]->(parent:CI)
                        RETURN parent.name as parent_name
                        """,
                        ci_name=name,
                    )
                    parent = None
                    async for r in result:
                        parent = r["parent_name"]
                        break

                    # Find child CIs
                    result = await session.run(
                        """
                        MATCH (child:CI)-[:BELONGS_TO]->(ci:CI {name: $ci_name})
                        RETURN child.name as child_name
                        """,
                        ci_name=name,
                    )
                    children = [r["child_name"] async for r in result]

                    relationships = {
                        "used_by": services_using,
                        "parent": parent,
                        "children": children,
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch relationships for CI {name}: {e}")

        return CIResponse.from_row(row, relationships)
    finally:
        await db.close()


@router.get("/{name}/impact")
async def get_ci_impact(name: str, request: Request):
    """Get impact analysis for a CI."""
    db = await get_db()
    try:
        # Verify CI exists
        cursor = await db.execute("SELECT * FROM ops_ci WHERE name = ?", (name,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="CI not found")

        indirect_dependents = []
        services_using = []
        risk_level = "medium"

        if graph_available():
            try:
                async with graph_session() as session:
                    # Find direct services using this CI
                    result = await session.run(
                        """
                        MATCH (s:Service)-[:USES]->(ci:CI {name: $ci_name})
                        RETURN s.name as service_name
                        """,
                        ci_name=name,
                    )
                    services_using = [r["service_name"] async for r in result]

                    # Find indirect dependents (services that depend on services using this CI)
                    result = await session.run(
                        """
                        MATCH (s:Service)-[:USES]->(ci:CI {name: $ci_name})
                        MATCH (dep:Service)-[:DEPENDS_ON]->(s)
                        RETURN DISTINCT dep.name as dependent
                        """,
                        ci_name=name,
                    )
                    indirect_dependents = [r["dependent"] async for r in result]

                    # Calculate risk level based on critical services
                    if services_using:
                        cursor = await db.execute(
                            """SELECT name, critical FROM ops_cmdb WHERE name IN ({})""".format(
                                ",".join("?" * len(services_using))
                            ),
                            services_using,
                        )
                        critical_count = sum(1 for r in await cursor.fetchall() if r["critical"])
                        if critical_count > 0 or len(services_using) >= 3:
                            risk_level = "high"
                        elif len(services_using) >= 2:
                            risk_level = "medium"
                        else:
                            risk_level = "low"
            except Exception as e:
                logger.warning(f"Failed to fetch impact for CI {name}: {e}")
        else:
            # Fallback: check if any service has this CI in dependencies
            cursor = await db.execute(
                "SELECT name, dependencies FROM ops_cmdb WHERE dependencies LIKE ?",
                (f'%"{name}"%',),
            )
            services_using = [r["name"] for r in await cursor.fetchall()]

        return CIImpactResponse(
            ci_name=name,
            ci_type=row["ci_type"],
            direct_dependents=services_using,
            indirect_dependents=indirect_dependents,
            services_using=services_using,
            change_window_required=len(services_using) > 0,
            risk_level=risk_level,
        )
    finally:
        await db.close()
