"""Mockable Phase 6 visual/OCR provider and deterministic offline file adapter."""

from __future__ import annotations

import base64
import json
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    MediaVisionAnnotation,
    MediaVisionBundle,
    OcrObservation,
    ShotVisualAnnotation,
)
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id


class VisionSchemaFailure(Exception):
    """A visual provider result did not satisfy the strict media schema."""


class VisionModelProvider(Protocol):
    """No transport assumptions: cloud clients remain optional and externally supplied."""

    provider_name: str
    model_name: str

    @property
    def input_hash(self) -> str | None: ...

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation: ...


class VisionHttpExecutor(Protocol):
    """Injectable JSON transport used by local vision providers."""

    def request_json(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None,
        timeout_seconds: int,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class UrllibVisionHttpExecutor:
    """Small dependency-free JSON transport."""

    def request_json(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None,
        timeout_seconds: int,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        request = Request(
            url,
            data=body,
            method=method,
            headers=request_headers,
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise VisionSchemaFailure(f"local Ollama request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise VisionSchemaFailure("local Ollama response root must be an object")
        return result


class _OllamaOcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: list[float] | None = None


class _OllamaFrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_index: int = Field(ge=0)
    summary: str | None = Field(
        default=None,
        description="One concise factual Chinese sentence about this exact frame.",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Concrete visible people, objects, or hotel scenes; never field names.",
    )
    dominant_colors: list[str] = Field(
        default_factory=list,
        description="Concrete visible colors such as 暖金色 or 米白色.",
    )
    composition: list[str] = Field(
        default_factory=list,
        description="Concrete framing such as 居中构图, 对称构图, 近景, or 全景.",
    )
    camera: list[str] = Field(
        default_factory=list,
        description="Concrete viewpoint such as 平视, 俯视, 仰视, or 广角感.",
    )
    lighting: list[str] = Field(
        default_factory=list,
        description="Concrete visible lighting such as 暖光, 自然光, or 逆光.",
    )
    text_overlay_styles: list[str] = Field(
        default_factory=list,
        description="Concrete subtitle or artistic text style, not the recognized OCR words.",
    )
    motion_graphics: list[str] = Field(
        default_factory=list,
        description="Only visible stickers or graphic effects; empty when not certain.",
    )
    branding: list[str] = Field(
        default_factory=list,
        description="Only visible logos, brand names, or branded objects.",
    )
    ocr: list[_OllamaOcrResult] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class _OllamaVisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frames: list[_OllamaFrameResult]
    unknowns: list[str] = Field(default_factory=list)


OLLAMA_VISION_PROMPT_VERSION = "1.1.0"
_FIELD_NAME_ECHOES = {
    "人物/物体/酒店场景",
    "人物",
    "物体",
    "酒店场景",
    "构图景别",
    "构图",
    "景别",
    "机位或可见镜头感",
    "机位",
    "可见镜头感",
    "灯光",
    "主色",
    "字幕和艺术字样式",
    "字幕",
    "艺术字样式",
    "贴纸与动效痕迹",
    "贴纸",
    "动效痕迹",
    "品牌露出",
    "清晰可见的中文 ocr",
    "ocr",
}


def _normalized_bounding_box(values: list[float] | None) -> list[float] | None:
    if values is None:
        return None
    if len(values) != 4 or any(value < 0 for value in values):
        raise VisionSchemaFailure("Ollama returned an invalid OCR bounding_box")
    scale = 1.0 if max(values, default=0) <= 1 else 1000.0
    if any(value > scale for value in values):
        raise VisionSchemaFailure("Ollama OCR bounding_box is outside 0..1 or 0..1000")
    normalized = [round(value / scale, 6) for value in values]
    if normalized[0] > normalized[2] or normalized[1] > normalized[3]:
        raise VisionSchemaFailure("Ollama OCR bounding_box coordinates are reversed")
    return normalized


def _local_ollama_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or (parsed.port or 11434) != 11434
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Ollama base URL must be local http://127.0.0.1:11434",
        )
    return f"http://{parsed.hostname}:11434"


def ollama_model_available(
    *,
    base_url: str,
    model: str,
    executor: VisionHttpExecutor | None = None,
    timeout_seconds: int = 5,
) -> bool:
    """Check only the loopback Ollama model registry."""

    local_url = _local_ollama_base_url(base_url)
    transport = executor or UrllibVisionHttpExecutor()
    try:
        payload = transport.request_json(
            url=f"{local_url}/api/tags",
            method="GET",
            payload=None,
            timeout_seconds=timeout_seconds,
        )
    except VisionSchemaFailure:
        return False
    models = payload.get("models")
    if not isinstance(models, list):
        return False
    names = {str(item.get("name") or "") for item in models if isinstance(item, dict)}
    return model in names or (":" not in model and f"{model}:latest" in names)


class OllamaVisionProvider:
    """Loopback-only Qwen/Ollama keyframe analysis with strict evidence mapping."""

    provider_name = "ollama"

    def __init__(
        self,
        *,
        model: str = "qwen3-vl:8b",
        base_url: str = "http://127.0.0.1:11434",
        batch_size: int = 4,
        timeout_seconds: int = 180,
        executor: VisionHttpExecutor | None = None,
    ) -> None:
        if not model.strip() or len(model) > 128:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Invalid Ollama vision model name")
        if batch_size < 1 or batch_size > 8:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Vision batch size must be 1 through 8")
        if timeout_seconds < 1 or timeout_seconds > 1800:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Vision timeout must be 1 through 1800 seconds",
            )
        self.model_name = model.strip()
        self.base_url = _local_ollama_base_url(base_url)
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.executor = executor or UrllibVisionHttpExecutor()
        self.raw_responses: list[dict[str, Any]] = []
        self.input_hash = sha256_json(
            {
                "provider": self.provider_name,
                "model": self.model_name,
                "base_url": self.base_url,
                "batch_size": self.batch_size,
                "contract": "media-vision-v2",
                "prompt_version": OLLAMA_VISION_PROMPT_VERSION,
            }
        )

    @staticmethod
    def _prompt(batch: Sequence[Any]) -> str:
        frame_map = "\n".join(
            f"- frame_index={index}: keyframe_id={item.keyframe_id}, "
            f"shot_id={item.shot_id}, timestamp_ms={item.timestamp_ms}"
            for index, item in enumerate(batch)
        )
        return (
            "你是酒店短视频视觉分析器。只描述图片中可以直接观察到的事实，不推测真实身份、"
            "地点、经营结果或因果关系。图片顺序与 frame_index 一致。\n"
            "请识别：人物/物体/酒店场景、构图景别、机位或可见镜头感、灯光、主色、"
            "字幕和艺术字样式、贴纸与动效痕迹、品牌露出，以及清晰可见的中文 OCR。"
            "无法确认的字段返回空数组，不要编造。bounding_box 使用 0 到 1 的"
            "[x1,y1,x2,y2] 归一化坐标。每张图必须返回且只返回一条对应 frame_index。"
            "labels 只写具体可见名词；camera 只写平视/俯视/仰视/广角感等具体观察；"
            "不要把“主色、构图、灯光、OCR、品牌露出”等字段名称本身写入任何数组，"
            "不要用“无、未知、未确认”充当标签。\n"
            f"{frame_map}"
        )

    def _analyze_batch(self, batch: Sequence[Any]) -> _OllamaVisionResponse:
        images: list[str] = []
        for item in batch:
            path = Path(item.path)
            if not path.is_file():
                raise VisionSchemaFailure(f"keyframe file not found: {item.keyframe_id}")
            images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        payload = self.executor.request_json(
            url=f"{self.base_url}/api/chat",
            method="POST",
            payload={
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": self._prompt(batch),
                        "images": images,
                    }
                ],
                "format": _OllamaVisionResponse.model_json_schema(),
                "stream": False,
                "think": False,
                "options": {"temperature": 0},
            },
            timeout_seconds=self.timeout_seconds,
        )
        self.raw_responses.append(payload)
        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            content = message.get("thinking") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise VisionSchemaFailure("local Ollama response has no message content")
        try:
            return _OllamaVisionResponse.model_validate_json(content)
        except ValidationError as exc:
            compact = [
                {"loc": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_url=False)
            ]
            raise VisionSchemaFailure(f"Ollama vision schema invalid: {compact}") from exc

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation:
        """Analyze bounded keyframes and map every result back to immutable evidence."""

        shot_values: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "summaries": [],
                "labels": set(),
                "dominant_colors": set(),
                "composition": set(),
                "camera": set(),
                "lighting": set(),
                "text_overlay_styles": set(),
                "motion_graphics": set(),
                "branding": set(),
                "ocr_ids": [],
                "confidences": [],
            }
        )
        observations: list[OcrObservation] = []
        unknowns: list[str] = []
        for offset in range(0, len(bundle.keyframes), self.batch_size):
            batch = bundle.keyframes[offset : offset + self.batch_size]
            response = self._analyze_batch(batch)
            seen: set[int] = set()
            for result in response.frames:
                if result.frame_index >= len(batch) or result.frame_index in seen:
                    raise VisionSchemaFailure("Ollama returned an invalid frame_index")
                seen.add(result.frame_index)
                frame = batch[result.frame_index]
                values = shot_values[frame.shot_id]
                if result.summary:
                    values["summaries"].append(result.summary.strip())
                for key in (
                    "labels",
                    "dominant_colors",
                    "composition",
                    "camera",
                    "lighting",
                    "text_overlay_styles",
                    "motion_graphics",
                    "branding",
                ):
                    values[key].update(
                        item.strip()
                        for item in getattr(result, key)
                        if item.strip()
                        and item.strip().casefold() not in _FIELD_NAME_ECHOES
                        and item.strip() not in {"无", "未知", "未确认", "无法确认"}
                    )
                if result.confidence is not None:
                    values["confidences"].append(result.confidence)
                for index, ocr in enumerate(result.ocr):
                    observation_id = stable_id(
                        "ocr_",
                        bundle.media_hash,
                        frame.keyframe_id,
                        str(index),
                        ocr.text,
                    )
                    observations.append(
                        OcrObservation(
                            observation_id=observation_id,
                            text=ocr.text,
                            shot_id=frame.shot_id,
                            keyframe_id=frame.keyframe_id,
                            start_ms=frame.timestamp_ms,
                            end_ms=frame.timestamp_ms,
                            confidence=ocr.confidence,
                            bounding_box=_normalized_bounding_box(ocr.bounding_box),
                        )
                    )
                    values["ocr_ids"].append(observation_id)
            if len(seen) != len(batch):
                unknowns.append(f"missing_frame_results:{offset}:{len(batch) - len(seen)}")
            unknowns.extend(response.unknowns)
        annotations = [
            ShotVisualAnnotation(
                annotation_id=stable_id(
                    "vis_",
                    bundle.media_hash,
                    shot_id,
                    self.model_name,
                ),
                shot_id=shot_id,
                summary="；".join(dict.fromkeys(values["summaries"]))[:2000] or None,
                labels=sorted(values["labels"]),
                dominant_colors=sorted(values["dominant_colors"]),
                composition=sorted(values["composition"]),
                camera=sorted(values["camera"]),
                lighting=sorted(values["lighting"]),
                text_overlay_styles=sorted(values["text_overlay_styles"]),
                motion_graphics=sorted(values["motion_graphics"]),
                branding=sorted(values["branding"]),
                ocr_observation_ids=list(dict.fromkeys(values["ocr_ids"])),
                confidence=(
                    sum(values["confidences"]) / len(values["confidences"])
                    if values["confidences"]
                    else None
                ),
            )
            for shot_id, values in sorted(shot_values.items())
        ]
        return MediaVisionAnnotation(
            shot_annotations=annotations,
            ocr_observations=observations,
            unknowns=list(dict.fromkeys(item for item in unknowns if item)),
        )


def _local_llamacpp_base_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "llama.cpp base URL must be a local http://127.0.0.1:<port>",
        )
    return f"http://{parsed.hostname}:{parsed.port or 8080}"


def llamacpp_model_available(
    *,
    base_url: str,
    model: str,
    executor: VisionHttpExecutor | None = None,
    timeout_seconds: int = 5,
) -> bool:
    """Check the loopback llama.cpp model registry (OpenAI-compatible endpoint)."""

    local_url = _local_llamacpp_base_url(base_url)
    transport = executor or UrllibVisionHttpExecutor()
    headers = _llamacpp_auth_headers()
    try:
        payload = transport.request_json(
            url=f"{local_url}/v1/models",
            method="GET",
            payload=None,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )
    except VisionSchemaFailure:
        return False
    data = payload.get("data")
    if not isinstance(data, list):
        return False
    ids = {str(item.get("id") or "") for item in data if isinstance(item, dict)}
    return bool(ids) and (model in ids or not model)


def _llamacpp_auth_headers() -> dict[str, str]:
    api_key = os.environ.get("DISTILLER_LLAMACPP_API_KEY")
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


class LlamaCppVisionProvider(OllamaVisionProvider):
    """Loopback-only llama.cpp keyframe analysis via the OpenAI-compatible API."""

    provider_name = "llamacpp"

    def __init__(
        self,
        *,
        model: str = "qwen3-vl-8b",
        base_url: str = "http://127.0.0.1:8080",
        batch_size: int = 4,
        timeout_seconds: int = 180,
        api_key: str | None = None,
        executor: VisionHttpExecutor | None = None,
    ) -> None:
        if not model.strip() or len(model) > 128:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Invalid llama.cpp vision model name")
        if batch_size < 1 or batch_size > 8:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Vision batch size must be 1 through 8")
        if timeout_seconds < 1 or timeout_seconds > 1800:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Vision timeout must be 1 through 1800 seconds",
            )
        self.model_name = model.strip()
        self.base_url = _local_llamacpp_base_url(base_url)
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds
        self.executor = executor or UrllibVisionHttpExecutor()
        self.api_key = api_key or os.environ.get("DISTILLER_LLAMACPP_API_KEY")
        self.raw_responses: list[dict[str, Any]] = []
        self.input_hash = sha256_json(
            {
                "provider": self.provider_name,
                "model": self.model_name,
                "base_url": self.base_url,
                "batch_size": self.batch_size,
                "contract": "media-vision-v2",
                "prompt_version": OLLAMA_VISION_PROMPT_VERSION,
            }
        )

    def _analyze_batch(self, batch: Sequence[Any]) -> _OllamaVisionResponse:
        content: list[dict[str, Any]] = [{"type": "text", "text": self._prompt(batch)}]
        for item in batch:
            path = Path(item.path)
            if not path.is_file():
                raise VisionSchemaFailure(f"keyframe file not found: {item.keyframe_id}")
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )
        payload = self.executor.request_json(
            url=f"{self.base_url}/v1/chat/completions",
            method="POST",
            payload={
                "model": self.model_name,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
                "stream": False,
            },
            timeout_seconds=self.timeout_seconds,
            headers=(
                {"Authorization": f"Bearer {self.api_key}"}
                if self.api_key
                else {}
            ),
        )
        self.raw_responses.append(payload)
        choices = payload.get("choices")
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content_text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content_text, str) or not content_text.strip():
            raise VisionSchemaFailure("local llama.cpp response has no message content")
        try:
            return _OllamaVisionResponse.model_validate_json(content_text)
        except ValidationError as exc:
            compact = [
                {"loc": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_url=False)
            ]
            raise VisionSchemaFailure(f"llama.cpp vision schema invalid: {compact}") from exc


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
