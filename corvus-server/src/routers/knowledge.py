"""Knowledge management API — operational memory via FTS5.

Indexes resolved incidents, triage results, and problem records so agents
can search past resolutions before escalating.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi import Query as FastQuery
from pydantic import BaseModel

from src.database import get_db

router = APIRouter(prefix="/ops/knowledge", tags=["knowledge"])


class KnowledgeEntry(BaseModel):
    title: str
    content: str
    source_type: str = "manual"
    source_id: str | None = None
    tags: list[str] = []
    service_type: str | None = None
    target: str | None = None


class KnowledgeSearchResult(BaseModel):
    id: str
    title: str
    content: str
    source_type: str
    source_id: str | None
    tags: list[str]
    service_type: str | None
    target: str | None
    rank: float
    created_at: str


class KnowledgeUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    governance_order: int | None = None


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_knowledge(entry: KnowledgeEntry, request: Request) -> dict[str, Any]:
    """Create a knowledge entry (manual or programmatic)."""
    # Governance entries require admin role
    if entry.source_type == "governance":
        auth = getattr(request.state, "auth", None)
        if not auth or auth.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Writing source_type='governance' requires admin role. "
                "Use 'governance-proposed' to propose rules for review.",
            )

    entry_id = f"KNW-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(UTC).isoformat()

    db = await get_db()
    try:
        await db.execute(
            """INSERT INTO ops_knowledge
               (id, source_type, source_id, title, content, tags, service_type, target, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                entry.source_type,
                entry.source_id,
                entry.title,
                entry.content,
                json.dumps(entry.tags),
                entry.service_type,
                entry.target,
                now,
            ),
        )
        # Sync FTS index
        await _sync_fts(db, entry_id)

        # Record governance history on create
        if entry.source_type == "governance":
            auth = getattr(request.state, "auth", None)
            changed_by = auth.identity if auth else "unknown"
            await _record_governance_history(db, entry_id, entry.content, changed_by)

        await db.commit()
        return {"id": entry_id, "created_at": now}
    finally:
        await db.close()


@router.get("/search")
async def search_knowledge(
    q: str = FastQuery(..., description="Search query"),
    source_type: str | None = FastQuery(None, description="Filter by source type"),
    service_type: str | None = FastQuery(None, description="Filter by service type"),
    target: str | None = FastQuery(None, description="Filter by target"),
    limit: int = FastQuery(10, ge=1, le=50),
) -> list[dict[str, Any]]:
    """Search operational knowledge using full-text search.

    Returns results ranked by relevance. Use this before escalating — the
    answer may already exist from a past resolution.
    """
    db = await get_db()
    try:
        # Build FTS query — escape special chars for safety
        fts_query = _escape_fts_query(q)
        if not fts_query.strip():
            return []

        # Base FTS query with rank
        sql = """
            SELECT k.id, k.title, k.content, k.source_type, k.source_id,
                   k.tags, k.service_type, k.target, k.created_at,
                   fts.rank
            FROM ops_knowledge_fts fts
            JOIN ops_knowledge k ON k.id = fts.knowledge_id
            WHERE ops_knowledge_fts MATCH ?
        """
        params: list[Any] = [fts_query]

        if source_type:
            sql += " AND k.source_type = ?"
            params.append(source_type)
        if service_type:
            sql += " AND k.service_type = ?"
            params.append(service_type)
        if target:
            sql += " AND k.target = ?"
            params.append(target)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = await db.execute_fetchall(sql, params)
        return [_row_to_result(row) for row in rows]
    finally:
        await db.close()


@router.get("/{entry_id}/history")
async def get_governance_history(entry_id: str) -> list[dict[str, Any]]:
    """Get change history for a knowledge entry."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT id, entry_id, content_hash, changed_by, changed_at, diff_summary "
            "FROM governance_history WHERE entry_id = ? ORDER BY changed_at",
            (entry_id,),
        )
        return [
            {
                "id": row[0],
                "entry_id": row[1],
                "content_hash": row[2],
                "changed_by": row[3],
                "changed_at": row[4],
                "diff_summary": row[5],
            }
            for row in rows
        ]
    finally:
        await db.close()


@router.patch("/{entry_id}")
async def update_knowledge(entry_id: str, update: KnowledgeUpdate, request: Request) -> dict[str, Any]:
    """Update a knowledge entry. Governance entries require admin role."""
    db = await get_db()
    try:
        row = await db.execute_fetchall("SELECT * FROM ops_knowledge WHERE id = ?", (entry_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")

        existing = _row_to_dict(row[0])

        # Governance entries require admin to update
        if existing["source_type"] == "governance":
            auth = getattr(request.state, "auth", None)
            if not auth or auth.role != "admin":
                raise HTTPException(status_code=403, detail="Updating governance entries requires admin role")

        now = datetime.now(UTC).isoformat()
        updates = []
        params = []

        if update.title is not None:
            updates.append("title = ?")
            params.append(update.title)
        if update.content is not None:
            updates.append("content = ?")
            params.append(update.content)
        if update.tags is not None:
            updates.append("tags = ?")
            params.append(json.dumps(update.tags))
        if update.governance_order is not None:
            updates.append("governance_order = ?")
            params.append(update.governance_order)

        if not updates:
            return {"id": entry_id, "updated": False}

        updates.append("updated_at = ?")
        params.append(now)
        params.append(entry_id)

        await db.execute(
            f"UPDATE ops_knowledge SET {', '.join(updates)} WHERE id = ?",  # nosec B608
            params,
        )
        await _sync_fts(db, entry_id)

        # Record governance history
        if existing["source_type"] == "governance":
            content = update.content if update.content is not None else existing["content"]
            auth = getattr(request.state, "auth", None)
            changed_by = auth.identity if auth else "unknown"
            await _record_governance_history(db, entry_id, content, changed_by)

        await db.commit()
        return {"id": entry_id, "updated_at": now}
    finally:
        await db.close()


@router.get("/{entry_id}")
async def get_knowledge(entry_id: str) -> dict[str, Any]:
    """Get a specific knowledge entry."""
    db = await get_db()
    try:
        row = await db.execute_fetchall("SELECT * FROM ops_knowledge WHERE id = ?", (entry_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")
        return _row_to_dict(row[0])
    finally:
        await db.close()


@router.get("")
async def list_knowledge(
    source_type: str | None = None,
    service_type: str | None = None,
    limit: int = FastQuery(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List knowledge entries with optional filters."""
    db = await get_db()
    try:
        sql = "SELECT * FROM ops_knowledge WHERE 1=1"
        params: list[Any] = []

        if source_type:
            sql += " AND source_type = ?"
            params.append(source_type)
        if service_type:
            sql += " AND service_type = ?"
            params.append(service_type)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await db.execute_fetchall(sql, params)
        return [_row_to_dict(row) for row in rows]
    finally:
        await db.close()


@router.delete("/{entry_id}")
async def delete_knowledge(entry_id: str) -> dict[str, str]:
    """Delete a knowledge entry."""
    db = await get_db()
    try:
        row = await db.execute_fetchall("SELECT id FROM ops_knowledge WHERE id = ?", (entry_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge entry not found")

        # Remove from FTS first, then main table
        await db.execute("DELETE FROM ops_knowledge_fts WHERE knowledge_id = ?", (entry_id,))
        await db.execute("DELETE FROM ops_knowledge WHERE id = ?", (entry_id,))
        await db.commit()
        return {"deleted": entry_id}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Auto-indexing: extract knowledge from operational records
# ---------------------------------------------------------------------------


async def index_resolved_incident(incident_id: str) -> str | None:
    """Extract knowledge from a resolved incident.

    Called automatically when an incident is resolved with a root cause
    and investigation summary.
    """
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT id, target, title, description, root_cause,
                      investigation_summary, remediation_applied
               FROM ops_incidents WHERE id = ? AND status = 'resolved'""",
            (incident_id,),
        )
        if not rows:
            return None

        inc = rows[0]
        # Only index if there's useful resolution data
        root_cause = inc[4] or ""
        investigation = inc[5] or ""
        remediation = inc[6] or ""
        if not (root_cause or investigation or remediation):
            return None

        # Build knowledge content
        parts = [f"Incident: {inc[3]}"]
        if inc[3]:  # description
            parts.append(f"Description: {inc[3]}")
        if root_cause:
            parts.append(f"Root cause: {root_cause}")
        if investigation:
            parts.append(f"Investigation: {investigation}")
        if remediation:
            parts.append(f"Remediation: {remediation}")

        content = "\n".join(parts)
        title = f"Resolved: {inc[3]}"  # title field

        # Check if already indexed
        existing = await db.execute_fetchall(
            "SELECT id FROM ops_knowledge WHERE source_type = 'incident' AND source_id = ?",
            (incident_id,),
        )
        if existing:
            # Update existing entry
            now = datetime.now(UTC).isoformat()
            await db.execute(
                "UPDATE ops_knowledge SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, content, now, existing[0][0]),
            )
            await _sync_fts(db, existing[0][0])
            await db.commit()
            return existing[0][0]

        # Look up service type from CMDB
        service_type = await _lookup_service_type(db, inc[1])

        entry_id = f"KNW-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(UTC).isoformat()
        await db.execute(
            """INSERT INTO ops_knowledge
               (id, source_type, source_id, title, content, tags, service_type, target, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                "incident",
                incident_id,
                title,
                content,
                json.dumps(["incident", "resolution"]),
                service_type,
                inc[1],  # target
                now,
            ),
        )
        await _sync_fts(db, entry_id)
        await db.commit()
        return entry_id
    finally:
        await db.close()


async def index_triage_result(triage_id: str) -> str | None:
    """Extract knowledge from a completed triage execution."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT id, target, service_type, runbook_name, action_type,
                      diagnosis, confidence, outcome
               FROM ops_triage_log WHERE id = ? AND outcome IN ('success', 'failure')""",
            (triage_id,),
        )
        if not rows:
            return None

        triage = rows[0]
        diagnosis = triage[5] or ""
        if not diagnosis:
            return None

        outcome = triage[7]
        action = triage[4]
        title = f"Triage {outcome}: {triage[3]} on {triage[1]}"
        content = (
            f"Service type: {triage[2]}\n"
            f"Runbook: {triage[3]}\n"
            f"Action: {action}\n"
            f"Diagnosis: {diagnosis}\n"
            f"Confidence: {triage[6]}\n"
            f"Outcome: {outcome}"
        )

        # Check if already indexed
        existing = await db.execute_fetchall(
            "SELECT id FROM ops_knowledge WHERE source_type = 'triage' AND source_id = ?",
            (triage_id,),
        )
        if existing:
            return existing[0][0]

        entry_id = f"KNW-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(UTC).isoformat()
        tags = ["triage", outcome, action]

        await db.execute(
            """INSERT INTO ops_knowledge
               (id, source_type, source_id, title, content, tags, service_type, target, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                "triage",
                triage_id,
                title,
                content,
                json.dumps(tags),
                triage[2],  # service_type
                triage[1],  # target
                now,
            ),
        )
        await _sync_fts(db, entry_id)
        await db.commit()
        return entry_id
    finally:
        await db.close()


async def index_problem_record(problem_id: str) -> str | None:
    """Extract knowledge from a problem record with root cause."""
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            """SELECT id, title, pattern, root_cause, recommended_fix,
                      workaround, correlated_incidents, workstream
               FROM ops_problems WHERE id = ?""",
            (problem_id,),
        )
        if not rows:
            return None

        prob = rows[0]
        root_cause = prob[3] or ""
        fix = prob[4] or ""
        workaround = prob[5] or ""
        if not (root_cause or fix or workaround):
            return None

        parts = [f"Problem: {prob[1]}"]
        if prob[2]:  # pattern
            parts.append(f"Pattern: {prob[2]}")
        if root_cause:
            parts.append(f"Root cause: {root_cause}")
        if fix:
            parts.append(f"Recommended fix: {fix}")
        if workaround:
            parts.append(f"Workaround: {workaround}")

        incidents = json.loads(prob[6]) if prob[6] else []
        if incidents:
            parts.append(f"Correlated incidents: {', '.join(incidents)}")

        content = "\n".join(parts)
        title = f"Problem: {prob[1]}"

        # Check if already indexed
        existing = await db.execute_fetchall(
            "SELECT id FROM ops_knowledge WHERE source_type = 'problem' AND source_id = ?",
            (problem_id,),
        )
        if existing:
            now = datetime.now(UTC).isoformat()
            await db.execute(
                "UPDATE ops_knowledge SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, content, now, existing[0][0]),
            )
            await _sync_fts(db, existing[0][0])
            await db.commit()
            return existing[0][0]

        entry_id = f"KNW-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(UTC).isoformat()
        tags = ["problem"]
        if prob[7]:  # workstream
            tags.append(prob[7])

        await db.execute(
            """INSERT INTO ops_knowledge
               (id, source_type, source_id, title, content, tags, service_type, target, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                "problem",
                problem_id,
                title,
                content,
                json.dumps(tags),
                None,
                None,
                now,
            ),
        )
        await _sync_fts(db, entry_id)
        await db.commit()
        return entry_id
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _record_governance_history(db, entry_id: str, content: str, changed_by: str) -> None:
    """Record a governance entry change in the audit trail."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """INSERT INTO governance_history (entry_id, content_hash, changed_by, changed_at)
           VALUES (?, ?, ?, ?)""",
        (entry_id, content_hash, changed_by, now),
    )


def _escape_fts_query(query: str) -> str:
    """Escape FTS5 special characters and format as a phrase or term query."""
    # Remove FTS5 operators that could cause syntax errors
    for char in ['"', "'", "(", ")", "*", ":", "^", "{", "}", "~"]:
        query = query.replace(char, " ")
    # Split into terms and rejoin — handles multiple spaces
    terms = query.split()
    if not terms:
        return ""
    # Use implicit AND (FTS5 default)
    return " ".join(terms)


async def _sync_fts(db, entry_id: str) -> None:
    """Sync a knowledge entry to the FTS index."""
    # Delete existing FTS entry if any
    await db.execute(
        "DELETE FROM ops_knowledge_fts WHERE knowledge_id = ?",
        (entry_id,),
    )
    # Insert fresh
    await db.execute(
        "INSERT INTO ops_knowledge_fts(knowledge_id, title, body, tags, service_type, target) "
        "SELECT id, title, content, tags, service_type, target "
        "FROM ops_knowledge WHERE id = ?",
        (entry_id,),
    )


async def _lookup_service_type(db, target: str) -> str | None:
    """Look up service type from CMDB."""
    rows = await db.execute_fetchall("SELECT service_type FROM ops_cmdb WHERE name = ?", (target,))
    return rows[0][0] if rows else None


def _row_to_dict(row) -> dict[str, Any]:
    """Convert a knowledge row to dict."""
    return {
        "id": row[0],
        "source_type": row[1],
        "source_id": row[2],
        "title": row[3],
        "content": row[4],
        "tags": json.loads(row[5]) if row[5] else [],
        "service_type": row[6],
        "target": row[7],
        "created_at": row[8],
        "updated_at": row[9] if len(row) > 9 else None,
    }


def _row_to_result(row) -> dict[str, Any]:
    """Convert a search result row to dict (includes rank)."""
    return {
        "id": row[0],
        "title": row[1],
        "content": row[2],
        "source_type": row[3],
        "source_id": row[4],
        "tags": json.loads(row[5]) if row[5] else [],
        "service_type": row[6],
        "target": row[7],
        "created_at": row[8],
        "rank": row[9],
    }
