"""Mockable Phase 6 visual/OCR provider and deterministic offline file adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import MediaVisionAnnotation, MediaVisionBundle
from video_account_distiller.utils.hashing import sha256_file


class VisionSchemaFailure(Exception):
    """A visual provider result did not satisfy the strict media schema."""


class VisionModelProvider(Protocol):
    """No transport assumptions: cloud clients remain optional and externally supplied."""

    provider_name: str
    model_name: str

    @property
    def input_hash(self) -> str | None: ...

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation: ...


class StructuredVisionFileProvider:
    """Replay one or more schema-targeted visual results from local JSON."""

    provider_name = "structured-file"

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if not self.path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING, f"Vision output file not found: {self.path}"
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID,
                f"Could not parse vision output file: {self.path}",
                details={"reason": str(exc)},
            ) from exc
        if not isinstance(payload, dict):
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID, "Vision output root must be an object"
            )
        self.model_name = str(payload.get("model_name") or self.path.name)
        self.input_hash = sha256_file(self.path)
        configured = payload.get("media_vision")
        self._candidates = list(configured) if isinstance(configured, list) else [configured]
        self._cursor = 0

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation:
        """Return the next candidate and validate it without reading image content."""

        del bundle
        if self._cursor >= len(self._candidates) or self._candidates[self._cursor] is None:
            raise VisionSchemaFailure("No unused media_vision response remains")
        candidate = self._candidates[self._cursor]
        self._cursor += 1
        try:
            return MediaVisionAnnotation.model_validate(candidate)
        except ValidationError as exc:
            compact = [
                {"loc": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_url=False)
            ]
            raise VisionSchemaFailure(f"media_vision failed schema validation: {compact}") from exc
