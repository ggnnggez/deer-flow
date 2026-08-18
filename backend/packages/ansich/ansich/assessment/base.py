from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ansich.contracts import NamedVersion

AuthorityClass = Literal[
    "human_override",
    "deterministic",
    "configured_rule",
    "soft_human",
    "automated",
]
FidelityClass = Literal["hard", "rule", "soft"]

_SECRET_FIELD_NAMES = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "dsn",
        "idtoken",
        "password",
        "passwd",
        "refreshtoken",
        "setcookie",
    }
)
_REDACTED = "<redacted>"


def _normalized_field_name(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _normalized_string(value: str, known_secrets: frozenset[str]) -> str:
    normalized = unicodedata.normalize("NFC", value)
    for secret in sorted(known_secrets, key=len, reverse=True):
        normalized = normalized.replace(secret, _REDACTED)
    return normalized


def canonical_json_value(
    value: object,
    *,
    filter_secret_fields: bool = False,
    known_secrets: Sequence[str] = (),
) -> object:
    """Return a deterministic JSON value suitable for identity hashing.

    Object keys and strings use Unicode NFC, integral floats collapse to
    integers, negative zero collapses to zero, and arrays retain their order.
    Secret-bearing mapping fields are omitted before hashing. Known exact
    secret values are replaced without retaining the original bytes.
    """

    secrets = frozenset(secret for secret in known_secrets if secret)

    def normalize(item: object) -> object:
        if item is None or isinstance(item, bool | int):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("canonical JSON does not support non-finite numbers")
            if item == 0:
                return 0
            if item.is_integer():
                return int(item)
            return item
        if isinstance(item, str):
            return _normalized_string(item, secrets)
        if isinstance(item, Mapping):
            result: dict[str, object] = {}
            for raw_key, child in item.items():
                if not isinstance(raw_key, str):
                    raise ValueError("canonical JSON object keys must be strings")
                key = unicodedata.normalize("NFC", raw_key)
                if filter_secret_fields and _normalized_field_name(key) in _SECRET_FIELD_NAMES:
                    continue
                if key in result:
                    raise ValueError("canonical JSON keys collide after Unicode normalization")
                result[key] = normalize(child)
            return {key: result[key] for key in sorted(result)}
        if isinstance(item, Sequence) and not isinstance(item, bytes | bytearray):
            return [normalize(child) for child in item]
        raise ValueError(f"unsupported canonical JSON value: {type(item).__name__}")

    return normalize(value)


def canonical_json_bytes(
    value: object,
    *,
    filter_secret_fields: bool = False,
    known_secrets: Sequence[str] = (),
) -> bytes:
    normalized = canonical_json_value(
        value,
        filter_secret_fields=filter_secret_fields,
        known_secrets=known_secrets,
    )
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_config_hash(config: object) -> str:
    return hashlib.sha256(canonical_json_bytes(config)).hexdigest()


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    obs_id: str = Field(min_length=1)
    role: str = Field(default="supporting", min_length=1)


class AssessorDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    input_observation_kinds: tuple[str, ...]
    output_field: str = Field(min_length=1)
    authority_class: AuthorityClass
    fidelity_class: FidelityClass


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    value: dict[str, object]
    as_of: datetime
    asserted_at: datetime
    assessor: NamedVersion
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_class: AuthorityClass
    fidelity_class: FidelityClass
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: tuple[EvidenceRef, ...] = ()

    @field_validator("as_of", "asserted_at")
    @classmethod
    def _timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("assessment timestamps must be timezone-aware")
        return value
