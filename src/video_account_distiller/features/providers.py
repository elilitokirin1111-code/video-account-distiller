"""Mockable Phase 3 text model provider and offline deterministic file adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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


class OllamaTextProvider:
    """Local text analysis through Ollama's OpenAI-compatible API.

    Uses the same model and base URL as the vision provider.
    """

    provider_name = "ollama"

    def __init__(
        self,
        *,
        model: str = "qwen3-vl:8b",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 180,
    ) -> None:
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        temperature: float = 0.0,
    ) -> ResponseT:
        """Call Ollama with a prompt and validate the response against the schema."""
        schema = response_model.model_json_schema()
        body = json.dumps(
            {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature},
                "format": schema,
            }
        ).encode()
        url = f"{self.base_url}/api/chat"
        request = Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModelSchemaFailure(f"Ollama text request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise ModelSchemaFailure("Ollama returned a non-dict response")
        raw = result.get("message", {}).get("content", "")
        if not raw:
            raise ModelSchemaFailure("Ollama returned an empty text response")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelSchemaFailure(f"Ollama response is not valid JSON: {raw[:200]}") from exc
        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            compact_errors = [
                {"loc": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_url=False)
            ]
            raise ModelSchemaFailure(
                f"Ollama response failed schema validation: {compact_errors}"
            ) from exc
