"""Audit logging middleware.

Writes every API request to ops_audit_log. Append-only, never deleted.
Forwards audit entries to SIEM as OCSF API Activity events.
Addresses threat model finding R1.1 (audit log integrity).

GAP-10: Per-Key Audit Alerting — real-time alerting on admin actions.
"""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.database import get_db
from src.siem.forwarder import forward_to_siem

logger = logging.getLogger(__name__)

# GAP-10: Admin action patterns that trigger real-time alerts
ADMIN_ACTION_PATTERNS = [
    "POST /ops/cmdb",
    "PATCH /ops/cmdb",
    "DELETE /ops/cmdb",
    "POST /ops/changes",
    "PATCH /ops/changes",
    "DELETE /ops/changes",
    "POST /ops/incidents",
    "PATCH /ops/incidents",
    "POST /ops/problems",
    "POST /backup/restore",
    "POST /ops/admin",
]


class AuditMiddleware(BaseHTTPMiddleware):
    """Log every API request to the audit trail."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip health checks and docs from audit
        if request.url.path in ("/ops/health", "/docs", "/openapi.json", "/"):
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000)

        # Extract actor from auth context if available.
        # AuthContext.identity is a property returning key_name; both access
        # patterns (.key_name here, .identity in routers) resolve to the same value.
        actor = "anonymous"
        if hasattr(request.state, "auth"):
            actor = request.state.auth.identity

        result = "success" if response.status_code < 400 else "failure"
        if response.status_code == 403:
            result = "denied"

        try:
            db = await get_db()
            try:
                await db.execute(
                    """INSERT INTO ops_audit_log
                       (timestamp, actor, action, resource, result, details)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        datetime.now(UTC).isoformat(),
                        actor,
                        f"{request.method} {request.url.path}",
                        request.url.path,
                        result,
                        json.dumps(
                            {
                                "method": request.method,
                                "path": request.url.path,
                                "status_code": response.status_code,
                                "duration_ms": duration_ms,
                                "query": str(request.query_params) if request.query_params else None,
                            }
                        ),
                    ),
                )
                await db.commit()
            finally:
                await db.close()

            # Forward audit entry to SIEM as OCSF API Activity event
            audit_ocsf = {
                "class_uid": 6003,
                "class_name": "API Activity",
                "category_uid": 6,
                "category_name": "Application Activity",
                "activity_id": 1,
                "activity_name": "Create",
                "severity_id": 1,
                "severity": "Informational",
                "time": datetime.now(UTC).isoformat(),
                "message": f"{request.method} {request.url.path}",
                "metadata": {
                    "version": "1.3.0",
                    "product": {
                        "name": "Corvus",
                        "vendor_name": "Corvus",
                        "version": "1.0.0",
                    },
                },
                "actor": {
                    "agent": {
                        "name": actor,
                        "type": "API Caller",
                        "uid": actor,
                    },
                },
                "unmapped": {
                    "audit_action": f"{request.method} {request.url.path}",
                    "audit_result": result,
                    "duration_ms": duration_ms,
                    "status_code": response.status_code,
                },
            }
            asyncio.create_task(forward_to_siem(audit_ocsf))

            # GAP-10: Real-time admin action alert
            action_key = f"{request.method} {request.url.path}"
            if any(action_key.startswith(pattern) for pattern in ADMIN_ACTION_PATTERNS):
                logger.warning(
                    "ADMIN_ACTION: %s by %s [%s] — see audit log for details",
                    action_key,
                    actor,
                    result,
                )
        except Exception:
            # Never let audit logging failure break the request
            logging.getLogger(__name__).debug("Audit logging failed", exc_info=True)

        return response
