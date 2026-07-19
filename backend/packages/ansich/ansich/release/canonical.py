from __future__ import annotations

import hashlib

from ansich.assessment.base import canonical_json_bytes, canonical_json_value


def sha256_canonical(value: object) -> str:
    """Hash a value with Ansich's single shared canonical JSON implementation."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = ["canonical_json_bytes", "canonical_json_value", "sha256_canonical"]
