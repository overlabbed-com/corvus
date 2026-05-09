"""Story 3.1: Prometheus metrics for Corvus observability.

Exports counters, histograms, and gauges for monitoring Corvus health
and performance.
"""

import logging

logger = logging.getLogger(__name__)

# Try to import prometheus_client
try:
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed - metrics disabled")


# Event metrics
EVENTS_RECEIVED = None
EVENTS_FORWARDED = None
EVENTS_DROPPED = None

# Triage metrics
TRIAGE_DURATION = None
TRIAGE_SUCCESS_RATE = None

# Graph metrics
GRAPH_QUERY_DURATION = None
GRAPH_CONNECTIONS = None

# Subscription metrics
ACTIVE_SUBSCRIPTIONS = None
SUBSCRIPTION_DROPPED = None

# SIEM metrics
SIEM_ADAPTER_HEALTH = None
SIEM_FORWARDING_SUCCESS = None
SIEM_FORWARDING_FAILURE = None

# Gap metrics
GAPS_OPEN = None
GAPS_CLOSED = None

# Trust metrics
TRUST_TIER_CHANGES = None

# Performance metrics
REQUEST_DURATION = None
REQUEST_COUNT = None


def init_metrics():
    """Initialize all Prometheus metrics."""
    global EVENTS_RECEIVED, EVENTS_FORWARDED, EVENTS_DROPPED
    global TRIAGE_DURATION
    global GRAPH_QUERY_DURATION, GRAPH_CONNECTIONS
    global ACTIVE_SUBSCRIPTIONS, SUBSCRIPTION_DROPPED
    global SIEM_ADAPTER_HEALTH, SIEM_FORWARDING_SUCCESS, SIEM_FORWARDING_FAILURE
    global GAPS_OPEN, GAPS_CLOSED
    global TRUST_TIER_CHANGES
    global REQUEST_DURATION, REQUEST_COUNT

    if not PROMETHEUS_AVAILABLE:
        return

    # Event metrics
    EVENTS_RECEIVED = Counter("corvus_events_received_total", "Total events received", ["type", "severity"])
    EVENTS_FORWARDED = Counter("corvus_events_forwarded_total", "Total events forwarded to SIEM", ["adapter"])
    EVENTS_DROPPED = Counter("corvus_events_dropped_total", "Total events dropped (queue full, etc.)")

    # Triage metrics
    triage_duration = Histogram(
        "corvus_triage_duration_seconds", "Triage execution duration", ["service_type", "outcome"]
    )
    triage_success_rate = Counter("corvus_triage_success_total", "Successful triages", ["service_type"])
    triage_failure_rate = Counter("corvus_triage_failure_total", "Failed triages", ["service_type"])

    # Graph metrics
    graph_query_duration = Histogram("corvus_graph_query_duration_seconds", "Neo4j query duration", ["query_type"])
    graph_connections = Gauge("corvus_graph_connections", "Active Neo4j connections")

    # Subscription metrics
    active_subscriptions = Gauge("corvus_sse_subscriptions", "Active SSE subscriptions")
    subscription_dropped = Counter("corvus_subscriptions_dropped_total", "Dropped subscriptions (timeout, error)")

    # SIEM metrics
    SIEM_ADAPTER_HEALTH = Gauge(
        "corvus_siem_adapter_health", "SIEM adapter health (1=healthy, 0=unhealthy)", ["adapter"]
    )
    SIEM_FORWARDING_SUCCESS = Counter(
        "corvus_siem_forwarded_success_total", "Successfully forwarded events", ["adapter"]
    )
    SIEM_FORWARDING_FAILURE = Counter("corvus_siem_forwarded_failure_total", "Failed event forwards", ["adapter"])

    # Gap metrics
    GAPS_OPEN = Gauge("corvus_gaps_open_total", "Open operational gaps", ["category", "workstream"])
    GAPS_CLOSED = Counter("corvus_gaps_closed_total", "Closed operational gaps", ["category"])

    # Trust metrics
    TRUST_TIER_CHANGES = Counter(
        "corvus_trust_tier_changes_total", "Trust tier changes", ["action_type", "old_tier", "new_tier"]
    )

    # Request metrics
    REQUEST_DURATION = Histogram(
        "corvus_request_duration_seconds", "HTTP request duration", ["endpoint", "method", "status"]
    )
    REQUEST_COUNT = Counter("corvus_requests_total", "Total HTTP requests", ["endpoint", "method", "status"])


def get_metrics() -> bytes:
    """Get Prometheus-formatted metrics."""
    if not PROMETHEUS_AVAILABLE:
        return b"# Prometheus metrics not available\n"
    return generate_latest(REGISTRY)


# Helper functions for incrementing metrics
def record_event_received(event_type: str, severity: str):
    """Record an event was received."""
    if EVENTS_RECEIVED:
        EVENTS_RECEIVED.labels(type=event_type, severity=severity).inc()


def record_event_forwarded(adapter: str):
    """Record an event was forwarded to SIEM."""
    if EVENTS_FORWARDED:
        EVENTS_FORWARDED.labels(adapter=adapter).inc()


def record_event_dropped():
    """Record an event was dropped."""
    if EVENTS_DROPPED:
        EVENTS_DROPPED.inc()


def record_triage_duration(service_type: str, outcome: str, duration: float):
    """Record triage execution time."""
    if TRIAGE_DURATION:
        TRIAGE_DURATION.labels(service_type=service_type, outcome=outcome).observe(duration)


def record_graph_query_duration(query_type: str, duration: float):
    """Record graph query time."""
    if GRAPH_QUERY_DURATION:
        GRAPH_QUERY_DURATION.labels(query_type=query_type).observe(duration)


def record_active_subscriptions(count: int):
    """Update active subscription count."""
    if ACTIVE_SUBSCRIPTIONS:
        ACTIVE_SUBSCRIPTIONS.set(count)


def record_gap_open(category: str, workstream: str):
    """Record a gap was opened."""
    if GAPS_OPEN:
        GAPS_OPEN.labels(category=category, workstream=workstream).inc()


def record_gap_closed(category: str):
    """Record a gap was closed."""
    if GAPS_CLOSED:
        GAPS_CLOSED.labels(category=category).inc()
        if GAPS_OPEN:
            GAPS_OPEN.labels(category=category, workstream="all").dec()


def record_request(endpoint: str, method: str, status: int, duration: float):
    """Record HTTP request metrics."""
    if REQUEST_COUNT:
        REQUEST_COUNT.labels(endpoint=endpoint, method=method, status=str(status)).inc()
    if REQUEST_DURATION:
        REQUEST_DURATION.labels(endpoint=endpoint, method=method, status=str(status)).observe(duration)


# Initialize metrics on module load (only once)
_METRICS_INITIALIZED = False

if not _METRICS_INITIALIZED:
    init_metrics()
    _METRICS_INITIALIZED = True
