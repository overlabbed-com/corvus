"""CLI configuration — reads from env vars or ~/.corvus.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _load_config_file() -> dict:
    """Load ~/.corvus.json if it exists."""
    config_path = Path.home() / ".corvus.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def get_base_url() -> str:
    """Get Corvus server URL."""
    url = os.environ.get("CORVUS_URL")
    if url:
        return url.rstrip("/")
    config = _load_config_file()
    return config.get("url", "http://localhost:8000").rstrip("/")


def get_token() -> str:
    """Get API token."""
    token = os.environ.get("CORVUS_TOKEN")
    if token:
        return token
    config = _load_config_file()
    return config.get("token", "")
