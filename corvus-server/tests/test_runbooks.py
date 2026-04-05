"""Tests for runbook loader and executor."""

from pathlib import Path

import pytest

from src.runbooks.executor import execute_triage, match_diagnosis
from src.runbooks.loader import RunbookRegistry


@pytest.fixture
def runbook_dir():
    return Path(__file__).parent.parent / "runbooks"


@pytest.fixture
def inference_runbook(runbook_dir):
    registry = RunbookRegistry()
    return registry.load_file(runbook_dir / "triage-inference.yaml")


def test_load_runbook_directory(runbook_dir):
    registry = RunbookRegistry()
    count = registry.load_directory(runbook_dir)
    assert count >= 3  # inference, database, proxy


def test_load_inference_runbook(inference_runbook):
    assert inference_runbook.name == "Inference Service Triage"
    assert inference_runbook.service_type == "inference"
    assert len(inference_runbook.investigation) == 5
    assert len(inference_runbook.diagnosis_hints) >= 4


def test_registry_lookup(runbook_dir):
    registry = RunbookRegistry()
    registry.load_directory(runbook_dir)

    rb = registry.get_for_service_type("inference")
    assert rb is not None
    assert rb.service_type == "inference"

    assert registry.get_for_service_type("nonexistent") is None


def test_service_types_covered(runbook_dir):
    registry = RunbookRegistry()
    registry.load_directory(runbook_dir)

    covered = registry.service_types_covered
    assert "inference" in covered
    assert "database" in covered
    assert "proxy" in covered


def test_match_diagnosis_cuda_oom(inference_runbook):
    result = match_diagnosis(inference_runbook, "CUDA error: out of memory")
    assert result is not None
    assert result["root_cause"] == "gpu_oom"
    assert result["restart_safe"] is False


def test_match_diagnosis_nccl(inference_runbook):
    result = match_diagnosis(inference_runbook, "NCCL timeout on rank 0")
    assert result is not None
    assert result["root_cause"] == "config_error"


def test_match_diagnosis_no_match(inference_runbook):
    result = match_diagnosis(inference_runbook, "Everything is fine")
    assert result is None


@pytest.mark.asyncio
async def test_execute_triage(inference_runbook):
    result = await execute_triage(
        runbook=inference_runbook,
        target="vllm-primary",
        host="tmtdockp01",
        investigation_data={"logs": "CUDA error: out of memory on device 0"},
    )
    assert result.runbook_name == "Inference Service Triage"
    assert result.diagnosis == "gpu_oom"
    assert result.restart_safe is False
    assert result.confidence > 0.5
