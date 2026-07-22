"""Stable internal identifier helpers."""

from __future__ import annotations

import hashlib
import uuid


def stable_id(prefix: str, *parts: object, length: int = 20) -> str:
    """Create a stable ID from a namespace prefix and source identifiers."""

    canonical = "\x1f".join(str(part).strip() for part in parts)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}{digest}"


def new_run_id() -> str:
    """Create a sortable-enough random run identifier without external state."""

    return f"run_{uuid.uuid4().hex}"
