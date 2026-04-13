"""Runbook YAML loader.

Loads and validates FMEA triage runbooks from YAML files.
Validates structure against schema (T1.2) and pre-compiles
regex patterns with ReDoS protection (D1.3).
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default runbook directory
RUNBOOK_DIR = Path("/app/config/runbooks")

# Maximum allowed regex pattern length to prevent ReDoS (D1.3)
MAX_REGEX_LENGTH = 200

# Regex complexity heuristic: flag patterns with excessive backtracking potential
# Nested quantifiers like (a+)+ or (a*)*b are the classic ReDoS pattern
_REDOS_PATTERN = re.compile(r"([+*])\s*\)\s*[+*?{]")

# Required top-level keys for a valid runbook
REQUIRED_KEYS = {"name", "service_type"}

# Valid step types
VALID_STEP_TYPES = frozenset(
    {
        "http.check",
        "gpu.nvidia_smi",
        "containers.logs",
        "containers.inspect",
        "host.check",
        "mqtt.check",
    }
)


class RunbookValidationError(ValueError):
    """Raised when a runbook fails schema validation."""


def _validate_regex_pattern(pattern: str, context: str) -> re.Pattern:
    """Validate and compile a regex pattern with ReDoS protection.

    Args:
        pattern: The regex string to validate
        context: Description of where this pattern appears (for error messages)

    Returns:
        Compiled regex pattern

    Raises:
        RunbookValidationError: If pattern is too long, has ReDoS risk, or is invalid
    """
    if len(pattern) > MAX_REGEX_LENGTH:
        raise RunbookValidationError(f"Regex pattern too long ({len(pattern)} > {MAX_REGEX_LENGTH}) in {context}")

    if _REDOS_PATTERN.search(pattern):
        raise RunbookValidationError(
            f"Regex pattern has potential ReDoS (nested quantifiers) in {context}: {pattern[:50]}..."
        )

    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise RunbookValidationError(f"Invalid regex pattern in {context}: {e}") from e


def _validate_runbook_schema(data: dict[str, Any], path: str) -> list[str]:
    """Validate runbook structure against expected schema.

    Returns list of warnings (non-fatal issues).
    Raises RunbookValidationError for fatal issues.
    """
    warnings = []

    # Check required keys
    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        raise RunbookValidationError(f"Missing required keys in {path}: {missing}")

    # Validate name is a non-empty string
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RunbookValidationError(f"'name' must be a non-empty string in {path}")

    # Validate service_type
    svc_type = data.get("service_type")
    if not isinstance(svc_type, str) or not svc_type.strip():
        raise RunbookValidationError(f"'service_type' must be a non-empty string in {path}")

    # Validate investigation steps
    investigation = data.get("investigation", [])
    if not isinstance(investigation, list):
        raise RunbookValidationError(f"'investigation' must be a list in {path}")

    for i, step in enumerate(investigation):
        if not isinstance(step, dict):
            raise RunbookValidationError(f"Investigation step {i} must be a dict in {path}")
        step_type = step.get("type")
        if step_type and step_type not in VALID_STEP_TYPES:
            warnings.append(f"Unknown step type '{step_type}' in step {i} of {path}")

    # Validate diagnosis_hints and pre-compile patterns (D1.3 + T1.2)
    hints = data.get("diagnosis_hints", [])
    if not isinstance(hints, list):
        raise RunbookValidationError(f"'diagnosis_hints' must be a list in {path}")

    for i, hint in enumerate(hints):
        if not isinstance(hint, dict):
            raise RunbookValidationError(f"Diagnosis hint {i} must be a dict in {path}")
        pattern = hint.get("pattern")
        if pattern:
            if not isinstance(pattern, str):
                raise RunbookValidationError(f"Diagnosis hint {i} 'pattern' must be a string in {path}")
            # Validate and pre-compile — raises on ReDoS or invalid regex
            _validate_regex_pattern(pattern, f"diagnosis_hint[{i}] in {path}")

    # Validate remediation
    remediation = data.get("remediation", {})
    if not isinstance(remediation, dict):
        raise RunbookValidationError(f"'remediation' must be a dict in {path}")

    # Validate escalation_triggers patterns
    for i, trigger in enumerate(remediation.get("escalation_triggers", [])):
        if not isinstance(trigger, str):
            raise RunbookValidationError(f"Escalation trigger {i} must be a string in {path}")

    return warnings


class Runbook:
    """A loaded runbook with investigation, diagnosis, and remediation steps."""

    def __init__(self, data: dict[str, Any], path: str = ""):
        self.name: str = data.get("name", "unnamed")
        self.type: str = data.get("type", "triage")
        self.service_type: str = data.get("service_type", "")
        self.version: int = data.get("version", 1)
        self.description: str = data.get("description", "")
        self.investigation: list[dict[str, Any]] = data.get("investigation", [])
        self.diagnosis_hints: list[dict[str, Any]] = data.get("diagnosis_hints", [])
        self.remediation: dict[str, Any] = data.get("remediation", {})
        self.path = path

        # Pre-compile diagnosis patterns for safe, fast matching (D1.3)
        self.compiled_patterns: dict[int, re.Pattern] = {}
        for i, hint in enumerate(self.diagnosis_hints):
            pattern = hint.get("pattern")
            if pattern:
                self.compiled_patterns[i] = re.compile(pattern, re.IGNORECASE)

    def __repr__(self) -> str:
        return f"Runbook(name={self.name!r}, service_type={self.service_type!r})"


class RunbookRegistry:
    """Registry of loaded runbooks, indexed by service_type."""

    def __init__(self):
        self._by_service_type: dict[str, Runbook] = {}
        self._all: list[Runbook] = []

    def load_directory(self, directory: Path | str) -> int:
        """Load all YAML runbooks from a directory. Returns count loaded."""
        directory = Path(directory)
        if not directory.exists():
            logger.warning("Runbook directory does not exist: %s", directory)
            return 0

        count = 0
        for path in sorted(directory.glob("*.yaml")):
            try:
                self.load_file(path)
                count += 1
            except RunbookValidationError as e:
                logger.error("Runbook validation failed: %s", e)
            except Exception:
                logger.exception("Failed to load runbook: %s", path)

        logger.info("Loaded %d runbooks from %s", count, directory)
        return count

    def load_file(self, path: Path | str) -> Runbook:
        """Load a single runbook YAML file.

        Validates structure and regex patterns before accepting.
        """
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise RunbookValidationError(f"Invalid runbook format in {path}: expected dict")

        # Schema validation (T1.2) + regex validation (D1.3)
        warnings = _validate_runbook_schema(data, str(path))
        for warning in warnings:
            logger.warning(warning)

        runbook = Runbook(data, path=str(path))
        self._all.append(runbook)

        if runbook.service_type:
            self._by_service_type[runbook.service_type] = runbook

        logger.info("Loaded runbook: %s (service_type=%s)", runbook.name, runbook.service_type)
        return runbook

    def get_for_service_type(self, service_type: str) -> Runbook | None:
        """Get the runbook for a service type."""
        return self._by_service_type.get(service_type)

    def list_all(self) -> list[Runbook]:
        """List all loaded runbooks."""
        return list(self._all)

    @property
    def service_types_covered(self) -> set[str]:
        """Set of service types that have runbooks."""
        return set(self._by_service_type.keys())


# Global registry
registry = RunbookRegistry()
