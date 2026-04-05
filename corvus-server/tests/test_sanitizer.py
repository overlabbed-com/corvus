"""Tests for the log sanitizer."""

from src.sanitizer import sanitize


class TestSanitize:
    """Test secret pattern redaction."""

    def test_homelab_api_key(self):
        assert sanitize("token: hlab-nemoclaw-key-1234") == "token: [REDACTED]"

    def test_openai_key(self):
        assert sanitize("key=sk-abc123def456ghi789jkl012mno") == "key=[REDACTED]"

    def test_github_personal_token(self):
        assert sanitize("ghp_ABCDEFghijklmnop1234567890abcdefghijkl") == "[REDACTED]"

    def test_github_server_token(self):
        assert sanitize("ghs_ABCDEFghijklmnop1234567890abcdefghijkl") == "[REDACTED]"

    def test_jwt_token(self):
        text = "Authorization: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123"
        result = sanitize(text)
        assert "eyJ" not in result
        assert "[REDACTED]" in result

    def test_bearer_header(self):
        assert sanitize("Authorization: Bearer my-secret-token") == "Authorization: [REDACTED]"

    def test_postgres_connection_string(self):
        text = "connecting to postgres://admin:s3cret@db.host:5432/mydb"
        result = sanitize(text)
        assert "s3cret" not in result
        assert "[REDACTED]" in result

    def test_redis_connection_string(self):
        text = "redis://user:password123@redis.host:6379"
        result = sanitize(text)
        assert "password123" not in result

    def test_aws_access_key(self):
        assert sanitize("AWS key: AKIAIOSFODNN7EXAMPLE") == "AWS key: [REDACTED]"

    def test_password_in_key_value(self):
        assert sanitize("password='super-secret'") == "password='[REDACTED]'"

    def test_secret_in_key_value(self):
        assert sanitize('secret="my-api-secret"') == 'secret="[REDACTED]"'

    def test_json_key_value_password(self):
        text = '{"password": "super-secret", "user": "admin"}'
        result = sanitize(text)
        assert "super-secret" not in result
        assert '"password": "[REDACTED]"' in result
        assert '"user": "admin"' in result

    def test_json_key_value_api_key(self):
        text = '{"api_key": "abc-123-xyz"}'
        result = sanitize(text)
        assert "abc-123-xyz" not in result

    def test_unquoted_key_value_password(self):
        assert "mysecret" not in sanitize("password=mysecret")
        assert sanitize("password=mysecret") == "password=[REDACTED]"

    def test_unquoted_key_value_token(self):
        result = sanitize("token=abc123 other=keep")
        assert "abc123" not in result
        assert "other=keep" in result

    def test_aws_secret_access_key_json(self):
        text = '{"aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}'
        result = sanitize(text)
        assert "wJalrXUtnFEMI" not in result

    def test_aws_secret_access_key_kv(self):
        text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG"
        result = sanitize(text)
        assert "wJalrXUtnFEMI" not in result

    def test_mongodb_connection_string(self):
        text = "mongodb://admin:s3cret@mongo.host:27017/mydb"
        result = sanitize(text)
        assert "s3cret" not in result
        assert "[REDACTED]" in result

    def test_no_false_positive_skeleton(self):
        """'skeleton' should not match the sk- pattern."""
        assert sanitize("found skeleton in closet") == "found skeleton in closet"

    def test_no_false_positive_skill(self):
        """'skill' should not match the sk- pattern."""
        assert sanitize("new skill learned") == "new skill learned"

    def test_preserves_normal_text(self):
        text = "Container vllm-primary restarted successfully at 2026-03-29T18:00:00Z"
        assert sanitize(text) == text

    def test_multiple_secrets_in_one_line(self):
        text = "key=sk-abc123def456ghi789jkl012mno password='secret123'"
        result = sanitize(text)
        assert "sk-abc" not in result
        assert "secret123" not in result

    def test_empty_string(self):
        assert sanitize("") == ""

    def test_multiline(self):
        text = "line1\npassword='secret'\nline3"
        result = sanitize(text)
        assert "secret" not in result
        assert "line1" in result
        assert "line3" in result


def test_malformed_extra_patterns_does_not_crash(monkeypatch):
    """Invalid regex in SANITIZER_EXTRA_PATTERNS should be skipped, not crash."""
    monkeypatch.setenv("SANITIZER_EXTRA_PATTERNS", r"[invalid(regex,VALID-[A-Z]+")
    import importlib

    import src.sanitizer

    importlib.reload(src.sanitizer)
    from src.sanitizer import sanitize as fresh_sanitize

    # Valid pattern still works
    assert fresh_sanitize("key: VALID-ABC") == "key: [REDACTED]"
    # Normal text unaffected
    assert fresh_sanitize("hello world") == "hello world"
    # Restore
    importlib.reload(src.sanitizer)


def test_extra_patterns_from_env(monkeypatch):
    """Extra patterns from env var should also be applied."""
    monkeypatch.setenv("SANITIZER_EXTRA_PATTERNS", r"CUSTOM-[A-Z0-9]+")
    # Force reimport to pick up env var
    import importlib

    import src.sanitizer

    importlib.reload(src.sanitizer)
    from src.sanitizer import sanitize as fresh_sanitize

    assert fresh_sanitize("key: CUSTOM-ABC123") == "key: [REDACTED]"
    # Restore
    importlib.reload(src.sanitizer)
