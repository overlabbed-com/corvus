"""Runbook executor — runs investigation steps and produces diagnoses.

Executes runbook investigation steps, matches diagnosis hints,
and returns structured triage results.
"""

import asyncio
import logging
import re
from typing import Any

from src.runbooks.loader import Runbook

logger = logging.getLogger(__name__)


class TriageResult:
    """Result of running a triage runbook."""

    def __init__(self):
        self.investigation_results: dict[str, Any] = {}
        self.diagnosis: str | None = None
        self.root_cause: str | None = None
        self.explanation: str | None = None
        self.restart_safe: bool | None = None
        self.confidence: float = 0.0
        self.escalation_required: bool = False
        self.escalation_reason: str | None = None
        self.runbook_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "runbook_name": self.runbook_name,
            "diagnosis": self.diagnosis,
            "root_cause": self.root_cause,
            "explanation": self.explanation,
            "restart_safe": self.restart_safe,
            "confidence": self.confidence,
            "escalation_required": self.escalation_required,
            "escalation_reason": self.escalation_reason,
            "investigation_results": self.investigation_results,
        }


class StepResult:
    """Result of a single investigation step."""

    def __init__(self, name: str, success: bool, output: Any = None, error: str | None = None):
        self.name = name
        self.success = success
        self.output = output
        self.error = error


# Step type handlers — these are abstract; real implementations would
# call Docker APIs, SSH, HTTP, etc. For now they return structured placeholders
# that agents populate via the Corvus API.
async def _execute_step(step: dict[str, Any], context: dict[str, str]) -> StepResult:
    """Execute a single investigation step.

    In production, each step type dispatches to a real executor.
    This base implementation handles the dispatch and context substitution.
    """
    step_name = step.get("name", "unnamed")
    step_type = step.get("type", "unknown")
    params = step.get("params", {})
    timeout = step.get("timeout", 30)

    # Template substitution
    resolved_params = {}
    for key, value in params.items():
        if isinstance(value, str):
            for ctx_key, ctx_val in context.items():
                value = value.replace(f"{{{{ {ctx_key} }}}}", ctx_val)
                value = value.replace(f"{{{{{ctx_key}}}}}", ctx_val)
        resolved_params[key] = value

    # Step type dispatch
    handler = STEP_HANDLERS.get(step_type)
    if handler:
        try:
            # Story 1.3: Wrap handler with timeout using asyncio.wait_for
            output = await asyncio.wait_for(
                handler(resolved_params, timeout),
                timeout=timeout,
            )
            return StepResult(step_name, success=True, output=output)
        except TimeoutError:
            logger.error(
                "Step %s timed out after %ds (type=%s, timeout=%d)",
                step_name,
                timeout,
                step_type,
                timeout,
            )
            return StepResult(step_name, success=False, error=f"Timeout after {timeout}s")
        except Exception as e:
            return StepResult(step_name, success=False, error=str(e))

    # Unknown step type — return placeholder
    return StepResult(
        step_name,
        success=True,
        output={"type": step_type, "params": resolved_params, "status": "requires_agent_execution"},
    )


async def _http_check(params: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Execute an HTTP health check step."""
    import httpx

    url = params.get("url", "")
    expect_status = params.get("expect_status", 200)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=timeout)
            return {
                "status_code": resp.status_code,
                "healthy": resp.status_code == expect_status,
                "response_time_ms": resp.elapsed.total_seconds() * 1000 if resp.elapsed else None,
            }
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        return {"status_code": None, "healthy": False, "error": str(e)}


async def _noop_step(params: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Placeholder step that returns params for agent-side execution."""
    return {"status": "requires_agent_execution", "params": params}


# Handler registry
STEP_HANDLERS: dict[str, Any] = {
    "http.check": _http_check,
    "gpu.nvidia_smi": _noop_step,
    "containers.logs": _noop_step,
    "containers.inspect": _noop_step,
    "host.check": _noop_step,
    "mqtt.check": _noop_step,
}


def match_diagnosis(runbook: Runbook, investigation_output: str) -> dict[str, Any] | None:
    """Match investigation output against runbook diagnosis hints.

    Uses pre-compiled patterns from the Runbook (validated at load time
    for ReDoS safety — D1.3).

    Returns the matching hint or None.
    """
    combined = investigation_output.lower()
    for i, hint in enumerate(runbook.diagnosis_hints):
        compiled = runbook.compiled_patterns.get(i)
        if compiled and compiled.search(combined):
            return hint
        # Fallback for hints without patterns that were loaded before validation
        pattern = hint.get("pattern", "")
        if pattern and not compiled:
            try:
                if re.search(pattern, combined, re.IGNORECASE):
                    return hint
            except re.error:
                logger.warning("Invalid regex pattern in diagnosis hint: %s", pattern)
    return None


async def execute_triage(
    runbook: Runbook,
    target: str,
    host: str = "",
    investigation_data: dict[str, Any] | None = None,
) -> TriageResult:
    """Execute a triage runbook for a target.

    Args:
        runbook: The loaded runbook to execute
        target: Target service/container name
        host: Host where the service runs
        investigation_data: Pre-collected investigation data (optional)

    Returns:
        TriageResult with diagnosis and recommendations
    """
    result = TriageResult()
    result.runbook_name = runbook.name

    context = {"target": target, "host": host}

    # Execute investigation steps
    for step in runbook.investigation:
        step_result = await _execute_step(step, context)
        output_key = step.get("outputs", {})
        if isinstance(output_key, dict):
            for key in output_key:
                result.investigation_results[key] = step_result.output

    # If pre-collected data provided, merge it
    if investigation_data:
        result.investigation_results.update(investigation_data)

    # Match diagnosis hints
    combined_output = str(result.investigation_results)
    matched_hint = match_diagnosis(runbook, combined_output)

    if matched_hint:
        result.diagnosis = matched_hint.get("root_cause", "unknown")
        result.root_cause = matched_hint.get("root_cause")
        result.explanation = matched_hint.get("explanation", "")
        result.restart_safe = matched_hint.get("restart_safe", False)
        result.confidence = 0.85
    else:
        result.diagnosis = "unknown"
        result.confidence = 0.3

    # Check escalation triggers
    remediation = runbook.remediation
    for trigger in remediation.get("escalation_triggers", []):
        if trigger.lower() in combined_output.lower():
            result.escalation_required = True
            result.escalation_reason = f"Matched escalation trigger: {trigger}"
            break

    return result
