from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_CREDENTIAL_PATTERNS = (
    re.compile(
        r"(?i)\b(?:"
        r"sk-(?:(?:proj|live|test)-)?[a-z0-9_-]{20,}"
        r"|gh[pousr]_[a-z0-9]{20,}"
        r"|github_pat_[a-z0-9_]{20,}"
        r"|xox[baprs]-[a-z0-9-]{20,}"
        r")\b"
    ),
    re.compile(
        r"(?i)\b(?:authorization\s*[:=]\s*)?"
        r"(?:bearer|basic)\s+[a-z0-9._~+/-]{12,}={0,2}\b"
    ),
    re.compile(
        r"(?i)\b[a-z][a-z0-9+.-]*://"
        r"[^\s/:@]{1,128}:[^\s/@]{8,256}@"
    ),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|"
        r"password|credential)\b\s*(?::|=|\bis\b)\s*"
        r"['\"]?[a-z0-9._~+/-]{16,}={0,2}"
    ),
)
_CREDENTIAL_FIELD = re.compile(
    r"(?i)(?:^|[_ -])(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|"
    r"password|credential|authorization)(?:$|[_ -])"
)
_CREDENTIAL_VALUE = re.compile(r"^[a-z0-9._~+/-]{16,}={0,2}$", re.IGNORECASE)


def contains_credential_like_material(value: object) -> bool:
    """Conservatively detect high-confidence credential shapes in safe manifests."""

    if isinstance(value, str):
        return any(pattern.search(value) is not None for pattern in _CREDENTIAL_PATTERNS)
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and _CREDENTIAL_FIELD.search(key) is not None and isinstance(child, str) and _CREDENTIAL_VALUE.fullmatch(child.strip()) is not None:
                return True
            if contains_credential_like_material(key) or contains_credential_like_material(child):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return any(contains_credential_like_material(child) for child in value)
    return False
