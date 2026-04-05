"""Log sanitizer — strips secrets from text before forwarding.

Addresses threat model finding I1.1: container logs exposed via
multiple paths without filtering.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"

# Default patterns — order matters (more specific first)
_DEFAULT_PATTERNS: list[tuple[str, str]] = [
    # Bearer auth headers (must be before generic token patterns)
    (r"Bearer\s+[A-Za-z0-9_.+/=-]+", REDACTED),
    # JWT tokens (header.payload.signature)
    (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+", REDACTED),
    # Homelab API keys
    (r"hlab-[A-Za-z0-9_-]+", REDACTED),
    # OpenAI/Anthropic keys (sk- followed by 20+ chars, not normal words)
    (r"sk-[A-Za-z0-9]{20,}", REDACTED),
    # GitHub tokens
    (r"gh[ps]_[A-Za-z0-9]{36,}", REDACTED),
    # AWS access key IDs
    (r"AKIA[A-Z0-9]{16}", REDACTED),
    # 1Password Connect tokens
    (r"eyJhbGci[A-Za-z0-9_.=-]+", REDACTED),
    # Corvus API keys (corvus- prefix)
    (r"corvus-[a-f0-9]{32,}", REDACTED),
    # Connection strings with credentials (postgres://, mysql://, redis://, mongodb://)
    (r"(postgres|mysql|redis|mongodb)://[^@\s]+@", r"\1://[REDACTED]@"),
    # JSON key-value secrets: "password": "value"
    (
        r'"(password|secret|token|api_key|aws_secret_access_key)"\s*:\s*"[^"]+"',
        r'"\1": "[REDACTED]"',
    ),
    # Key-value secrets: password='...', secret="...", token='...',
    # api_key="...", aws_secret_access_key="..."
    (
        r"""(password|secret|token|api_key|aws_secret_access_key)=(['"])[^'"]+\2""",
        r"\1=\2[REDACTED]\2",
    ),
    # Unquoted key-value secrets: password=value, token=value
    (
        r"(password|secret|token|api_key|aws_secret_access_key)=[^\s,;&'\"]+",
        r"\1=[REDACTED]",
    ),
]

# Compile patterns once at import time
_COMPILED: list[tuple[re.Pattern, str]] = [
    (re.compile(pattern), replacement) for pattern, replacement in _DEFAULT_PATTERNS
]

# Extra patterns from env var
_extra_raw = os.getenv("SANITIZER_EXTRA_PATTERNS", "")
if _extra_raw:
    for pattern in _extra_raw.split(","):
        pattern = pattern.strip()
        if pattern:
            try:
                _COMPILED.append((re.compile(pattern), REDACTED))
            except re.error as exc:
                logger.warning(
                    "Skipping invalid SANITIZER_EXTRA_PATTERNS entry %r: %s",
                    pattern,
                    exc,
                )


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
