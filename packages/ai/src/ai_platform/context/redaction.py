"""Strip secrets before anything is placed in model context.

This is defence in depth, not the primary control: secrets should never be readable by the
context builder in the first place. TODO: context builders (project files, device logs) that
use this before sending data to any provider.
"""

from __future__ import annotations

import re
from typing import Any, Final

REDACTED: Final = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|certificate|"
    r"aws_access_key_id|aws_secret_access_key|session[_-]?token)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERNS: Final = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S),
    re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key ids
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if _SENSITIVE_KEY.search(str(k)) else redact(v)) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    return value
