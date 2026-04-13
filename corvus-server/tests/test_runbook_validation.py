"""Tests for runbook schema validation (T1.2) and ReDoS protection (D1.3)."""

import pytest
import yaml

from src.runbooks.loader import (
    RunbookRegistry,
    RunbookValidationError,
    _validate_regex_pattern,
    _validate_runbook_schema,
)


class TestRunbookSchemaValidation:
    def test_valid_runbook(self):
        data = {
            "name": "test-runbook",
            "service_type": "inference",
            "investigation": [
                {"name": "check-health", "type": "http.check", "params": {"url": "http://localhost"}},
            ],
            "diagnosis_hints": [
                {"pattern": "oom|out of memory", "root_cause": "gpu_oom"},
            ],
            "remediation": {"action": "restart"},
        }
        warnings = _validate_runbook_schema(data, "test.yaml")
        assert isinstance(warnings, list)

    def test_missing_name(self):
        data = {"service_type": "inference"}
        with pytest.raises(RunbookValidationError, match="Missing required keys.*name"):
            _validate_runbook_schema(data, "test.yaml")

    def test_missing_service_type(self):
        data = {"name": "test"}
        with pytest.raises(RunbookValidationError, match="Missing required keys.*service_type"):
            _validate_runbook_schema(data, "test.yaml")

    def test_empty_name(self):
        data = {"name": "", "service_type": "inference"}
        with pytest.raises(RunbookValidationError, match="non-empty string"):
            _validate_runbook_schema(data, "test.yaml")

    def test_investigation_not_list(self):
        data = {"name": "test", "service_type": "inference", "investigation": "bad"}
        with pytest.raises(RunbookValidationError, match="must be a list"):
            _validate_runbook_schema(data, "test.yaml")

    def test_investigation_step_not_dict(self):
        data = {"name": "test", "service_type": "inference", "investigation": ["bad"]}
        with pytest.raises(RunbookValidationError, match="must be a dict"):
            _validate_runbook_schema(data, "test.yaml")

    def test_unknown_step_type_warns(self):
        data = {
            "name": "test",
            "service_type": "inference",
            "investigation": [{"type": "custom.unknown"}],
        }
        warnings = _validate_runbook_schema(data, "test.yaml")
        assert any("Unknown step type" in w for w in warnings)

    def test_diagnosis_hints_not_list(self):
        data = {"name": "test", "service_type": "inference", "diagnosis_hints": "bad"}
        with pytest.raises(RunbookValidationError, match="must be a list"):
            _validate_runbook_schema(data, "test.yaml")

    def test_diagnosis_hint_not_dict(self):
        data = {"name": "test", "service_type": "inference", "diagnosis_hints": ["bad"]}
        with pytest.raises(RunbookValidationError, match="must be a dict"):
            _validate_runbook_schema(data, "test.yaml")

    def test_invalid_regex_in_hint(self):
        data = {
            "name": "test",
            "service_type": "inference",
            "diagnosis_hints": [{"pattern": "[invalid"}],
        }
        with pytest.raises(RunbookValidationError, match="Invalid regex"):
            _validate_runbook_schema(data, "test.yaml")

    def test_remediation_not_dict(self):
        data = {"name": "test", "service_type": "inference", "remediation": "bad"}
        with pytest.raises(RunbookValidationError, match="must be a dict"):
            _validate_runbook_schema(data, "test.yaml")


class TestReDoSProtection:
    def test_normal_pattern_compiles(self):
        compiled = _validate_regex_pattern("oom|out of memory", "test")
        assert compiled is not None

    def test_too_long_pattern_rejected(self):
        long_pattern = "a" * 201
        with pytest.raises(RunbookValidationError, match="too long"):
            _validate_regex_pattern(long_pattern, "test")

    def test_nested_quantifier_rejected(self):
        """Classic ReDoS: (a+)+ causes exponential backtracking."""
        with pytest.raises(RunbookValidationError, match="ReDoS"):
            _validate_regex_pattern("(a+)+b", "test")

    def test_nested_star_rejected(self):
        with pytest.raises(RunbookValidationError, match="ReDoS"):
            _validate_regex_pattern("(x*)*y", "test")

    def test_invalid_regex_rejected(self):
        with pytest.raises(RunbookValidationError, match="Invalid regex"):
            _validate_regex_pattern("[unclosed", "test")

    def test_safe_complex_pattern_allowed(self):
        """Non-ReDoS complex patterns should be fine."""
        compiled = _validate_regex_pattern(r"error|failed|timeout|connection\s+refused", "test")
        assert compiled is not None


class TestRunbookRegistryValidation:
    def test_load_valid_yaml(self, tmp_path):
        runbook = {
            "name": "test-runbook",
            "service_type": "proxy",
            "investigation": [],
            "diagnosis_hints": [],
            "remediation": {},
        }
        (tmp_path / "test.yaml").write_text(yaml.dump(runbook))

        reg = RunbookRegistry()
        count = reg.load_directory(tmp_path)
        assert count == 1
        assert reg.get_for_service_type("proxy") is not None

    def test_reject_invalid_yaml(self, tmp_path):
        """Invalid runbooks should be rejected but not crash the registry."""
        bad_runbook = {"invalid": True}  # Missing name and service_type
        (tmp_path / "bad.yaml").write_text(yaml.dump(bad_runbook))

        reg = RunbookRegistry()
        count = reg.load_directory(tmp_path)
        assert count == 0  # Should not load

    def test_reject_redos_pattern(self, tmp_path):
        runbook = {
            "name": "evil-runbook",
            "service_type": "test",
            "diagnosis_hints": [{"pattern": "(a+)+b"}],
        }
        (tmp_path / "evil.yaml").write_text(yaml.dump(runbook))

        reg = RunbookRegistry()
        count = reg.load_directory(tmp_path)
        assert count == 0

    def test_precompiled_patterns(self, tmp_path):
        runbook = {
            "name": "test",
            "service_type": "test",
            "diagnosis_hints": [
                {"pattern": "oom|memory", "root_cause": "oom"},
                {"pattern": "timeout|slow", "root_cause": "timeout"},
            ],
        }
        (tmp_path / "test.yaml").write_text(yaml.dump(runbook))

        reg = RunbookRegistry()
        reg.load_directory(tmp_path)
        loaded = reg.get_for_service_type("test")
        assert loaded is not None
        assert len(loaded.compiled_patterns) == 2
