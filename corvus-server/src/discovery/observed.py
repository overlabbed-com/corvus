"""Layer 2: Observed discovery from network traffic.

Collects actual TCP connections between containers via conntrack, Tetragon
events, or external collectors. Maps raw IP:port tuples to container names
using Docker network metadata from admin-api.

Data flow:
  1. Collector (Tetragon, conntrack, Prefect flow) captures TCP connections
  2. Raw tuples posted to Corvus /ops/discovery/connections endpoint
  3. This module resolves IPs → container names via admin-api
  4. Deduplicates and builds CONNECTS_TO edges for the graph
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from src.discovery.declared import DiscoveryResult

logger = logging.getLogger(__name__)


@dataclass
class RawConnection:
    """A single observed TCP connection tuple."""

    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    protocol: str = "tcp"
    host: str = ""
    timestamp: str = ""


@dataclass
class ObservedConnection:
    """A resolved connection between two named services."""

    source: str
    target: str
    dst_port: int
    protocol: str = "tcp"
    count: int = 1
    first_seen: str = ""
    last_seen: str = ""


@dataclass
class ObservationResult:
    """Output of an observation sweep."""

    connections: list[ObservedConnection] = field(default_factory=list)
    unresolved: list[RawConnection] = field(default_factory=list)
    ip_map_size: int = 0
    host: str = ""


async def build_ip_map(
    admin_api_url: str,
    admin_api_token: str = "",
) -> dict[str, str]:
    """Build IP → container name mapping from admin-api.

    Queries /containers for all containers and extracts network IP addresses.
    Falls back to container name if no IP is available.

    Returns:
        Dict mapping IP addresses to container names.
    """
    ip_map: dict[str, str] = {}
    url = f"{admin_api_url.rstrip('/')}/containers"

    headers = {}
    if admin_api_token:
        headers["Authorization"] = f"Bearer {admin_api_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            containers = response.json()
    except Exception:
        logger.warning("Admin API unreachable for IP mapping at %s", url, exc_info=True)
        return ip_map

    if not isinstance(containers, list):
        return ip_map

    for container in containers:
        if not isinstance(container, dict):
            continue

        name = container.get("name", "")
        if isinstance(name, str) and name.startswith("/"):
            name = name[1:]
        if not name:
            continue

        # Extract IPs from network settings
        networks = container.get("networks", {})
        if isinstance(networks, dict):
            for _net_name, net_info in networks.items():
                if isinstance(net_info, dict):
                    ip = net_info.get("ip", net_info.get("IPAddress", ""))
                    if ip:
                        ip_map[ip] = name

        # Also check top-level ip field (admin-api format)
        ip = container.get("ip", "")
        if ip:
            ip_map[ip] = name

    logger.info("Built IP map with %d entries from admin-api", len(ip_map))
    return ip_map


def resolve_connections(
    raw: list[RawConnection],
    ip_map: dict[str, str],
) -> ObservationResult:
    """Resolve raw IP connections to named service connections.

    Deduplicates by (source, target, dst_port) and counts occurrences.

    Args:
        raw: Raw TCP connection tuples.
        ip_map: IP → container name mapping.

    Returns:
        ObservationResult with resolved and unresolved connections.
    """
    now = datetime.now(UTC).isoformat()
    aggregated: dict[tuple[str, str, int], ObservedConnection] = {}
    unresolved: list[RawConnection] = []

    for conn in raw:
        src_name = ip_map.get(conn.src_ip)
        dst_name = ip_map.get(conn.dst_ip)

        if not src_name or not dst_name:
            unresolved.append(conn)
            continue

        # Skip self-connections
        if src_name == dst_name:
            continue

        key = (src_name, dst_name, conn.dst_port)
        if key in aggregated:
            aggregated[key].count += 1
            aggregated[key].last_seen = conn.timestamp or now
        else:
            aggregated[key] = ObservedConnection(
                source=src_name,
                target=dst_name,
                dst_port=conn.dst_port,
                protocol=conn.protocol,
                count=1,
                first_seen=conn.timestamp or now,
                last_seen=conn.timestamp or now,
            )

    return ObservationResult(
        connections=list(aggregated.values()),
        unresolved=unresolved,
        ip_map_size=len(ip_map),
    )


def connections_to_discovery_result(
    connections: list[ObservedConnection],
) -> DiscoveryResult:
    """Convert observed connections to DiscoveryResult for graph population.

    Creates CONNECTS_TO edges between services with layer='observed' provenance.
    Confidence is 0.8 for observed connections (actual traffic).
    """
    result = DiscoveryResult()

    # Deduplicate edges: one per (source, target) pair
    seen_edges: set[tuple[str, str]] = set()
    for conn in connections:
        edge_key = (conn.source, conn.target)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        result.edges.append(
            {
                "source": conn.source,
                "target": conn.target,
                "type": "OBSERVED_CONNECTION",
                "layer": "observed",
                "confidence": 0.8,
                "dst_port": conn.dst_port,
                "protocol": conn.protocol,
                "count": conn.count,
                "first_seen": conn.first_seen,
                "last_seen": conn.last_seen,
            }
        )

    return result


def parse_conntrack(raw_text: str, host: str = "") -> list[RawConnection]:
    """Parse conntrack -L output into RawConnection objects.

    Expected format (from /proc/net/nf_conntrack or conntrack -L):
      ipv4  2 tcp  6 300 ESTABLISHED src=172.20.0.5 dst=172.20.0.3 sport=44512
      dport=5432 src=172.20.0.3 dst=172.20.0.5 sport=5432 dport=44512 [ASSURED] ...

    Only captures ESTABLISHED TCP connections.
    """
    connections: list[RawConnection] = []
    now = datetime.now(UTC).isoformat()

    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line or "ESTABLISHED" not in line:
            continue
        if "tcp" not in line.lower():
            continue

        parts = {}
        for token in line.split():
            if "=" in token:
                k, v = token.split("=", 1)
                # Only capture first occurrence (original direction)
                if k not in parts:
                    parts[k] = v

        src_ip = parts.get("src", "")
        dst_ip = parts.get("dst", "")
        src_port = parts.get("sport", "0")
        dst_port = parts.get("dport", "0")

        if src_ip and dst_ip:
            connections.append(
                RawConnection(
                    src_ip=src_ip,
                    src_port=int(src_port),
                    dst_ip=dst_ip,
                    dst_port=int(dst_port),
                    protocol="tcp",
                    host=host,
                    timestamp=now,
                )
            )

    return connections


def parse_tetragon_events(events: list[dict], host: str = "") -> list[RawConnection]:
    """Parse Tetragon kprobe TCP connect events into RawConnection objects.

    Expected format (from TracingPolicy tcp_connect kprobe):
    {
        "process_kprobe": {
            "process": {"binary": "...", "pod": {"container": {"name": "..."}}},
            "args": [
                {"sock_arg": {
                    "family": "AF_INET",
                    "saddr": "172.20.0.5",
                    "daddr": "172.20.0.3",
                    "sport": 44512,
                    "dport": 5432
                }}
            ]
        }
    }
    """
    connections: list[RawConnection] = []
    now = datetime.now(UTC).isoformat()

    for event in events:
        kprobe = event.get("process_kprobe", {})
        if not kprobe:
            continue

        args = kprobe.get("args", [])
        for arg in args:
            sock = arg.get("sock_arg", {})
            if not sock:
                continue

            family = sock.get("family", "")
            if family not in ("AF_INET", "AF_INET6"):
                continue

            saddr = sock.get("saddr", "")
            daddr = sock.get("daddr", "")
            sport = sock.get("sport", 0)
            dport = sock.get("dport", 0)

            if saddr and daddr:
                timestamp = event.get("time", now)
                connections.append(
                    RawConnection(
                        src_ip=saddr,
                        src_port=int(sport),
                        dst_ip=daddr,
                        dst_port=int(dport),
                        protocol="tcp",
                        host=host,
                        timestamp=timestamp,
                    )
                )

    return connections


def summarize_connections(
    connections: list[ObservedConnection],
) -> dict[str, list[dict]]:
    """Group connections by source service for reporting.

    Returns:
        Dict mapping source service → list of {target, port, count} dicts.
    """
    by_source: dict[str, list[dict]] = defaultdict(list)
    for conn in connections:
        by_source[conn.source].append(
            {
                "target": conn.target,
                "port": conn.dst_port,
                "protocol": conn.protocol,
                "count": conn.count,
            }
        )
    return dict(by_source)
