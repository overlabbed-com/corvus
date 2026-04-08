"""Corvus server configuration."""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("CORVUS_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "corvus.db"
AUDIT_LOG_PATH = DATA_DIR / "audit.jsonl"

# Auth
API_KEYS: dict[str, str] = {}  # name -> key mapping
_raw_keys = os.getenv("CORVUS_API_KEYS", "")
if _raw_keys:
    for entry in _raw_keys.split(","):
        if ":" in entry:
            name, key = entry.split(":", 1)
            API_KEYS[key.strip()] = name.strip()

# SIEM forwarding
SIEM_URL = os.getenv("CORVUS_SIEM_URL", "")
SIEM_TOKEN = os.getenv("CORVUS_SIEM_TOKEN", "")

# LLM
LLM_URL = os.getenv("CORVUS_LLM_URL", "")

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# MCP endpoint
MCP_ENABLED = os.getenv("CORVUS_MCP_ENABLED", "true").lower() == "true"
MCP_INTERNAL_KEY = os.getenv("CORVUS_MCP_INTERNAL_KEY", "corvus-mcp-internal")

# Register the internal MCP key so tool calls pass auth
if MCP_ENABLED and MCP_INTERNAL_KEY:
    API_KEYS[MCP_INTERNAL_KEY] = "mcp-internal:admin"

# Change window defaults
CHANGE_EXPIRY_HOURS = int(os.getenv("CORVUS_CHANGE_EXPIRY_HOURS", "4"))

# Dev mode — explicit flag instead of inferring from empty API_KEYS
CORVUS_DEV_MODE: bool = os.getenv("CORVUS_DEV_MODE", "false").lower() == "true"

# OIDC (OpenID Connect) configuration
OIDC_ISSUER_URL: str = os.getenv("OIDC_ISSUER_URL", "https://accounts.google.com")
OIDC_CLIENT_ID: str = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET: str = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_ENABLED: bool = os.getenv("OIDC_ENABLED", "false").lower() == "true"

# Infrastructure config — loaded from external YAML so no instance-specific
# data lives in source code.  Set CORVUS_INFRA_CONFIG to override the path.
INFRA_CONFIG_PATH = os.getenv(
    "CORVUS_INFRA_CONFIG",
    str(Path(__file__).parent.parent / "config" / "infrastructure.yaml"),
)


def _load_infra_config() -> dict:
    """Load infrastructure config from YAML file. Returns empty defaults if not found."""
    path = Path(INFRA_CONFIG_PATH)
    if not path.exists():
        logger.info("No infrastructure config at %s — using empty defaults", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        logger.info(
            "Loaded infrastructure config: %d hosts, %d GPUs, %d stack mappings",
            len(data.get("hosts", [])),
            len(data.get("gpus", [])),
            len(data.get("stack_host_map", {})),
        )
        return data
    except Exception:
        logger.warning("Failed to load infrastructure config from %s", path, exc_info=True)
        return {}


_infra = _load_infra_config()
INFRA_HOSTS: list[dict] = _infra.get("hosts", [])
INFRA_GPUS: list[dict] = _infra.get("gpus", [])
INFRA_STACK_HOST_MAP: dict[str, str] = _infra.get("stack_host_map", {})


class RuntimeConfig:
    """Mutable runtime configuration with atomic get/set/revert.

    Background tasks and routers read tunable parameters from here
    instead of module-level constants. The auto-tuner writes here.
    Defaults match the original hardcoded values.
    """

    _values: dict[str, float | int | str] = {}
    _defaults: dict[str, float | int | str] = {}
    _bounds: dict[str, tuple[float | int | None, float | int | None]] = {}

    @classmethod
    def register_default(
        cls,
        key: str,
        value: float | int | str,
        min_val: float | int | None = None,
        max_val: float | int | None = None,
    ) -> None:
        """Register a tunable parameter with its default and optional bounds."""
        cls._defaults[key] = value
        cls._bounds[key] = (min_val, max_val)
        if key not in cls._values:
            cls._values[key] = value

    @classmethod
    def get(cls, key: str) -> float | int | str:
        """Get current value of a tunable parameter."""
        if key not in cls._defaults:
            raise KeyError(f"Unknown config key: {key}")
        return cls._values.get(key, cls._defaults[key])

    @classmethod
    def set(cls, key: str, value: float | int | str) -> None:
        """Set a tunable parameter, clamping to bounds if registered."""
        min_val, max_val = cls._bounds.get(key, (None, None))
        if isinstance(value, (int, float)):
            if min_val is not None and value < min_val:
                value = type(value)(min_val)
            if max_val is not None and value > max_val:
                value = type(value)(max_val)
        cls._values[key] = value

    @classmethod
    def revert(cls, key: str) -> None:
        """Restore a parameter to its registered default."""
        if key in cls._defaults:
            cls._values[key] = cls._defaults[key]

    @classmethod
    def snapshot(cls) -> dict[str, float | int | str]:
        """Return current values of all registered parameters."""
        return {k: cls._values.get(k, v) for k, v in cls._defaults.items()}

    @classmethod
    def defaults(cls) -> dict[str, float | int | str]:
        """Return the registered defaults (not overrides)."""
        return dict(cls._defaults)

    @classmethod
    def reset(cls) -> None:
        """Reset all state. For testing only."""
        cls._values.clear()
        cls._defaults.clear()
        cls._bounds.clear()


# Register tunable operational parameters
RuntimeConfig.register_default("trust.promotion_threshold", 0.95, min_val=0.80, max_val=0.99)
RuntimeConfig.register_default("trust.min_executions", 20, min_val=5, max_val=100)
RuntimeConfig.register_default("change_expiry.hours", CHANGE_EXPIRY_HOURS, min_val=1, max_val=24)
RuntimeConfig.register_default("step_timeout.default", 300, min_val=30, max_val=3600)
RuntimeConfig.register_default("step_timeout.reaper_interval", 60, min_val=15, max_val=300)
RuntimeConfig.register_default("triage.confidence_threshold", 0.5, min_val=0.2, max_val=0.9)
