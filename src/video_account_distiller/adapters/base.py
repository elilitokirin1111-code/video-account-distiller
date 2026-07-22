"""Adapter contracts for current and future authorized sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from video_account_distiller.models import FieldMapping, Platform


class SourceAdapter(Protocol):
    """Minimal offline adapter contract used by Phase 1."""

    def validate_source(self, source: Path) -> None: ...

    def load_records(self, source: Path) -> list[dict[str, Any]]: ...

    def map_fields(
        self,
        records: list[dict[str, Any]],
        *,
        entity: str,
        platform: Platform,
        mapping: FieldMapping | None = None,
    ) -> tuple[list[dict[str, Any]], FieldMapping]: ...
