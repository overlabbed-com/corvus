"""Layer 1: Declared discovery from Docker Compose files.

Walks a directory tree, parses all docker-compose.yml files, and extracts
service definitions, dependencies, networks, GPU assignments, and
environment-variable-based dependency inference.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.config import INFRA_GPUS, INFRA_HOSTS, INFRA_STACK_HOST_MAP

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryResult:
    """Aggregated discovery output from one or more layers."""

    services: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    hosts: list[dict] = field(default_factory=list)
    gpus: list[dict] = field(default_factory=list)
    networks: list[dict] = field(default_factory=list)



# Regex to extract hostnames from URLs in env var values
_URL_HOST_RE = re.compile(
    r"(?:https?://|postgres(?:ql)?://[^@]*@|redis://(?:[^@]*@)?|amqp://(?:[^@]*@)?|mqtt://)"
    r"([a-zA-Z][a-zA-Z0-9_-]*)"
    r"(?::\d+)?"
)


def _infer_host_from_stack(stack_name: str) -> str | None:
    """Map a stack directory name to its host using INFRA_STACK_HOST_MAP."""
    return INFRA_STACK_HOST_MAP.get(stack_name)


def _infer_stack_from_path(compose_path: Path, compose_dir: Path) -> str:
    """Extract stack name from the compose file's parent directory relative to compose_dir."""
    rel = compose_path.parent.relative_to(compose_dir)
    parts = rel.parts
    if parts:
        # Use first directory component as stack name (e.g., stacks/ai/docker-compose.yml -> ai)
        return parts[0] if len(parts) == 1 else parts[0]
    return "unknown"


def _parse_env_list(env_value) -> dict[str, str]:
    """Parse environment from compose format (list of KEY=VALUE or dict)."""
    if isinstance(env_value, dict):
        return {k: str(v) if v is not None else "" for k, v in env_value.items()}
    if isinstance(env_value, list):
        result = {}
        for item in env_value:
            item_str = str(item)
            if "=" in item_str:
                k, v = item_str.split("=", 1)
                result[k] = v
            else:
                result[item_str] = ""
        return result
    return {}


def _extract_gpu_indexes(env_vars: dict[str, str]) -> list[int]:
    """Extract GPU indexes from NVIDIA_VISIBLE_DEVICES env var."""
    nvidia_devs = env_vars.get("NVIDIA_VISIBLE_DEVICES", "")
    if not nvidia_devs or nvidia_devs in ("", "none", "void"):
        return []
    if nvidia_devs == "all":
        return []  # Can't determine specific indexes
    indexes = []
    for part in nvidia_devs.split(","):
        part = part.strip()
        if part.isdigit():
            indexes.append(int(part))
    return indexes


def _extract_env_dependencies(env_vars: dict[str, str], all_service_names: set[str]) -> list[str]:
    """Extract service dependencies from environment variable URL values.

    Scans env var values for URLs containing known service names as hostnames.
    """
    deps = set()
    for value in env_vars.values():
        if not value:
            continue
        for match in _URL_HOST_RE.finditer(str(value)):
            hostname = match.group(1)
            if hostname in all_service_names:
                deps.add(hostname)
    return sorted(deps)


def _parse_depends_on(depends_on_value) -> list[str]:
    """Parse depends_on from compose format (list or dict)."""
    if isinstance(depends_on_value, list):
        return depends_on_value
    if isinstance(depends_on_value, dict):
        return list(depends_on_value.keys())
    return []


def parse_compose_dir(compose_dir: str) -> DiscoveryResult:
    """Walk a directory tree, parse all docker-compose.yml files, and extract services.

    Args:
        compose_dir: Root directory to search for compose files.

    Returns:
        DiscoveryResult with services, edges, hosts, gpus, and networks.
    """
    root = Path(compose_dir)
    if not root.exists():
        logger.warning("Compose directory does not exist: %s", compose_dir)
        return DiscoveryResult(hosts=list(INFRA_HOSTS), gpus=list(INFRA_GPUS))

    # Find all compose files
    compose_files = sorted(root.rglob("docker-compose.yml"))
    if not compose_files:
        logger.warning("No docker-compose.yml files found in %s", compose_dir)
        return DiscoveryResult(hosts=list(INFRA_HOSTS), gpus=list(INFRA_GPUS))

    logger.info("Found %d compose files in %s", len(compose_files), compose_dir)

    # First pass: collect all service names for env var dependency detection
    all_service_names: set[str] = set()
    parsed_files: list[tuple[Path, str, dict]] = []

    for compose_file in compose_files:
        try:
            content = compose_file.read_text()
            data = yaml.safe_load(content)
            if not data or not isinstance(data, dict):
                continue

            services = data.get("services", {})
            if not services:
                continue

            stack = _infer_stack_from_path(compose_file, root)
            parsed_files.append((compose_file, stack, data))

            for svc_key, svc_def in services.items():
                if not isinstance(svc_def, dict):
                    continue
                name = svc_def.get("container_name", svc_key)
                all_service_names.add(name)
                # Also add the service key since depends_on uses keys
                all_service_names.add(svc_key)
        except Exception:
            logger.warning("Failed to parse %s", compose_file, exc_info=True)

    # Second pass: extract full service definitions
    result = DiscoveryResult(
        hosts=list(INFRA_HOSTS),
        gpus=list(INFRA_GPUS),
    )
    seen_networks: set[str] = set()
    seen_services: set[str] = set()
    # Map service keys to container names for edge resolution
    key_to_name: dict[str, str] = {}

    for _compose_file, stack, data in parsed_files:
        services = data.get("services", {})
        host = _infer_host_from_stack(stack)

        # Collect networks defined in this compose file
        file_networks = data.get("networks", {})
        for net_name in file_networks:
            if net_name not in seen_networks:
                seen_networks.add(net_name)
                result.networks.append({"name": net_name})

        for svc_key, svc_def in services.items():
            if not isinstance(svc_def, dict):
                continue

            container_name = svc_def.get("container_name", svc_key)
            key_to_name[svc_key] = container_name

            if container_name in seen_services:
                continue
            seen_services.add(container_name)

            image = svc_def.get("image", "")
            healthcheck = "healthcheck" in svc_def
            env_vars = _parse_env_list(svc_def.get("environment", []))
            gpu_indexes = _extract_gpu_indexes(env_vars)

            # Determine service type from image or name heuristics
            service_type = "container"
            if "postgres" in (image + container_name).lower():
                service_type = "database"
            elif "redis" in (image + container_name).lower():
                service_type = "cache"
            elif "vllm" in container_name.lower():
                service_type = "inference"
            elif "mcp" in container_name.lower():
                service_type = "mcp-server"

            result.services.append(
                {
                    "name": container_name,
                    "host": host,
                    "image": image,
                    "healthcheck": healthcheck,
                    "service_type": service_type,
                    "stack": stack,
                    "gpu_indexes": gpu_indexes,
                }
            )

            # depends_on edges (hard dependencies)
            depends_on = _parse_depends_on(svc_def.get("depends_on", []))
            for dep_key in depends_on:
                dep_name = key_to_name.get(dep_key, dep_key)
                result.edges.append(
                    {
                        "source": container_name,
                        "target": dep_name,
                        "type": "DEPENDS_ON",
                        "layer": "declared",
                        "confidence": 0.9,
                    }
                )

            # Network edges
            svc_networks = svc_def.get("networks", [])
            if isinstance(svc_networks, list):
                net_list = svc_networks
            elif isinstance(svc_networks, dict):
                net_list = list(svc_networks.keys())
            else:
                net_list = []
            for net in net_list:
                result.edges.append(
                    {
                        "source": container_name,
                        "target": net,
                        "type": "CONNECTS_TO",
                        "layer": "declared",
                        "confidence": 0.9,
                    }
                )

            # Env var dependency edges (softer confidence)
            env_deps = _extract_env_dependencies(env_vars, all_service_names)
            for dep_name in env_deps:
                # Avoid duplicating hard depends_on edges
                resolved_depends = {key_to_name.get(d, d) for d in depends_on}
                if dep_name not in resolved_depends and dep_name != container_name:
                    result.edges.append(
                        {
                            "source": container_name,
                            "target": dep_name,
                            "type": "DEPENDS_ON",
                            "layer": "declared-env",
                            "confidence": 0.7,
                        }
                    )

    logger.info(
        "Parsed %d services, %d edges, %d networks from %d compose files",
        len(result.services),
        len(result.edges),
        len(result.networks),
        len(parsed_files),
    )
    return result
