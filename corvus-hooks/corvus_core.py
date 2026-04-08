"""Corvus Governance Core Library.

Shared logic for all AI coding assistant adapters. Handles:
- Target extraction from docker/SSH commands and MCP tool inputs
- Corvus API calls (check_target, emit_event)
- User intent classification (incident/change/design/neutral)
- macOS keychain credential retrieval

Adapters import this module and translate their tool's hook format
into these common functions.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CORVUS_BASE_URL = os.environ.get(
    "CORVUS_GOVERNANCE_URL", "http://192.168.20.14:9420"
)
TIMEOUT_SECONDS = 5

# Keychain config (macOS). Non-macOS uses env var fallback.
KEYCHAIN_SERVICE = "corvus.themillertribe-int.org"
KEYCHAIN_ACCOUNT = "claude-code-api-key"
ENV_API_KEY = "CORVUS_API_KEY"  # fallback for Linux/CI

# ---------------------------------------------------------------------------
# Credential retrieval
# ---------------------------------------------------------------------------


def get_api_key() -> Optional[str]:
    """Retrieve Corvus API key. Tries macOS keychain, then env var."""
    # macOS keychain
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Env var fallback (Linux, CI, containers)
    return os.environ.get(ENV_API_KEY)


# ---------------------------------------------------------------------------
# Corvus API
# ---------------------------------------------------------------------------


def check_target(target: str, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Call Corvus GET /ops/events/targets/{target}/status.

    Returns dict with keys: target, recommendation (GO/CAUTION/STOP),
    reason, active_changes, active_incidents, recent_events, trust_tier.
    Returns None if Corvus is unreachable.
    """
    if not api_key:
        api_key = get_api_key()
    if not api_key:
        return None

    url = f"{CORVUS_BASE_URL}/ops/events/targets/{target}/status"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, TimeoutError, OSError):
        return None


def emit_event(
    event_type: str,
    target: str,
    source: str = "ai-assistant",
    severity: str = "info",
    data: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> bool:
    """POST an event to Corvus. Returns True on success."""
    if not api_key:
        api_key = get_api_key()
    if not api_key:
        return False

    url = f"{CORVUS_BASE_URL}/ops/events"
    payload = json.dumps({
        "type": event_type,
        "target": target,
        "source": source,
        "severity": severity,
        "data": data or {"auto_emitted": True},
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status in (200, 201)
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, OSError):
        return False


# ---------------------------------------------------------------------------
# Target extraction — Bash commands
# ---------------------------------------------------------------------------

DESTRUCTIVE_PATTERNS = [
    re.compile(
        r"(?:sudo\s+)?docker\s+(?:restart|stop|rm|kill)\s+"
        r"(?:-[a-zA-Z]\s+)*"
        r"([a-zA-Z0-9][a-zA-Z0-9_.:-]+)",
    ),
    re.compile(
        r"(?:sudo\s+)?docker\s+compose\s+"
        r"(?:-f\s+\S+\s+)*"
        r"(up|down|restart)",
    ),
    re.compile(
        r"(?:sudo\s+)?docker\s+volume\s+rm\s+"
        r"(?:-f\s+)*"
        r"([a-zA-Z0-9][a-zA-Z0-9_.:-]+)",
    ),
    re.compile(
        r"(?:sudo\s+)?docker\s+network\s+rm\s+"
        r"([a-zA-Z0-9][a-zA-Z0-9_.:-]+)",
    ),
]

SSH_DOCKER_PATTERN = re.compile(
    r'ssh\s+\S+\s+["\']?'
    r"(?:sudo\s+)?docker\s+"
    r"(?:restart|stop|rm|kill|compose\s+(?:up|down|restart))\s*"
    r"(?:[^\"\']*?\s)?"
    r"([a-zA-Z0-9][a-zA-Z0-9_.:-]*)?"
)

DOCKER_ACTION_PATTERN = re.compile(
    r"(?:sudo\s+)?docker\s+(restart|stop|rm|kill)\s+"
    r"(?:-[a-zA-Z]\s+)*"
    r"([a-zA-Z0-9][a-zA-Z0-9_.:-]+)"
)

SSH_DOCKER_ACTION_PATTERN = re.compile(
    r'ssh\s+\S+\s+["\']?'
    r"(?:sudo\s+)?docker\s+(restart|stop|rm|kill)\s+"
    r"(?:[^\"\']*?\s)?"
    r"([a-zA-Z0-9][a-zA-Z0-9_.:-]*)?"
)

# Maps docker action → Corvus event type
ACTION_EVENT_MAP = {
    "restart": "remediation.restart",
    "stop": "remediation.stop",
    "rm": "remediation.remove",
    "kill": "remediation.kill",
}


def extract_target_from_command(command: str) -> Optional[str]:
    """Extract infrastructure target from a shell command.

    Returns container/volume/network/stack name, or None if not destructive.
    """
    # SSH-wrapped commands
    m = SSH_DOCKER_PATTERN.search(command)
    if m:
        target = m.group(1)
        if target:
            return target.strip("\"'")
        stack_match = re.search(r"/stacks/([a-zA-Z0-9_-]+)/", command)
        if stack_match:
            return stack_match.group(1)
        return "unknown-ssh-target"

    # Direct docker commands
    for pattern in DESTRUCTIVE_PATTERNS:
        m = pattern.search(command)
        if m:
            target = m.group(1)
            if target in ("up", "down", "restart"):
                stack_match = re.search(r"/stacks/([a-zA-Z0-9_-]+)/", command)
                if stack_match:
                    return stack_match.group(1)
                proj_match = re.search(r"-p\s+(\S+)", command)
                if proj_match:
                    return proj_match.group(1)
                return "docker-compose"
            return target

    return None


def extract_action_from_command(command: str) -> Optional[Tuple[str, str]]:
    """Extract (action, target) from a shell command for event emission.

    Returns (action, target) tuple or None.
    """
    m = SSH_DOCKER_ACTION_PATTERN.search(command)
    if m and m.group(2):
        return (m.group(1), m.group(2).strip("\"'"))

    m = DOCKER_ACTION_PATTERN.search(command)
    if m:
        return (m.group(1), m.group(2))

    return None


# ---------------------------------------------------------------------------
# Target extraction — MCP tools
# ---------------------------------------------------------------------------

# tool_name → primary input field containing the target
MCP_TARGET_FIELDS = {
    "docker-container_restart": "container_name",
    "docker-container_stop": "container_name",
    "docker-container_start": "container_name",
    "portainer-container_restart": "container_name",
    "portainer-container_stop": "container_name",
    "portainer-container_start": "container_name",
    "portainer-stack_deploy": "stack_name",
    "portainer-stack_remove": "stack_name",
}

# MCP tool → Corvus event type
MCP_EVENT_MAP = {
    "docker-container_restart": "remediation.restart",
    "docker-container_stop": "remediation.stop",
    "docker-container_start": "remediation.start",
    "portainer-container_restart": "remediation.restart",
    "portainer-container_stop": "remediation.stop",
    "portainer-container_start": "remediation.start",
    "portainer-stack_deploy": "change.completed",
    "portainer-stack_remove": "change.completed",
}

MCP_TARGET_FALLBACK_FIELDS = ["name", "container", "container_id", "stack"]


def normalize_mcp_tool_name(tool_name: str) -> str:
    """Strip common MCP prefixes to get the canonical tool suffix.

    e.g. 'mcp__litellm-mcp__docker-container_restart' → 'docker-container_restart'
         'docker-container_restart' → 'docker-container_restart'
    """
    # Strip LiteLLM proxy prefix
    if "__" in tool_name:
        tool_name = tool_name.rsplit("__", 1)[-1]
    return tool_name


def extract_target_from_mcp(tool_name: str, tool_input: Dict[str, Any]) -> Optional[str]:
    """Extract target from an MCP tool call's input dict."""
    canonical = normalize_mcp_tool_name(tool_name)
    primary = MCP_TARGET_FIELDS.get(canonical)
    if primary and primary in tool_input:
        return str(tool_input[primary])

    for field in MCP_TARGET_FALLBACK_FIELDS:
        if field in tool_input:
            return str(tool_input[field])

    return None


def is_destructive_mcp_tool(tool_name: str) -> bool:
    """Check if an MCP tool name is a known destructive operation."""
    canonical = normalize_mcp_tool_name(tool_name)
    return canonical in MCP_TARGET_FIELDS


def get_mcp_event_type(tool_name: str) -> Optional[str]:
    """Get the Corvus event type for an MCP tool."""
    canonical = normalize_mcp_tool_name(tool_name)
    return MCP_EVENT_MAP.get(canonical)


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

_INFRA_NOUNS = (
    r"container|service|stack|server|host|secret|key|token|cert|dns|"
    r"network|vlan|volume|gpu|model|mcp|caddy|postgres|redis|litellm|"
    r"vllm|milvus|prefect|corvus|splunk|netdata|plex|sonarr|radarr|"
    r"ollama|homeassistant|zigbee|tetragon|comfyui|mosquitto|mqtt"
)

_HOSTS = r"dockp0[1-4]|tmtdockp0[1-4]|tmtnsp0[12]|tmtaip01"

INCIDENT_PATTERNS = [
    re.compile(
        r"\b(?:broken|down|failing|crashed|stuck|unresponsive|"
        r"not\s+(?:working|responding|starting)|crash[- ]?loop\w*|"
        r"restart[- ]?loop\w*|unhealthy|503|502|500|OOM|"
        r"out\s+of\s+memory|can'?t\s+(?:reach|connect|access)|"
        r"timeout|timed?\s+out|error\w*|flapping)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:fix|debug|investigate|troubleshoot|diagnose|what'?s\s+wrong)\b"
        r".*\b(?:" + _INFRA_NOUNS + r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:container|service|stack|server|host)\b"
        r".*\b(?:fix|debug|investigate|troubleshoot|diagnose|broken|down|failing|error)\b",
        re.IGNORECASE,
    ),
]

CHANGE_PATTERNS = [
    re.compile(
        r"\b(?:install|deploy|set\s+up|configure|add|enable|remove|disable|"
        r"uninstall|migrate|move|upgrade|update|rotate|change)\b"
        r".*\b(?:" + _INFRA_NOUNS + r")\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:" + _INFRA_NOUNS + r")\b"
        r".*\b(?:install|deploy|set\s+up|configure|add|enable|remove|disable|"
        r"uninstall|migrate|move|upgrade|update|rotate|change)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:docker\s+compose|ansible|gitops|merge|pr|pull\s+request)\b"
        r".*\b(?:change|update|deploy|create)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:install|deploy|set\s+up|configure)\b"
        r".*\b(?:" + _HOSTS + r")\b",
        re.IGNORECASE,
    ),
]

DESIGN_PATTERNS = [
    re.compile(
        r"\b(?:build|create|design|architect|plan)\b"
        r".*\b(?:new|stack|service|system|platform|pipeline|tool|agent)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:new)\b.*\b(?:stack|service|container|deployment|infrastructure)\b",
        re.IGNORECASE,
    ),
]

FALSE_POSITIVE_PATTERNS = [
    re.compile(
        r"\b(?:blog|post|article|write|draft|email|slack|meeting|"
        r"calendar|presentation|slide)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:how\s+does|what\s+is|explain|describe|tell\s+me\s+about|"
        r"show\s+me)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:commit|push|pr|pull\s+request|review|merge)\b"
        r".*\b(?:this|the|my|our)\b",
        re.IGNORECASE,
    ),
]


def classify_intent(prompt: str) -> Optional[str]:
    """Classify user intent: 'incident', 'change', 'design', or None."""
    for pattern in INCIDENT_PATTERNS:
        if pattern.search(prompt):
            return "incident"

    for pattern in DESIGN_PATTERNS:
        if pattern.search(prompt):
            if any(fp.search(prompt) for fp in FALSE_POSITIVE_PATTERNS):
                return None
            return "design"

    for pattern in CHANGE_PATTERNS:
        if pattern.search(prompt):
            if any(fp.search(prompt) for fp in FALSE_POSITIVE_PATTERNS):
                return None
            return "change"

    return None


# ---------------------------------------------------------------------------
# Governance messages
# ---------------------------------------------------------------------------

INCIDENT_MANDATE = """
You MUST follow the Incident Workflow:
1. SWITCH to Responder role
2. CREATE incident record IMMEDIATELY (before investigating):
   corvus_create_incident(target="<service>", title="<title>",
     description="<what user reported>", severity="warning",
     detected_by="<assistant-name>")
3. CHECK for conflicts: corvus_check_target(target="<service>")
4. INVESTIGATE (logs, status, dependencies)
5. If restart needed: MAX 2 attempts, then escalate
6. EMIT events for every action: corvus_emit_event(...)
7. When resolved: update incident + emit resolution event
DO NOT skip the incident creation. It is the FIRST action, always.
""".strip()

CHANGE_MANDATE = """
You MUST follow the Change Lifecycle:
1. SWITCH to Architect role — design the change
2. CREATE change window BEFORE any modification:
   corvus_emit_event(type="change.started", target="<service>",
     source="<assistant-name>", data={"description": "..."})
3. Architect design → Lean Review → Advocate challenge
4. CHECKPOINT — present design + challenge for approval
5. ONLY after approval: implement via GitOps (branch + PR)
6. After deployment: corvus_emit_event(type="change.completed", ...)
7. Monitor for 24-72h post-change
DO NOT modify infrastructure before the design is approved.
""".strip()

DESIGN_MANDATE = """
You MUST follow the Design Workflow:
1. Create project directory if needed
2. Architect designs — research and PROPOSE (don't ask user to decide)
3. Design MUST include: problem statement, proposed solution, risk
   assessment, rollback plan, dependency map, phased rollout
4. Lean Review — simplest solution? YAGNI? Existing code?
5. Advocate challenges the design (MANDATORY, no exceptions)
6. CHECKPOINT — present BOTH design + challenge for approval
7. Only after approval: implement via GitOps
DO NOT implement before designing. DO NOT skip the Advocate challenge.
""".strip()
