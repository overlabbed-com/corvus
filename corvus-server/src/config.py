"""Corvus server configuration."""

import os
from pathlib import Path

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
