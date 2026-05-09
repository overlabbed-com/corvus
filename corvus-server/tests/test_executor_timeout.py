"""Tests for runbook executor timeout behavior.

Story 1.3: All step handlers should be wrapped with asyncio.wait_for()
to enforce timeout limits.
"""

import asyncio
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_slow_handler_times_out(client):
    """A slow handler should raise TimeoutError after the configured timeout."""
    from src.runbooks import executor

    # Create a step that would take too long
    step = {
        "name": "slow-check",
        "type": "slow.step",
        "params": {"url": "http://slow.example.com"},
        "timeout": 1,  # 1 second timeout
    }
    context = {}

    # Create a slow handler
    async def slow_handler(params, timeout):
        await asyncio.sleep(5)  # Would sleep for 5 seconds
        return {"status": "ok"}

    # Patch the handler registry
    with patch.object(executor, "STEP_HANDLERS", {"slow.step": slow_handler}):
        result = await executor._execute_step(step, context)

        # Should fail due to timeout
        assert result.success is False
        assert "Timeout" in result.error


@pytest.mark.asyncio
async def test_fast_handler_completes(client):
    """A fast handler should complete within the timeout."""
    from src.runbooks import executor

    step = {
        "name": "fast-check",
        "type": "fast.step",
        "params": {"url": "http://fast.example.com"},
        "timeout": 5,  # 5 second timeout
    }
    context = {}

    # Create a fast handler
    async def fast_handler(params, timeout):
        return {"status": "ok", "response_time_ms": 10}

    # Patch the handler registry
    with patch.object(executor, "STEP_HANDLERS", {"fast.step": fast_handler}):
        result = await executor._execute_step(step, context)

        assert result.success is True
        assert result.output["status"] == "ok"


@pytest.mark.asyncio
async def test_timeout_error_logged_with_step_details(client):
    """Timeout errors should be logged with step details."""
    from src.runbooks import executor

    step = {
        "name": "slow-check",
        "type": "slow.step",
        "params": {"url": "http://slow.example.com"},
        "timeout": 1,
    }
    context = {}

    async def slow_handler(params, timeout):
        await asyncio.sleep(10)
        return {"status": "ok"}

    with (
        patch.object(executor, "STEP_HANDLERS", {"slow.step": slow_handler}),
        patch.object(executor, "logger") as mock_logger,
    ):
        result = await executor._execute_step(step, context)

        # Should have logged at error level
        assert result.success is False
        assert mock_logger.error.called
        # Error message should contain step name and timeout
        error_call_args = str(mock_logger.error.call_args)
        assert "slow-check" in error_call_args


@pytest.mark.asyncio
async def test_default_timeout_applied_when_not_specified(client):
    """When timeout is not specified, a default should be applied."""
    from src.runbooks import executor

    step = {
        "name": "check",
        "type": "check.step",
        "params": {"url": "http://example.com"},
        # No timeout specified - should use default (30s)
    }
    context = {}

    captured_timeout = [None]

    async def check_handler(params, timeout):
        captured_timeout[0] = timeout
        return {"status": "ok"}

    with patch.object(executor, "STEP_HANDLERS", {"check.step": check_handler}):
        result = await executor._execute_step(step, context)

        assert result.success is True
        # Default timeout should be 30
        assert captured_timeout[0] == 30


@pytest.mark.asyncio
async def test_unknown_step_type_returns_placeholder(client):
    """An unknown step type should return a placeholder without timeout."""
    from src.runbooks import executor

    step = {
        "name": "unknown-step",
        "type": "unknown.type",
        "params": {},
        "timeout": 5,
    }
    context = {}

    result = await executor._execute_step(step, context)

    # Unknown step types return placeholder immediately
    assert result.success is True
    assert result.output["status"] == "requires_agent_execution"
