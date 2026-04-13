"""Container inspection for drift detection.

Inspects running containers to extract actual configuration
for comparison with declared GitOps state.
"""

import json
import logging
import subprocess
from typing import Any

from src.discovery.deploy_manager import RunningConfig

logger = logging.getLogger(__name__)


async def inspect_container(service_name: str, host: str | None = None) -> RunningConfig | None:
    """Inspect running container and extract configuration.
    
    Args:
        service_name: Name of the container/service
        host: Optional Docker host (defaults to local)
        
    Returns:
        RunningConfig with actual container state, or None if not found
    """
    try:
        # Build docker inspect command
        if host:
            cmd = f"ssh {host} 'docker inspect {service_name}'"
        else:
            cmd = f"docker inspect {service_name}"
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            logger.debug(f"Container {service_name} not found or inspect failed")
            return None
        
        # Parse inspect output
        inspect_data = json.loads(result.stdout)
        if not inspect_data or not isinstance(inspect_data, list) or len(inspect_data) == 0:
            return None
        
        container = inspect_data[0]
        
        # Extract image
        image = container.get("Config", {}).get("Image", "unknown")
        
        # Extract healthcheck
        healthcheck_cmd = container.get("Config", {}).get("Healthcheck", {})
        healthcheck = None
        if healthcheck_cmd and healthcheck_cmd.get("Test"):
            healthcheck = " ".join(healthcheck_cmd["Test"])
        
        # Extract environment variables (compute hash)
        env_vars = container.get("Config", {}).get("Env", [])
        env_dict = {}
        for env in env_vars:
            if "=" in env:
                key, _ = env.split("=", 1)
                env_dict[key] = True  # Only track names, not values
        
        from src.discovery.deploy_manager import compute_env_hash
        env_hash = compute_env_hash(env_dict)
        
        # Extract networks
        networks = []
        network_settings = container.get("NetworkSettings", {}).get("Networks", {})
        networks = list(network_settings.keys())
        
        # Extract resources
        resources = {}
        host_config = container.get("HostConfig", {})
        if host_config.get("Memory"):
            resources["memory_limit"] = host_config["Memory"]
        if host_config.get("NanoCpus"):
            resources["cpu_limit"] = host_config["NanoCpus"] / 1e9
        
        # Extract state
        state = container.get("State", {})
        container_state = state.get("Status", "unknown")
        health_status = state.get("Health", {}).get("Status", "unknown")
        oom_killed = state.get("OOMKilled", False)
        restart_count = state.get("RestartCount", 0)
        
        return RunningConfig(
            image=image,
            healthcheck=healthcheck,
            env_hash=env_hash,
            networks=networks if networks else None,
            resources=resources if resources else None,
            state=container_state,
            health_status=health_status,
            oom_killed=oom_killed,
            restart_count=restart_count,
        )
        
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout inspecting container {service_name}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse inspect output for {service_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error inspecting container {service_name}: {e}", exc_info=True)
        return None


async def inspect_multiple_containers(
    service_names: list[str],
    host: str | None = None,
) -> dict[str, RunningConfig | None]:
    """Inspect multiple containers concurrently.
    
    Args:
        service_names: List of container names
        host: Optional Docker host
        
    Returns:
        Dict mapping service name to RunningConfig (or None if not found)
    """
    import asyncio
    
    tasks = [inspect_container(name, host) for name in service_names]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    return {
        name: result if isinstance(result, RunningConfig) else None
        for name, result in zip(service_names, results)
    }


async def get_container_logs(
    service_name: str,
    lines: int = 100,
    host: str | None = None,
) -> str | None:
    """Get recent container logs.
    
    Args:
        service_name: Container name
        lines: Number of lines to fetch
        host: Optional Docker host
        
    Returns:
        Log output or None if container not found
    """
    try:
        if host:
            cmd = f"ssh {host} 'docker logs {service_name} --tail {lines}'"
        else:
            cmd = f"docker logs {service_name} --tail {lines}"
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return None
        
        return result.stdout
        
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout fetching logs for {service_name}")
        return None
    except Exception as e:
        logger.error(f"Error fetching logs for {service_name}: {e}", exc_info=True)
        return None
