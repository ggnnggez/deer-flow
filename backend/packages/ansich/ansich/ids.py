from __future__ import annotations

from uuid import uuid4


def new_id() -> str:
    """Return a globally unique, storage-portable Ansich identifier."""

    return str(uuid4())
