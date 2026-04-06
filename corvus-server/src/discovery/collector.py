"""Layer 2 collector — active connection discovery via Docker API.

Corvus-native collection using only Docker primitives:
  1. Docker network inspect → IP-to-container mapping (all networks, all hosts)
  2. Docker exec /proc/net/tcp → active TCP connections per container
  3. Resolve connections through the IP map → service-to-service edges

No external tools required (no conntrack binary, no Tetragon policy).
Works with both local Docker socket and remote Docker TCP API (mTLS).

Configuration:
  CORVUS_DOCKER_HOSTS: Comma-separated host specs.
    - Local socket: "my-host:unix:///var/run/docker.sock"
    - Remote TCP:   "remote-host:https://10.0.0.1:2376"
  CORVUS_DOCKER_TLS_DIR: Directory containing TLS certs for remote hosts.
    Expected files: ca.pem, cert.pem, key.pem
  CORVUS_COLLECT_INTERVAL: Collection interval in seconds (default: 900 = 15 min).
  CORVUS_COLLECT_CONTAINERS: Comma-separated container names to read /proc/net/tcp
    from. If empty, reads from all containers that support exec.
"""

import asyncio
import logging
import os
import ssl
import struct
from socket import inet_ntoa

import httpx

from src.discovery.observed import (
    RawConnection,
    connections_to_discovery_result,
    resolve_connections,
    summarize_connections,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOCKER_HOSTS: dict[str, str] = {}  # hostname → URL
_raw_hosts = os.getenv("CORVUS_DOCKER_HOSTS", "")
if _raw_hosts:
    for entry in _raw_hosts.split(","):
        entry = entry.strip()
        if ":" in entry:
            name, url = entry.split(":", 1)
            DOCKER_HOSTS[name.strip()] = url.strip()

DOCKER_TLS_DIR = os.getenv("CORVUS_DOCKER_TLS_DIR", "/certs/docker")
COLLECT_INTERVAL = int(os.getenv("CORVUS_COLLECT_INTERVAL", "900"))

# Containers to sample /proc/net/tcp from. Empty = all with exec support.
_sample_containers = os.getenv("CORVUS_COLLECT_CONTAINERS", "")
SAMPLE_CONTAINERS: list[str] = [c.strip() for c in _sample_containers.split(",") if c.strip()]


# ---------------------------------------------------------------------------
# Docker API client
# ---------------------------------------------------------------------------


def _build_tls_context() -> ssl.SSLContext | None:
    """Build mTLS context from cert files if they exist."""
    ca = os.path.join(DOCKER_TLS_DIR, "ca.pem")
    cert = os.path.join(DOCKER_TLS_DIR, "cert.pem")
    key = os.path.join(DOCKER_TLS_DIR, "key.pem")

    if not all(os.path.exists(f) for f in (ca, cert, key)):
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(cert, key)
    ctx.load_verify_locations(ca)
    return ctx


def _client_for_host(host_url: str) -> httpx.AsyncClient:
    """Create an httpx client for the given Docker host URL."""
    if host_url.startswith("unix://"):
        socket_path = host_url.replace("unix://", "")
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=30.0)

    # TCP with TLS
    tls_ctx = _build_tls_context()
    return httpx.AsyncClient(base_url=host_url, verify=tls_ctx or False, timeout=30.0)


# ---------------------------------------------------------------------------
# IP Map: Docker network inspect
# ---------------------------------------------------------------------------


async def collect_ip_map(host_name: str, host_url: str) -> dict[str, str]:
    """Build IP → container name map from Docker network inspect.

    Queries all networks on the host and extracts container IPs.

    Returns:
        Dict mapping IP addresses to container names.
    """
    ip_map: dict[str, str] = {}

    async with _client_for_host(host_url) as client:
        try:
            # List all networks
            resp = await client.get("/networks")
            resp.raise_for_status()
            networks = resp.json()
        except Exception:
            logger.warning("Failed to list networks on %s", host_name, exc_info=True)
            return ip_map

        for net in networks:
            if not isinstance(net, dict):
                continue
            # Skip host/none/bridge built-in networks
            net_name = net.get("Name", "")
            if net_name in ("host", "none"):
                continue

            containers = net.get("Containers", {})
            if not isinstance(containers, dict):
                continue

            for _cid, info in containers.items():
                if not isinstance(info, dict):
                    continue
                name = info.get("Name", "")
                ipv4 = info.get("IPv4Address", "")
                if name and ipv4:
                    # Strip CIDR suffix (172.18.0.5/16 → 172.18.0.5)
                    ip = ipv4.split("/")[0]
                    ip_map[ip] = name

    logger.info("Collected %d IPs from %s", len(ip_map), host_name)
    return ip_map


# ---------------------------------------------------------------------------
# Connection collection: /proc/net/tcp
# ---------------------------------------------------------------------------


def _hex_to_ip(hex_str: str) -> str:
    """Convert hex IP from /proc/net/tcp to dotted-decimal."""
    return inet_ntoa(struct.pack("<I", int(hex_str, 16)))


def _hex_to_port(hex_str: str) -> int:
    """Convert hex port from /proc/net/tcp to integer."""
    return int(hex_str, 16)


def parse_proc_net_tcp(raw_text: str, host: str = "") -> list[RawConnection]:
    """Parse /proc/net/tcp output into RawConnection objects.

    Format (from Linux kernel):
      sl  local_address rem_address   st tx_queue rx_queue ...
       0: 00000000:1F40 00000000:0000 0A ...
       1: 0F0012AC:1F40 0E0012AC:1E07 01 ...

    State 01 = ESTABLISHED. We only capture established connections.
    """
    connections: list[RawConnection] = []

    for line in raw_text.strip().splitlines():
        line = line.strip()
        if line.startswith("sl") or not line:
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        local = parts[1]  # hex_ip:hex_port
        remote = parts[2]
        state = parts[3]

        # 01 = ESTABLISHED
        if state != "01":
            continue

        try:
            local_ip_hex, local_port_hex = local.split(":")
            remote_ip_hex, remote_port_hex = remote.split(":")

            src_ip = _hex_to_ip(local_ip_hex)
            src_port = _hex_to_port(local_port_hex)
            dst_ip = _hex_to_ip(remote_ip_hex)
            dst_port = _hex_to_port(remote_port_hex)

            # Skip loopback
            if src_ip.startswith("127.") or dst_ip.startswith("127."):
                continue

            connections.append(
                RawConnection(
                    src_ip=src_ip,
                    src_port=src_port,
                    dst_ip=dst_ip,
                    dst_port=dst_port,
                    protocol="tcp",
                    host=host,
                )
            )
        except (ValueError, struct.error):
            continue

    return connections


async def collect_connections_from_container(
    host_name: str,
    host_url: str,
    container_id: str,
    container_name: str,
) -> list[RawConnection]:
    """Read /proc/net/tcp from inside a container via Docker exec API.

    Uses the Docker exec API to cat /proc/net/tcp, which shows the
    container's TCP connections from its network namespace perspective.
    """
    async with _client_for_host(host_url) as client:
        try:
            # Create exec
            exec_resp = await client.post(
                f"/containers/{container_id}/exec",
                json={
                    "AttachStdout": True,
                    "AttachStderr": False,
                    "Cmd": ["cat", "/proc/net/tcp"],
                },
            )
            exec_resp.raise_for_status()
            exec_id = exec_resp.json().get("Id")
            if not exec_id:
                return []

            # Start exec and read output
            start_resp = await client.post(
                f"/exec/{exec_id}/start",
                json={"Detach": False, "Tty": False},
            )
            start_resp.raise_for_status()

            # Docker exec output has a stream header (8 bytes per frame)
            # For simplicity, strip non-printable bytes and parse as text
            raw = start_resp.content.decode("utf-8", errors="replace")
            # Strip Docker stream framing bytes
            clean_lines = []
            for line in raw.splitlines():
                # Remove leading non-printable characters (stream headers)
                cleaned = line.lstrip("\x00\x01\x02\x03\x04\x05\x06\x07\x08")
                if cleaned.strip():
                    clean_lines.append(cleaned)
            clean_text = "\n".join(clean_lines)

            return parse_proc_net_tcp(clean_text, host=host_name)

        except Exception:
            logger.debug(
                "Failed to read /proc/net/tcp from %s on %s",
                container_name,
                host_name,
                exc_info=True,
            )
            return []


# ---------------------------------------------------------------------------
# Full collection sweep
# ---------------------------------------------------------------------------


async def collect_host(host_name: str, host_url: str) -> tuple[dict[str, str], list[RawConnection]]:
    """Run a full collection sweep on a single Docker host.

    Returns:
        Tuple of (ip_map, raw_connections).
    """
    ip_map = await collect_ip_map(host_name, host_url)
    all_connections: list[RawConnection] = []

    async with _client_for_host(host_url) as client:
        try:
            resp = await client.get("/containers/json")
            resp.raise_for_status()
            containers = resp.json()
        except Exception:
            logger.warning("Failed to list containers on %s", host_name, exc_info=True)
            return ip_map, all_connections

        for container in containers:
            if not isinstance(container, dict):
                continue

            cid = container.get("Id", "")
            names = container.get("Names", [])
            name = names[0].lstrip("/") if names else ""

            if not name or not cid:
                continue

            # If SAMPLE_CONTAINERS is set, only sample those
            if SAMPLE_CONTAINERS and name not in SAMPLE_CONTAINERS:
                continue

            conns = await collect_connections_from_container(host_name, host_url, cid, name)
            all_connections.extend(conns)

    logger.info(
        "Collected %d raw connections from %d containers on %s",
        len(all_connections),
        len(containers) if not SAMPLE_CONTAINERS else len(SAMPLE_CONTAINERS),
        host_name,
    )
    return ip_map, all_connections


async def collect_all_hosts() -> tuple[dict[str, str], list[RawConnection]]:
    """Run collection across all configured Docker hosts.

    Returns:
        Tuple of (merged_ip_map, all_raw_connections).
    """
    if not DOCKER_HOSTS:
        logger.warning("No Docker hosts configured (CORVUS_DOCKER_HOSTS is empty)")
        return {}, []

    merged_ip_map: dict[str, str] = {}
    all_connections: list[RawConnection] = []

    # Collect from all hosts concurrently
    tasks = [collect_host(name, url) for name, url in DOCKER_HOSTS.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        host_name = list(DOCKER_HOSTS.keys())[i]
        if isinstance(result, Exception):
            logger.warning("Collection failed for %s: %s", host_name, result)
            continue
        ip_map, connections = result
        merged_ip_map.update(ip_map)
        all_connections.extend(connections)

    logger.info(
        "Total: %d IPs, %d raw connections from %d hosts",
        len(merged_ip_map),
        len(all_connections),
        len(DOCKER_HOSTS),
    )
    return merged_ip_map, all_connections


async def run_collection() -> dict:
    """Run a full collection sweep and return resolved connections.

    This is the main entry point for scheduled collection.

    Returns:
        Summary dict with collection results.
    """
    ip_map, raw_connections = await collect_all_hosts()

    if not raw_connections:
        return {
            "hosts": len(DOCKER_HOSTS),
            "ip_map_size": len(ip_map),
            "raw_connections": 0,
            "resolved": 0,
            "unresolved": 0,
            "edges": 0,
        }

    observation = resolve_connections(raw_connections, ip_map)
    discovery_result = connections_to_discovery_result(observation.connections)
    summary = summarize_connections(observation.connections)

    return {
        "hosts": len(DOCKER_HOSTS),
        "ip_map_size": len(ip_map),
        "raw_connections": len(raw_connections),
        "resolved": len(observation.connections),
        "unresolved": len(observation.unresolved),
        "edges": len(discovery_result.edges),
        "summary": summary,
        "connections": observation.connections,
        "discovery_result": discovery_result,
    }


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------

_collector_task: asyncio.Task | None = None


async def _collection_loop():
    """Background loop that collects connections on a schedule."""
    logger.info("Layer 2 collector started (interval=%ds)", COLLECT_INTERVAL)
    while True:
        try:
            await asyncio.sleep(COLLECT_INTERVAL)
            result = await run_collection()
            logger.info(
                "Scheduled collection: %d raw → %d resolved → %d edges",
                result.get("raw_connections", 0),
                result.get("resolved", 0),
                result.get("edges", 0),
            )

            # Write to graph if we have edges and graph is available
            if result.get("edges", 0) > 0:
                try:
                    from src.discovery.populator import populate_graph
                    from src.graph import graph_available

                    if graph_available():
                        from src.discovery.declared import DiscoveryResult

                        await populate_graph(
                            DiscoveryResult(),  # empty declared
                            observed=result["discovery_result"],
                        )
                        logger.info("Wrote %d observed edges to graph", result["edges"])
                except Exception:
                    logger.warning("Failed to write observed edges to graph", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Layer 2 collector stopped")
            break
        except Exception:
            logger.exception("Layer 2 collection sweep failed")


def start_collector():
    """Start the background collection task."""
    global _collector_task
    if not DOCKER_HOSTS:
        logger.info("Layer 2 collector not started (no Docker hosts configured)")
        return
    if _collector_task and not _collector_task.done():
        logger.warning("Layer 2 collector already running")
        return
    _collector_task = asyncio.create_task(_collection_loop())


def stop_collector():
    """Stop the background collection task."""
    global _collector_task
    if _collector_task and not _collector_task.done():
        _collector_task.cancel()
        _collector_task = None
