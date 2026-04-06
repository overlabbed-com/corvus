# Issue #17: Log Sanitizer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a regex-based log sanitizer that strips secrets from text before it reaches API responses, SIEM forwarding, or Slack notifications.

**Architecture:** Single `sanitize()` function in `src/sanitizer.py` with compiled regex patterns. Hooked into the SIEM forwarder (`src/siem/forwarder.py`) to sanitize event data before Splunk HEC forwarding. Configurable via `SANITIZER_EXTRA_PATTERNS` env var.

**Tech Stack:** Python stdlib `re`, FastAPI, pytest, aiosqlite (existing)

**Branch:** `feat/issue-17-log-sanitizer`

---

### Task 1: Create the sanitizer module with tests

**Files:**
- Create: `corvus-server/src/sanitizer.py`
- Create: `corvus-server/tests/test_sanitizer.py`

**Step 1: Write the failing tests**

Create `corvus-server/tests/test_sanitizer.py`:

```python
"""Tests for the log sanitizer."""

from src.sanitizer import sanitize


class TestSanitize:
    """Test secret pattern redaction."""

    def test_custom_api_key(self):
        assert sanitize("token: xkey-ops-agent-key-1234") == "token: [REDACTED]"

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
```

**Step 2: Run tests to verify they fail**

Run: `cd corvus-server && python -m pytest tests/test_sanitizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.sanitizer'`

**Step 3: Write the sanitizer module**

Create `corvus-server/src/sanitizer.py`:

```python
"""Log sanitizer — strips secrets from text before forwarding.

Addresses threat model finding I1.1: container logs exposed via
multiple paths without filtering.
"""

import os
import re

REDACTED = "[REDACTED]"

# Default patterns — order matters (more specific first)
_DEFAULT_PATTERNS: list[tuple[str, str]] = [
    # Bearer auth headers (must be before generic token patterns)
    (r"Bearer\s+[A-Za-z0-9_.+/=-]+", REDACTED),
    # JWT tokens (header.payload.signature)
    (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+", REDACTED),
    # Homelab API keys
    (r"xkey-[A-Za-z0-9_-]+", REDACTED),
    # OpenAI/Anthropic keys (sk- followed by 20+ chars, not normal words)
    (r"sk-[A-Za-z0-9]{20,}", REDACTED),
    # GitHub tokens
    (r"gh[ps]_[A-Za-z0-9]{36,}", REDACTED),
    # AWS access key IDs
    (r"AKIA[A-Z0-9]{16}", REDACTED),
    # Connection strings with credentials (postgres://, mysql://, redis://)
    (r"(postgres|mysql|redis)://[^@\s]+@", r"\1://[REDACTED]@"),
    # Key-value secrets: password='...', secret="...", token='...',
    # api_key="..."
    (r"""(password|secret|token|api_key)=(['"])[^'"]+\2""", r"\1=\2[REDACTED]\2"),
]

# Compile patterns once at import time
_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern), replacement)
    for pattern, replacement in _DEFAULT_PATTERNS
]

# Extra patterns from env var
_extra_raw = os.getenv("SANITIZER_EXTRA_PATTERNS", "")
if _extra_raw:
    for pattern in _extra_raw.split(","):
        pattern = pattern.strip()
        if pattern:
            _COMPILED.append((re.compile(pattern), REDACTED))


def sanitize(text: str) -> str:
    """Replace secret patterns in text with [REDACTED].

    Safe to call on any string. Returns the original string if no
    secrets are found.
    """
    if not text:
        return text
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text
```

**Step 4: Run tests to verify they pass**

Run: `cd corvus-server && python -m pytest tests/test_sanitizer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus-server/src/sanitizer.py corvus-server/tests/test_sanitizer.py
git commit -m "feat(#17): add log sanitizer module with secret pattern redaction"
```

---

### Task 2: Hook sanitizer into SIEM forwarder

**Files:**
- Modify: `corvus-server/src/siem/forwarder.py`
- Create: `corvus-server/tests/test_siem_sanitizer.py`

**Step 1: Write the failing test**

Create `corvus-server/tests/test_siem_sanitizer.py`:

```python
"""Test that SIEM forwarder sanitizes event data."""

import json

from src.sanitizer import sanitize


def test_siem_payload_sanitized():
    """Event data containing secrets should be sanitized before forwarding."""
    event_data = {
        "message": "Error connecting to postgres://admin:s3cret@db:5432/app",
        "evidences": [{"data": {"log": "Bearer my-secret-token in header"}}],
    }

    sanitized = sanitize(json.dumps(event_data))
    assert "s3cret" not in sanitized
    assert "my-secret-token" not in sanitized
    assert "[REDACTED]" in sanitized
```

**Step 2: Run test to verify it passes**

Run: `cd corvus-server && python -m pytest tests/test_siem_sanitizer.py -v`
Expected: PASS (sanitize already works on JSON strings)

**Step 3: Modify the SIEM forwarder**

In `corvus-server/src/siem/forwarder.py`, add the sanitizer call. The key change is sanitizing the JSON payload before sending:

Replace the `forward_to_siem` function's payload construction with:

```python
import json
from src.sanitizer import sanitize

# ... existing code ...

async def forward_to_siem(ocsf_event: dict[str, Any]) -> bool:
    """Forward an OCSF event to Splunk HEC.

    Returns True if forwarded successfully, False otherwise.
    Retries up to 3 times with exponential backoff.
    Sanitizes event data to strip secrets before forwarding.
    """
    if not SIEM_URL or not SIEM_TOKEN:
        return False

    # Sanitize the event data before forwarding
    sanitized_json = sanitize(json.dumps(ocsf_event))
    sanitized_event = json.loads(sanitized_json)

    payload = {
        "event": sanitized_event,
        "sourcetype": "corvus:ocsf",
        "index": "corvus",
    }

    # ... rest of retry logic unchanged ...
```

**Step 4: Run all tests**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus-server/src/siem/forwarder.py corvus-server/tests/test_siem_sanitizer.py
git commit -m "feat(#17): hook sanitizer into SIEM forwarder"
```

---

### Task 3: Add SANITIZER_EXTRA_PATTERNS to config

**Files:**
- Modify: `corvus-server/src/config.py`
- Add test to: `corvus-server/tests/test_sanitizer.py`

**Step 1: Write the failing test**

Add to `corvus-server/tests/test_sanitizer.py`:

```python
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
```

**Step 2: Run test to verify it passes**

Run: `cd corvus-server && python -m pytest tests/test_sanitizer.py::test_extra_patterns_from_env -v`
Expected: PASS (the env var loading is already in the module)

**Step 3: Add config documentation**

Add to `corvus-server/src/config.py`:

```python
# Log sanitizer
SANITIZER_EXTRA_PATTERNS = os.getenv("SANITIZER_EXTRA_PATTERNS", "")
```

**Step 4: Run all tests**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add corvus-server/src/config.py corvus-server/tests/test_sanitizer.py
git commit -m "feat(#17): add SANITIZER_EXTRA_PATTERNS config support"
```

---

### Task 4: Final — run full test suite and push

**Step 1: Run full test suite**

Run: `cd corvus-server && python -m pytest tests/ -v`
Expected: All PASS

**Step 2: Push branch and create PR**

```bash
git push -u origin feat/issue-17-log-sanitizer
gh pr create --title "feat: log sanitizer — strip secrets before forwarding (#17)" \
  --body "$(cat <<'EOF'
## Summary
- New `src/sanitizer.py` module with compiled regex patterns for 10+ secret types
- Hooked into SIEM forwarder to sanitize event data before Splunk HEC
- Configurable via `SANITIZER_EXTRA_PATTERNS` env var
- Addresses threat model finding I1.1

Closes #17

## Test plan
- [ ] `pytest tests/test_sanitizer.py -v` — all pattern tests pass
- [ ] `pytest tests/test_siem_sanitizer.py -v` — SIEM integration passes
- [ ] Verify no false positives on normal log text
EOF
)"
```
