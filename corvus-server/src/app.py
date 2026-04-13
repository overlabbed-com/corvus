"""Corvus server — operational governance for AI agent fleets."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.config import API_KEYS, CORVUS_DEV_MODE, MCP_ENABLED, OIDC_ENABLED
from src.dashboard.router import router as dashboard_router
from src.database import init_db
from src.discovery.collector import start_collector, stop_collector
from src.graph import close_graph, get_safe_mode_state, graph_available, graph_health, init_graph
from src.middleware.audit import AuditMiddleware
from src.middleware.auth import AuthMiddleware
from src.modules.loader import load_modules, register_module_routers
from src.routers import (
    agent_instructions,
    backup,
    changes,
    ci,
    cmdb,
    correlations,
    discovery,
    events,
    gaps,
    graph_queries,
    graph_triage,
    incidents,
    knowledge,
    lean_metrics,
    metrics,
    patterns,
    plans,
    problems,
    runbooks,
    steps,
    trust,
)
from src.runbooks.loader import registry as runbook_registry
from src.tasks.change_expiry import run_change_expiry_loop
from src.tasks.correlation import run_correlation_sweep_loop
from src.tasks.drift_detection import run_drift_detection_loop
from src.tasks.event_cleanup import run_cleanup_loop
from src.tasks.gap_detection import run_gap_sweep_loop
from src.tasks.metrics_collector import run_metrics_collector_loop
from src.tasks.step_timeout import run_step_timeout_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module directories to search (in priority order)
MODULE_DIRS = [
    Path("/app/config/modules"),  # Docker mount
    Path(__file__).parent.parent / "modules",  # Repo-local
]

# Runbook directories to search (in priority order)
RUNBOOK_DIRS = [
    Path("/app/config/runbooks"),  # Docker mount
    Path(__file__).parent.parent / "runbooks",  # Repo-local
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # T3.2: Refuse to start without auth unless explicitly in dev mode
    if not CORVUS_DEV_MODE and not API_KEYS and not OIDC_ENABLED:
        raise RuntimeError(
            "No authentication configured (CORVUS_API_KEYS empty, OIDC_ENABLED=false). "
            "Set CORVUS_DEV_MODE=true to allow anonymous admin access, or configure "
            "API keys via CORVUS_API_KEYS='name:key' environment variable."
        )

    await init_db()
    await init_graph()

    # Load runbooks
    for runbook_dir in RUNBOOK_DIRS:
        if runbook_dir.exists():
            count = runbook_registry.load_directory(runbook_dir)
            logger.info("Loaded %d runbooks from %s", count, runbook_dir)
            break
    else:
        logger.warning("No runbook directory found")

    # Load modules
    for module_dir in MODULE_DIRS:
        if module_dir.exists():
            count = load_modules(module_dir)
            logger.info("Loaded %d modules from %s", count, module_dir)
            break
    else:
        logger.info("No module directory found")

    # Register module routers
    registered = register_module_routers(app)
    if registered:
        logger.info("Registered %d module routers", registered)

    # Start background tasks
    expiry_task = asyncio.create_task(run_change_expiry_loop())
    cleanup_task = asyncio.create_task(run_cleanup_loop())
    gap_sweep_task = asyncio.create_task(run_gap_sweep_loop())
    step_timeout_task = asyncio.create_task(run_step_timeout_loop())
    metrics_task = asyncio.create_task(run_metrics_collector_loop())
    # Correlation sweep runs every 5 minutes
    correlation_task = asyncio.create_task(run_correlation_sweep_loop())
    # Drift detection runs every 10 minutes
    drift_task = asyncio.create_task(run_drift_detection_loop())

    # Start Layer 2 collector (if Docker hosts configured)
    start_collector()

    yield

    stop_collector()
    await close_graph()
    for task in (
        expiry_task,
        cleanup_task,
        gap_sweep_task,
        step_timeout_task,
        metrics_task,
        correlation_task,
        drift_task,
    ):
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# Rate limiter — keyed by remote address for unauthenticated, by API key for authenticated
# Default: 200/minute for reads, 60/minute for writes (applied per-endpoint via decorators)
# Global fallback: 500/minute per IP
# GAP-2: Per-Key Rate Limiting

def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key based on authenticated identity or IP."""
    if hasattr(request.state, "auth") and request.state.auth:
        # Use key name as rate limit key
        return f"key:{request.state.auth.key_name}"
    # Fallback to IP
    return get_remote_address(request)

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["500/minute"],
    storage_uri="memory://",
)

app = FastAPI(
    title="Corvus",
    description="Operational governance for AI agent fleets",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiter setup
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, exc: RequestValidationError
):
    """"Return 400 for request validation errors (GAP-1: OCSF schema validation)."""
    errors = []
    for e in exc.errors():
        loc = ".".join(str(item) for item in e["loc"] if item not in ("body", "__root__"))
        errors.append(f"{'.'.join(loc) + ': ' if loc else ''}{e['msg']}")

    detail = "; ".join(errors)
    if any("Unknown event type" in e["msg"] for e in exc.errors()):
        from src.models.events import EVENT_TYPE_ALLOWLIST
        valid = sorted(EVENT_TYPE_ALLOWLIST)
        detail = f"{detail}; valid_types={valid}"

    return JSONResponse(status_code=400, content={"detail": detail})



@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """"Return 400 for Pydantic validation errors (GAP-1: OCSF schema validation)."""
    errors = []
    for e in exc.errors():
        loc = ".".join(str(item) for item in e["loc"] if item not in ("body", "__root__"))
        errors.append(f"{'.'.join(loc) + ': ' if loc else ''}{e['msg']}")

    detail = "; ".join(errors)
    if any("Unknown event type" in e["msg"] for e in exc.errors()):
        from src.models.events import EVENT_TYPE_ALLOWLIST
        valid = sorted(EVENT_TYPE_ALLOWLIST)
        detail = f"{detail}; valid_types={valid}"

    return JSONResponse(status_code=400, content={"detail": detail})


# Middleware (order matters — outermost first, innermost last)
# AuditMiddleware logs every request (runs first, wraps everything)
# AuthMiddleware enforces auth on /ops/ and /backup/ paths
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthMiddleware)

# Routers
app.include_router(changes.router)
app.include_router(events.router)
app.include_router(incidents.router)
app.include_router(problems.router)
app.include_router(ci.router)
app.include_router(cmdb.router)
app.include_router(runbooks.router)
app.include_router(runbooks.triage_router)
app.include_router(metrics.router)
app.include_router(backup.router)
app.include_router(steps.router)
app.include_router(plans.router)
app.include_router(trust.router)
app.include_router(patterns.router)
app.include_router(knowledge.router)
app.include_router(agent_instructions.router)
app.include_router(gaps.router)
app.include_router(lean_metrics.router)
app.include_router(correlations.router)
app.include_router(graph_triage.router, tags=["triage-graph"])
app.include_router(discovery.router, prefix="/ops/discovery", tags=["discovery"])
app.include_router(graph_queries.router, prefix="/ops/graph", tags=["graph"])
app.include_router(dashboard_router)


# MCP SSE endpoint (conditionally mounted)
if MCP_ENABLED:
    from src.mcp_endpoint import create_mcp_routes

    app.mount("/mcp", create_mcp_routes(app))
    logger.info("MCP endpoint enabled at /mcp/sse")


@app.get("/")
async def root():
    return {
        "name": "Corvus",
        "version": "0.1.0",
        "description": "Operational governance for AI agent fleets",
    }


@app.get("/health")
async def health():
    graph_avail = graph_available()
    return {
        "status": "healthy" if graph_avail else "degraded",
        "graph": graph_avail,
        "safe_mode": get_safe_mode_state(),
        "graph_health": graph_health(),
    }
