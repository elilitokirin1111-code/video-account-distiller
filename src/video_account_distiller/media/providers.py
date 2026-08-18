"""Mockable Phase 6 visual/OCR provider and deterministic offline file adapter."""

from __future__ import annotations

import base64
import json
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

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


class VisionProviderUnavailable(Exception):
    """The configured visual model service could not serve a request."""


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
        except HTTPError as exc:
            raise VisionProviderUnavailable(
                f"model service request failed with HTTP {exc.code}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise VisionProviderUnavailable(
                f"model service is unavailable: {type(exc).__name__}"
            ) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VisionSchemaFailure(
                f"model service returned invalid JSON: {type(exc).__name__}"
            ) from exc
        if not isinstance(result, dict):
            raise VisionSchemaFailure("local Ollama response root must be an object")
        return result


_VisionSummary = Annotated[str, StringConstraints(max_length=240)]
_VisionLabel = Annotated[str, StringConstraints(max_length=80)]
_VisionOcrText = Annotated[str, StringConstraints(min_length=1, max_length=160)]


class _OllamaOcrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: _VisionOcrText
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: list[float] | None = Field(default=None, min_length=4, max_length=4)


class _OllamaFrameResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_index: int = Field(ge=0)
    summary: _VisionSummary | None = Field(
        default=None,
        description="One concise factual Chinese sentence about this exact frame.",
    )
    labels: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=12,
        description="Concrete visible people, objects, or hotel scenes; never field names.",
    )
    dominant_colors: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Concrete visible colors such as 暖金色 or 米白色.",
    )
    shot_scale: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=3,
        description="Concrete visible shot scale such as 特写, 近景, 中景, 全景, or 远景.",
    )
    camera_movement: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=4,
        description="Best-effort camera motion such as 固定机位, 手持, 推镜, 摇镜, 移镜, or 跟拍.",
    )
    composition: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Concrete framing such as 居中构图, 对称构图, 三分法, or 引导线; "
        "shot scale belongs in shot_scale.",
    )
    camera: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Concrete viewpoint/angle such as 平视, 俯视, 仰视, or 斜角.",
    )
    lighting: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Concrete visible lighting such as 暖光, 自然光, or 逆光.",
    )
    text_overlay_styles: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Concrete subtitle or artistic text style, not the recognized OCR words.",
    )
    motion_graphics: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Only visible stickers or graphic effects; empty when not certain.",
    )
    branding: list[_VisionLabel] = Field(
        default_factory=list,
        max_length=8,
        description="Only visible logos, brand names, or branded objects.",
    )
    ocr: list[_OllamaOcrResult] = Field(default_factory=list, max_length=12)
    confidence: float | None = Field(default=None, ge=0, le=1)


class _OllamaVisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frames: list[_OllamaFrameResult]
    unknowns: list[_VisionSummary] = Field(default_factory=list, max_length=12)


def _parse_structured_vision_response(
    content: str,
    *,
    provider_label: str,
) -> _OllamaVisionResponse:
    """Accept strict JSON plus common Markdown/prose wrappers from local VLMs."""

    stripped = content.strip()
    candidates = [stripped]
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().casefold() in {"```", "```json"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidates.append("\n".join(lines).strip())
    object_start = stripped.find("{")
    if object_start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(stripped[object_start:])
        except json.JSONDecodeError:
            pass
        else:
            candidates.append(json.dumps(value, ensure_ascii=False))

    validation_errors: list[dict[str, Any]] = []
    for candidate in dict.fromkeys(item for item in candidates if item):
        try:
            return _OllamaVisionResponse.model_validate_json(candidate)
        except ValidationError as exc:
            validation_errors = [
                {"loc": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_url=False)
            ]
    raise VisionSchemaFailure(f"{provider_label} vision schema invalid: {validation_errors}")


OLLAMA_VISION_PROMPT_VERSION = "1.4.0"
LLAMACPP_VISION_CONTRACT_VERSION = "1.3.0"
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
    "机位角度",
    "可见镜头感",
    "运镜",
    "运镜痕迹",
    "镜头感",
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
    except (VisionProviderUnavailable, VisionSchemaFailure):
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
            "你是短视频画面语义分析器。只描述图片中可以直接观察到的事实，"
            "不要推测人物身份、地点、经营结果或因果关系。图片顺序与 frame_index 一致。\n"
            "每张图片必须返回一条结果，识别人物、物体、酒店场景、景别、运镜痕迹、机位角度、"
            "构图、灯光、主色、字幕或艺术字样式、贴纸动效痕迹、品牌露出，以及清晰可见的 OCR。"
            "景别只填特写/近景/中景/全景/远景等可见画幅；运镜痕迹（固定机位/手持/推拉摇移跟等）"
            "和机位角度（平视/俯视/仰视/斜角等）只能从画面线索推断，不确定就返回空数组。"
            "无法确认的列表字段返回空数组，不要用‘无’‘未知’‘未确认’作为标签。"
            "bounding_box 使用 [x1,y1,x2,y2] 的 0 到 1 归一化坐标。\n"
            "只返回一个合法 JSON 对象，不要 Markdown、代码围栏、解释或 YAML。结构必须是：\n"
            '{"frames":[{"frame_index":0,"summary":"一句画面事实",'
            '"labels":[],"dominant_colors":[],"shot_scale":[],"camera_movement":[],'
            '"composition":[],"camera":[],'
            '"lighting":[],"text_overlay_styles":[],"motion_graphics":[],'
            '"branding":[],"ocr":[{"text":"可见文字","confidence":0.9,'
            '"bounding_box":[0.1,0.1,0.9,0.2]}],"confidence":0.9}],'
            '"unknowns":[]}\n'
            f"本批图片映射：\n{frame_map}"
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
        return _parse_structured_vision_response(content, provider_label="Ollama")

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation:
        """Analyze bounded keyframes and map every result back to immutable evidence."""

        shot_values: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "summaries": [],
                "labels": set(),
                "dominant_colors": set(),
                "shot_scale": set(),
                "camera_movement": set(),
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
                    "shot_scale",
                    "camera_movement",
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
                shot_scale=sorted(values["shot_scale"]),
                camera_movement=sorted(values["camera_movement"]),
                camera_angle=sorted(values["camera"]),
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
    return f"http://{parsed.hostname}:{parsed.port or 8081}"


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
    except (VisionProviderUnavailable, VisionSchemaFailure):
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
        base_url: str = "http://127.0.0.1:8081",
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
        # This llama.cpp/Qwen3-VL runtime can silently omit later images in a
        # multi-image request. Single-image batches preserve evidence coverage.
        self.batch_size = 1
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
                "structured_output_version": LLAMACPP_VISION_CONTRACT_VERSION,
            }
        )

    @staticmethod
    def _response_schema(batch_size: int) -> dict[str, Any]:
        """Build a grammar-ready schema with exact coverage for this request."""

        schema = _OllamaVisionResponse.model_json_schema()
        schema["required"] = list(schema["properties"])
        for definition in schema["$defs"].values():
            if isinstance(definition, dict) and isinstance(definition.get("properties"), dict):
                definition["required"] = list(definition["properties"])
        frames = schema["properties"]["frames"]
        frames["minItems"] = batch_size
        frames["maxItems"] = batch_size
        frame_result = schema["$defs"]["_OllamaFrameResult"]
        frame_index = frame_result["properties"]["frame_index"]
        frame_index["minimum"] = 0
        frame_index["maximum"] = batch_size - 1
        if batch_size == 1:
            frame_index["const"] = 0
        return schema

    @staticmethod
    def _structured_output_options(schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "max_tokens": 4096,
            "chat_template_kwargs": {"enable_thinking": False},
            # llama.cpp converts this schema to a token-level grammar.
            # json_object without schema only guarantees generic JSON.
            "response_format": {"type": "json_object", "schema": schema},
        }

    @staticmethod
    def _completion_candidates(payload: dict[str, Any]) -> tuple[list[str], str]:
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else None
        message = choice.get("message") if isinstance(choice, dict) else None
        finish_reason = str(choice.get("finish_reason") or "unknown") if choice else "unknown"
        if not isinstance(message, dict):
            return [], finish_reason
        candidates = [
            value
            for key in ("content", "reasoning_content")
            if isinstance((value := message.get(key)), str) and value.strip()
        ]
        return list(dict.fromkeys(candidates)), finish_reason

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
        schema = self._response_schema(len(batch))
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        errors: list[str] = []
        previous_output = ""
        for model_attempt in range(1, 3):
            if model_attempt == 2:
                if "finish_reason=length" in errors[-1]:
                    retry_content = [
                        {
                            "type": "text",
                            "text": (
                                self._prompt(batch) + "\n上一条输出因长度上限被截断。"
                                "请从原图重新生成更精简的完整 JSON："
                                "summary 只写一句；每个分类最多 5 项；OCR 最多 8 项；"
                                "不得重复、解释、使用 Markdown 或省略必需字段。"
                            ),
                        },
                        *content[1:],
                    ]
                    # A truncated assistant turn can bias the model to continue the
                    # broken JSON. Re-send the original image and a compact contract.
                    messages = [{"role": "user", "content": retry_content}]
                else:
                    messages = [
                        messages[0],
                        {"role": "assistant", "content": previous_output[:4000]},
                        {
                            "role": "user",
                            "content": (
                                "上一条输出未通过严格 JSON Schema 校验。"
                                f"错误：{errors[-1]}。请重新检查同一张图片并输出完整替代结果；"
                                "不得解释、不得使用 Markdown、不得省略必需字段。"
                            ),
                        },
                    ]
            payload = self.executor.request_json(
                url=_chat_completions_url(self.base_url),
                method="POST",
                payload={
                    "model": self.model_name,
                    "messages": messages,
                    "temperature": 0,
                    "stream": False,
                    **self._structured_output_options(schema),
                },
                timeout_seconds=self.timeout_seconds,
                headers=({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            )
            self.raw_responses.append(payload)
            candidates, finish_reason = self._completion_candidates(payload)
            if not candidates:
                errors.append(
                    f"attempt {model_attempt}: no message content (finish_reason={finish_reason})"
                )
                previous_output = "{}"
                continue
            previous_output = candidates[0]
            candidate_errors: list[str] = []
            for candidate in candidates:
                try:
                    return _parse_structured_vision_response(
                        candidate,
                        provider_label="llama.cpp",
                    )
                except VisionSchemaFailure as exc:
                    candidate_errors.append(str(exc))
            errors.append(
                f"attempt {model_attempt}: finish_reason={finish_reason}; "
                + "; ".join(candidate_errors)
            )
        raise VisionSchemaFailure(
            "llama.cpp vision remained schema-invalid after 2 model-level attempts: "
            + " | ".join(errors)
        )


def _chat_completions_url(base_url: str) -> str:
    """Join the chat-completions path onto an OpenAI-compatible base URL.

    Alibaba Model Studio compatible endpoints already end with
    ``/compatible-mode/v1``; plain OpenAI-compatible roots keep the ``/v1``
    segment. Scheme-less hosts are defaulted to HTTPS.
    """
    normalized = (base_url or "").strip().rstrip("/")
    if normalized and "://" not in normalized:
        normalized = f"https://{normalized}"
    if normalized.endswith("/compatible-mode/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


class CloudVisionProvider(LlamaCppVisionProvider):
    """Any OpenAI-compatible vision API (DashScope Qwen-VL, OpenAI, etc.)."""

    provider_name = "cloud"

    @staticmethod
    def _structured_output_options(schema: dict[str, Any]) -> dict[str, Any]:
        del schema
        # Preserve compatibility with generic OpenAI-compatible cloud APIs;
        # llama.cpp-specific grammar and chat-template parameters are local only.
        return {"response_format": {"type": "json_object"}}

    def __init__(
        self,
        *,
        model: str = "qwen-vl-max-latest",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        batch_size: int = 4,
        timeout_seconds: int = 180,
        api_key: str | None = None,
        executor: VisionHttpExecutor | None = None,
    ) -> None:
        if not model.strip() or len(model) > 128:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Invalid cloud vision model name")
        if batch_size < 1 or batch_size > 8:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Vision batch size must be 1 through 8")
        if timeout_seconds < 1 or timeout_seconds > 1800:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Vision timeout must be 1 through 1800 seconds",
            )
        raw_base_url = base_url.strip()
        # Users often paste Alibaba Model Studio MaaS gateways without a scheme.
        if "://" not in raw_base_url:
            raw_base_url = f"https://{raw_base_url}"
        parsed = urlparse(raw_base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"})
        ):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Cloud vision base URL must be an HTTPS origin (or loopback HTTP)",
            )
        self.model_name = model.strip()
        self.base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
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
