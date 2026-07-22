"""Mockable structured text-model provider contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    CommentSignalAnnotation,
    VideoFactExtraction,
    VideoSemanticAnnotation,
)
from video_account_distiller.utils.hashing import sha256_file

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class ModelSchemaFailure(Exception):
    """A provider response could not satisfy the requested schema."""


class TextModelProvider(Protocol):
    """Provider abstraction used by the retrying Phase 3 pipeline."""

    provider_name: str
    model_name: str

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        temperature: float = 0.0,
    ) -> ResponseT: ...


class StructuredFileProvider:
    """Read deterministic structured model responses from an offline JSON file."""

    provider_name = "structured-file"

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if not self.path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING, f"Model output file not found: {self.path}"
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID,
                f"Could not parse model output file: {self.path}",
                details={"reason": str(exc)},
            ) from exc
        if not isinstance(payload, dict):
            raise DistillerError(
                ErrorCode.MODEL_SCHEMA_INVALID,
                "Model output root must be an object",
            )
        self.model_name = str(payload.get("model_name") or self.path.name)
        self.input_hash = sha256_file(self.path)
        self._responses: dict[str, list[object]] = {}
        for key in ("video_fact_extraction", "video_semantic_labeling", "comment_intent"):
            value = payload.get(key)
            if isinstance(value, list):
                self._responses[key] = list(value)
            elif value is not None:
                self._responses[key] = [value]
        self._cursor: dict[str, int] = {}

    @staticmethod
    def _task_key(response_model: type[BaseModel]) -> str:
        if issubclass(response_model, VideoFactExtraction):
            return "video_fact_extraction"
        if issubclass(response_model, VideoSemanticAnnotation):
            return "video_semantic_labeling"
        if issubclass(response_model, CommentSignalAnnotation):
            return "comment_intent"
        raise ModelSchemaFailure(f"Unsupported response model: {response_model.__name__}")

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        temperature: float = 0.0,
    ) -> ResponseT:
        """Return the next scripted candidate and validate it strictly."""

        del prompt, temperature
        task = self._task_key(response_model)
        candidates = self._responses.get(task, [])
        if not candidates:
            raise ModelSchemaFailure(f"No response configured for {task}")
        index = self._cursor.get(task, 0)
        if index >= len(candidates):
            raise ModelSchemaFailure(f"No unused response candidate remains for {task}")
        candidate = candidates[index]
        self._cursor[task] = index + 1
        try:
            return response_model.model_validate(candidate)
        except ValidationError as exc:
            compact_errors = [
                {"loc": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_url=False)
            ]
            raise ModelSchemaFailure(
                f"{task} response failed schema validation: {compact_errors}"
            ) from exc
