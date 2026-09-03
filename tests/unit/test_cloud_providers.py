from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.providers import (
    CloudChatTextProvider,
    LlamaCppTextProvider,
    _chat_completions_url,
    _normalize_https_base_url,
)
from video_account_distiller.insights.gpt_analysis import (
    AnalysisProviderKind,
    BailianModel,
    DeepSeekModel,
    GptAnalysisOptions,
)
from video_account_distiller.media.providers import (
    QWEN_NATIVE_VIDEO_MAX_BYTES,
    CloudVisionProvider,
    DeepSeekVisionProvider,
    QwenNativeVideoProvider,
)
from video_account_distiller.models import (
    MediaVisionBundle,
    VisionInputKeyframe,
    VisionInputShot,
)
from video_account_distiller.workflows.account_distill import build_vision_provider


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("api.deepseek.com", "https://api.deepseek.com"),
        (
            "ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
            "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
        ),
        ("https://api.deepseek.com", "https://api.deepseek.com"),
        ("http://127.0.0.1:8081", "http://127.0.0.1:8081"),
        ("  ", ""),
        ("", ""),
    ],
)
def test_normalize_https_base_url_defaults_scheme(raw: str, expected: str) -> None:
    assert _normalize_https_base_url(raw) == expected


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        (
            "ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        (
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1/chat/completions",
        ),
        (
            "http://127.0.0.1:8082",
            "http://127.0.0.1:8082/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url_avoids_duplicate_v1_path(
    base_url: str,
    expected: str,
) -> None:
    assert _chat_completions_url(base_url) == expected


def test_cloud_text_provider_normalizes_scheme_less_maas_gateway() -> None:
    provider = CloudChatTextProvider(
        model="qwen-max-latest",
        base_url="ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
        api_key="sk-test",
    )
    assert provider.base_url == "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com"


def test_cloud_text_provider_uses_deepseek_switch_for_selected_gateway() -> None:
    direct = CloudChatTextProvider(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-test",
    )
    assert direct._request_options(BaseModel) == {
        "response_format": {"type": "json_object"},
        "reasoning_effort": "high",
        "max_tokens": 65_536,
        "thinking": {"type": "enabled"},
    }

    bailian = CloudChatTextProvider(
        model="deepseek-v4-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
    )
    assert bailian._request_options(BaseModel)["enable_thinking"] is True


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ([{"ok": True}], {"ok": True}),
        ({"output": [{"ok": True}]}, {"ok": True}),
        ('{"result":{"ok":true}}', {"ok": True}),
    ],
)
def test_llamacpp_unwraps_harmless_structured_payload_containers(
    payload: object,
    expected: dict[str, bool],
) -> None:
    assert LlamaCppTextProvider._unwrap_structured_payload(payload) == expected


def test_local_schema_coercion_does_not_drop_object_for_absent_optional_array() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            }
        },
    }

    assert LlamaCppTextProvider._coerce_to_schema({}, schema) == {}


def test_local_schema_coercion_repairs_empty_top_level_limitations() -> None:
    schema = {
        "type": "object",
        "properties": {
            "limitations": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            }
        },
    }

    assert LlamaCppTextProvider._coerce_to_schema(
        {"limitations": []},
        schema,
    ) == {"limitations": ["模型未提供限制说明"]}


def test_cloud_vision_provider_accepts_scheme_less_maas_gateway() -> None:
    provider = CloudVisionProvider(
        model="qwen-vl-max-latest",
        base_url="ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
        api_key="sk-test",
    )
    assert provider.base_url == "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com"


def test_cloud_vision_provider_accepts_any_https_origin_without_scheme() -> None:
    provider = CloudVisionProvider(
        model="qwen-vl-max-latest",
        base_url="openai-compatible.example.com",
        api_key="sk-test",
    )
    assert provider.base_url == "https://openai-compatible.example.com"


def test_cloud_vision_provider_preserves_dashscope_compatible_path() -> None:
    provider = CloudVisionProvider(
        model="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
    )
    assert provider.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


class _RecordingVisionExecutor:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def request_json(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None,
        timeout_seconds: int,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "url": url,
                "method": method,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
                "headers": headers,
            }
        )
        return self.response


def test_qwen37_cloud_provider_sends_native_video_with_keyframe_anchors(
    tmp_path: Path,
) -> None:
    assert QWEN_NATIVE_VIDEO_MAX_BYTES == 256 * 1024 * 1024

    video = tmp_path / "source.mp4"
    video.write_bytes(b"short-video")
    frames: list[VisionInputKeyframe] = []
    shots: list[VisionInputShot] = []
    response_frames: list[dict[str, Any]] = []
    for index in range(2):
        frame = tmp_path / f"frame-{index}.jpg"
        frame.write_bytes(f"jpeg-{index}".encode())
        shot_id = f"shot_{index}"
        shots.append(
            VisionInputShot(shot_id=shot_id, start_ms=index * 1_000, end_ms=(index + 1) * 1_000)
        )
        frames.append(
            VisionInputKeyframe(
                keyframe_id=f"key_{index}",
                shot_id=shot_id,
                timestamp_ms=index * 1_000 + 500,
                path=str(frame),
                sha256=f"{index + 1}" * 64,
            )
        )
        response_frames.append(
            {
                "frame_index": index,
                "summary": f"画面 {index}",
                "labels": [],
                "dominant_colors": [],
                "shot_scale": [],
                "camera_movement": [],
                "composition": [],
                "camera": [],
                "lighting": [],
                "text_overlay_styles": [],
                "motion_graphics": [],
                "branding": [],
                "ocr": [],
                "confidence": 0.9,
            }
        )
    executor = _RecordingVisionExecutor(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"frames": response_frames, "unknowns": []})},
                }
            ]
        }
    )
    provider = QwenNativeVideoProvider(
        model="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-test",
        executor=executor,
    )

    result = provider.analyze(
        MediaVisionBundle(
            video_id="vid_native",
            media_hash="a" * 64,
            shots=shots,
            keyframes=frames,
            source_video_path=str(video),
            duration_ms=2_000,
        )
    )

    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["url"].endswith("/compatible-mode/v1/chat/completions")
    payload = call["payload"]
    assert payload["model"] == "qwen3.7-plus"
    assert payload["enable_thinking"] is False
    content = payload["messages"][0]["content"]
    assert [item["type"] for item in content] == ["text", "video_url", "image_url", "image_url"]
    assert content[1]["video_url"]["fps"] == 2.0
    assert content[1]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert len(result.shot_annotations) == 2


def test_cloud_factory_selects_native_qwen_and_deepseek_vision() -> None:
    qwen = build_vision_provider(
        provider="cloud",
        model="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        batch_size=4,
        timeout_seconds=300,
        api_key="sk-test",
    )
    deepseek = build_vision_provider(
        provider="cloud",
        model="deepseek-v4-flash-vision-exp",
        base_url="https://api.deepseek.com",
        batch_size=4,
        timeout_seconds=300,
        api_key="sk-test",
    )

    assert isinstance(qwen, QwenNativeVideoProvider)
    assert isinstance(deepseek, DeepSeekVisionProvider)
    assert deepseek._structured_output_options({})["thinking"] == {"type": "disabled"}


def test_cloud_vision_provider_rejects_plain_http_remote() -> None:
    with pytest.raises(DistillerError) as exc_info:
        CloudVisionProvider(
            model="qwen-vl-max-latest",
            base_url="http://api.example.com",
            api_key="sk-test",
        )
    assert exc_info.value.code is ErrorCode.SCHEMA_INVALID


def test_gpt_analysis_options_accept_qwen_models_for_bailian() -> None:
    options = GptAnalysisOptions(
        provider=AnalysisProviderKind.BAILIAN,
        model=BailianModel.QWEN_MAX,
    )
    assert options.model == "qwen-max"

    chat = GptAnalysisOptions(
        provider=AnalysisProviderKind.DEEPSEEK,
        model=DeepSeekModel.CHAT,
    )
    assert chat.model == "deepseek-chat"


def test_gpt_analysis_options_infers_bailian_from_qwen_model() -> None:
    options = GptAnalysisOptions.model_validate(
        {"model": "qwen-plus", "template": "content_strategy"}
    )
    assert options.provider.value == "bailian"


class _StubResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body


def test_auth_failure_message_maps_insufficient_quota() -> None:
    from video_account_distiller.common.http_utils import _auth_failure_message

    message = _auth_failure_message(
        _StubResponse(
            403,
            b'{"error":{"code":"insufficient_quota","message":"Free quota exhausted."}}',
        ),
        status=403,
    )
    assert "额度不足" in message
    assert "insufficient_quota" in message


def test_auth_failure_message_maps_invalid_api_key() -> None:
    from video_account_distiller.common.http_utils import _auth_failure_message

    message = _auth_failure_message(
        _StubResponse(401, b'{"error":{"code":"invalid_api_key","message":"bad key"}}'),
        status=401,
    )
    assert "API Key 无效" in message


def test_auth_failure_message_falls_back_to_generic() -> None:
    from video_account_distiller.common.http_utils import _auth_failure_message

    message = _auth_failure_message(_StubResponse(403, b"nope"), status=403)
    assert message == "API rejected the credential or permission scope"
