"""Mockable Phase 3 text model provider and offline deterministic file adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    CommentSignalAnnotation,
    SingleVideoDeepOutput,
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
        for key in (
            "video_fact_extraction",
            "video_semantic_labeling",
            "comment_intent",
            "single_video_deep_distillation",
        ):
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
        if issubclass(response_model, SingleVideoDeepOutput):
            return "single_video_deep_distillation"
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
    """Local text analysis through Ollama's chat API.

    Uses a compact field guide derived from the response schema instead of the
    full JSON schema, because small local models return empty or malformed
    output when the prompt embeds a very long schema.
    """

    provider_name = "ollama"

    def __init__(
        self,
        *,
        model: str = "qwen3:8b",
        base_url: str = "http://127.0.0.1:11434",
        timeout_seconds: int = 180,
    ) -> None:
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _field_guide(response_model: type[BaseModel]) -> str:
        """Build a compact, human-readable JSON shape from the Pydantic schema."""

        schema = response_model.model_json_schema()
        defs = schema.get("$defs") or {}

        def deref(prop: dict[str, Any]) -> dict[str, Any]:
            ref = prop.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                return dict(defs.get(name) or {})
            any_of = prop.get("anyOf")
            if isinstance(any_of, list):
                non_null = [item for item in any_of if item.get("type") != "null"]
                if len(non_null) == 1:
                    merged = dict(non_null[0])
                    merged.setdefault("nullable", True)
                    return merged
            return prop

        def shape(prop: dict[str, Any], depth: int = 0) -> str:
            indent = "  " * depth
            resolved = deref(prop)
            kind = resolved.get("type")
            if kind == "array":
                items = resolved.get("items") or {}
                return f"{indent}[{shape(items, 0).strip()}]"
            if kind == "object":
                props = resolved.get("properties") or {}
                if not props:
                    return f"{indent}{{object}}"
                lines = [f"{indent}{{"]
                for name, sub in props.items():
                    lines.append(f"{indent}  {name}: {shape(sub, depth + 1).strip()}")
                lines.append(f"{indent}}}")
                return "\n".join(lines)
            nullable = "或null" if resolved.get("nullable") else ""
            enum = resolved.get("enum")
            hint = f"（可选值：{'/'.join(str(e) for e in enum)}）" if enum else ""
            return f"{kind}{nullable}{hint}"

        props = schema.get("properties") or {}
        lines = ["输出 JSON，结构如下：", "{"]
        for name, prop in props.items():
            required = "必填" if name in (schema.get("required") or []) else "可选"
            lines.append(f"  {name}: {shape(prop).strip()} ({required})")
        lines.append("}")
        return "\n".join(lines)

    def _build_prompt(self, prompt: str, response_model: type[BaseModel]) -> str:
        """Replace the embedded long schema section with a compact field guide."""
        marker = "## Response schema"
        guide = self._field_guide(response_model)
        if marker in prompt:
            head = prompt.split(marker, 1)[0].rstrip()
            suffix = "\n\n## Response schema（字段说明）\n\n"
            return f"{head}{suffix}{guide}\n\n只输出 JSON，不要其他文字。"
        return f"{prompt}\n\n{guide}\n\n只输出 JSON，不要其他文字。"

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        temperature: float = 0.0,
    ) -> ResponseT:
        """Call Ollama with a prompt and validate the response against the schema."""
        content = self._build_prompt(prompt, response_model)
        body = json.dumps(
            {
                "model": self.model_name,
                "messages": [{"role": "user", "content": content}],
                "stream": False,
                "think": False,
                "options": {"temperature": temperature},
                "format": "json",
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
        except json.JSONDecodeError:
            start = raw.find("{")
            if start >= 0:
                try:
                    # Parse the first complete JSON object and ignore trailing junk
                    # or accidentally concatenated objects from the local model.
                    parsed, _ = json.JSONDecoder().raw_decode(raw[start:])
                except json.JSONDecodeError as exc:
                    raise ModelSchemaFailure(
                        f"Ollama response is not valid JSON: {raw[:200]}"
                    ) from exc
            else:
                raise ModelSchemaFailure(
                    f"Ollama response is not valid JSON: {raw[:200]}"
                ) from None
        try:
            return response_model.model_validate(parsed)
        except ValidationError:
            # Local models produce noisy keys and free-text enum values.
            # Coerce once against the schema before giving up.
            coerced = self._coerce_to_schema(parsed, response_model.model_json_schema())
            try:
                return response_model.model_validate(coerced)
            except ValidationError as exc:
                compact_errors = [
                    {"loc": list(error["loc"]), "type": error["type"]}
                    for error in exc.errors(include_url=False)
                ]
                raise ModelSchemaFailure(
                    f"Ollama response failed schema validation: {compact_errors}"
                ) from exc

    @staticmethod
    def _coerce_to_schema(data: object, schema: dict[str, Any]) -> object:
        """Drop keys outside the schema and map unknown enum values to unknown.

        Recurses through ``$defs``-referenced sub-schemas so nested noise from
        small local models cannot fail an otherwise correct analysis.
        """
        defs = schema.get("$defs") or {}

        def deref(prop: dict[str, Any]) -> dict[str, Any]:
            ref = prop.get("$ref")
            if isinstance(ref, str):
                return dict(defs.get(ref.rsplit("/", 1)[-1]) or prop)
            return prop

        def coerce(value: object, prop: dict[str, Any]) -> object:
            resolved = deref(prop)
            kind = resolved.get("type")
            if kind == "object" and isinstance(value, dict):
                props = resolved.get("properties") or {}
                result: dict[str, object] = {}
                for name, sub in props.items():
                    if name not in value:
                        continue
                    coerced = coerce(value[name], sub)
                    if coerced is not None:
                        result[name] = coerced
                # Drop nested objects whose non-empty array contract is no
                # longer satisfied (e.g. a fact with zero surviving citations).
                for name, sub in props.items():
                    if deref(sub).get("minItems", 0) >= 1:
                        field = result.get(name)
                        if not isinstance(field, list) or not field:
                            return None
                # Required enum fields left out by the model default to unknown.
                for name, sub in props.items():
                    if name in result or name not in (resolved.get("required") or []):
                        continue
                    enum = deref(sub).get("enum")
                    if enum:
                        result[name] = next(
                            (item for item in enum if "unknown" in str(item).lower()),
                            enum[0],
                        )
                return result
            if kind == "array" and isinstance(value, list):
                items = resolved.get("items") or {}
                return [
                    item for item in (coerce(entry, items) for entry in value) if item is not None
                ]
            enum = resolved.get("enum")
            if enum and value not in enum:
                fallback = next(
                    (item for item in enum if "unknown" in str(item).lower()),
                    enum[0],
                )
                return fallback
            return value

        return coerce(data, schema)


class LlamaCppTextProvider(OllamaTextProvider):
    """Local text analysis through a llama.cpp OpenAI-compatible server."""

    provider_name = "llamacpp"

    def __init__(
        self,
        *,
        model: str = "local",
        base_url: str = "http://127.0.0.1:8081",
        timeout_seconds: int = 180,
        api_key: str | None = None,
    ) -> None:
        self.model_name = model or "local"
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key or os.environ.get("DISTILLER_LLAMACPP_API_KEY")

    def generate_structured(
        self,
        prompt: str,
        response_model: type[ResponseT],
        *,
        temperature: float = 0.0,
    ) -> ResponseT:
        """Call llama.cpp with a prompt and validate the response against the schema."""

        content = self._build_prompt(prompt, response_model)
        body = json.dumps(
            {
                "model": self.model_name,
                "messages": [{"role": "user", "content": content}],
                "temperature": temperature,
                "stream": False,
            }
        ).encode()
        url = f"{self.base_url}/v1/chat/completions"
        request_headers = {"Content-Type": "application/json"}
        if self.api_key:
            request_headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            url,
            data=body,
            method="POST",
            headers=request_headers,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModelSchemaFailure(
                f"llama.cpp text request failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(result, dict):
            raise ModelSchemaFailure("llama.cpp returned a non-dict response")
        choices = result.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        raw = message.get("content") if isinstance(message, dict) else None
        if not raw:
            raise ModelSchemaFailure("llama.cpp returned an empty text response")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            if start >= 0:
                try:
                    parsed, _ = json.JSONDecoder().raw_decode(raw[start:])
                except json.JSONDecodeError as exc:
                    raise ModelSchemaFailure(
                        f"llama.cpp response is not valid JSON: {raw[:200]}"
                    ) from exc
            else:
                raise ModelSchemaFailure(
                    f"llama.cpp response is not valid JSON: {raw[:200]}"
                ) from None
        try:
            return response_model.model_validate(parsed)
        except ValidationError:
            coerced = self._coerce_to_schema(parsed, response_model.model_json_schema())
            try:
                return response_model.model_validate(coerced)
            except ValidationError as exc:
                compact_errors = [
                    {"loc": list(error["loc"]), "type": error["type"]}
                    for error in exc.errors(include_url=False)
                ]
                raise ModelSchemaFailure(
                    f"llama.cpp response failed schema validation: {compact_errors}"
                ) from exc


class CloudChatTextProvider(LlamaCppTextProvider):
    """Any OpenAI-compatible chat API (DeepSeek, DashScope, OpenAI, etc.)."""

    provider_name = "cloud"
