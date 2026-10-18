"""The Corvus v2 API: the single binary (ADR-001), the generic contract.

The routes (the product's consumption surface):
  POST /ops/events                 — the event ingest (the data vocabulary)
  GET  /ops/events                 — the query (the target filter)
  GET  /ops/events/stream          — the SSE stream (the live fabric)
  POST /ops/changes                — the change window
  GET  /ops/changes/active         — the active changes
  GET  /ops/conflict-check         — THE decision (GO/CAUTION/STOP)
  GET  /health                     — the liveness

The API key auth: the X-Corvus-Key header (the fleet's key). No homelab
wiring anywhere — the contract is the product (criterion 5).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import FleetConfig, load_config
from .core import CorvusCore
from .state import State


class EventIn(BaseModel):
    type: str
    target: str
    source: str = "unknown"
    severity: str = "info"
    data: dict = {}


class ChangeIn(BaseModel):
    targets: list[str]
    description: str = ""
    created_by: str | None = None
    rollback_plan: str | None = None
    auto_expire: bool = True
    expires_at: str | None = None


def _auth_key(request: Request, config: FleetConfig) -> str:
    key = request.headers.get("X-Corvus-Key", "")
    if key != config.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-Corvus-Key")
    return key


def create_app(config: FleetConfig | None = None, db_path: str = ":memory:") -> FastAPI:
    cfg = config or load_config(os.environ.get("CORVUS_CONFIG_PATH"))
    state = State(db_path)
    core = CorvusCore(cfg, state)
    subscribers: set[asyncio.Queue] = set()

    app = FastAPI(title="Corvus", version="2.0.0",
                  description="The change control board and IR command center for agent fleets")

    async def require_key(request: Request) -> str:
        return _auth_key(request, cfg)

    @app.get("/health")
    async def health():
        return {"status": "ok", "fleet": cfg.name, "node": cfg.node_id,
                "event_types": len(cfg.event_types)}

    @app.post("/ops/events", status_code=201)
    async def ingest(event: EventIn, key: str = Depends(require_key)):
        try:
            row = core.ingest_event(event.model_dump(), authenticated_as=key[:8])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        for q in list(subscribers):
            q.put_nowait(row)
        return row

    @app.get("/ops/events")
    async def events(target: str | None = None, limit: int = Query(100, le=1000),
                     key: str = Depends(require_key)):
        return core.query_events(target, limit)

    @app.get("/ops/events/stream")
    async def stream(key: str = Depends(require_key)):
        q: asyncio.Queue = asyncio.Queue()
        subscribers.add(q)

        async def gen():
            try:
                while True:
                    row = await q.get()
                    yield f"data: {json.dumps(row)}\n\n"
            finally:
                subscribers.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/ops/changes", status_code=201)
    async def open_change(change: ChangeIn, key: str = Depends(require_key)):
        try:
            return core.open_change(change.model_dump(), authenticated_as=key[:8])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/ops/changes/active")
    async def active_changes(target: str, key: str = Depends(require_key)):
        return core.active_changes_for(target)

    @app.get("/ops/conflict-check")
    async def conflict_check(target: str, action_type: str | None = None,
                             actor: str | None = None, key: str = Depends(require_key)):
        return core.conflict_check(target, action_type, actor)

    return app


app = create_app()
