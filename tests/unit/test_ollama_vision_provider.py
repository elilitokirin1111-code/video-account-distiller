from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.media.providers import (
    LlamaCppVisionProvider,
    OllamaVisionProvider,
    UrllibVisionHttpExecutor,
    VisionProviderUnavailable,
    VisionSchemaFailure,
    ollama_model_available,
)
from video_account_distiller.models import (
    MediaVisionBundle,
    VisionInputKeyframe,
    VisionInputShot,
)


class RecordingExecutor:
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
            }
        )
        return self.response


class SequencedExecutor(RecordingExecutor):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__(responses[0])
        self.responses = iter(responses)

    def request_json(
        self,
        *,
        url: str,
        method: str,
        payload: dict[str, Any] | None,
        timeout_seconds: int,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        super().request_json(
            url=url,
            method=method,
            payload=payload,
            timeout_seconds=timeout_seconds,
            headers=headers,
        )
        return next(self.responses)


def _bundle(tmp_path: Path) -> MediaVisionBundle:
    frames: list[VisionInputKeyframe] = []
    shots: list[VisionInputShot] = []
    for index in range(2):
        frame = tmp_path / f"frame-{index}.jpg"
        frame.write_bytes(f"jpeg-{index}".encode())
        shot_id = f"shot_{index}"
        shots.append(
            VisionInputShot(
                shot_id=shot_id,
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
            )
        )
        frames.append(
            VisionInputKeyframe(
                keyframe_id=f"key_{index}",
                shot_id=shot_id,
                timestamp_ms=index * 1000 + 500,
                path=str(frame),
                sha256=f"{index + 1}" * 64,
            )
        )
    return MediaVisionBundle(
        video_id="vid_local",
        media_hash="a" * 64,
        shots=shots,
        keyframes=frames,
    )


def test_ollama_vision_maps_local_frames_to_strict_evidence(tmp_path: Path) -> None:
    content = {
        "frames": [
            {
                "frame_index": 0,
                "summary": "酒店大堂正面构图",
                "labels": ["酒店大堂", "前台"],
                "dominant_colors": ["暖金色"],
                "composition": ["居中构图"],
                "camera": ["主色", "平视"],
                "lighting": ["暖光"],
                "text_overlay_styles": ["金色标题字"],
                "motion_graphics": ["无可确认动效"],
                "branding": ["前台墙面标识"],
                "ocr": [
                    {
                        "text": "欢迎入住",
                        "confidence": 0.92,
                        "bounding_box": [100, 200, 800, 400],
                    }
                ],
                "confidence": 0.9,
            },
            {
                "frame_index": 1,
                "summary": "客房全景",
                "labels": ["客房", "床"],
                "dominant_colors": ["米白"],
                "composition": ["广角全景"],
                "camera": ["平视"],
                "lighting": ["自然光"],
                "text_overlay_styles": [],
                "motion_graphics": [],
                "branding": [],
                "ocr": [],
                "confidence": 0.88,
            },
        ],
        "unknowns": ["video_motion_not_observable_from_still_frames"],
    }
    executor = RecordingExecutor({"message": {"content": json.dumps(content)}})
    provider = OllamaVisionProvider(batch_size=2, executor=executor)

    result = provider.analyze(_bundle(tmp_path))

    assert executor.calls[0]["url"] == "http://127.0.0.1:11434/api/chat"
    assert executor.calls[0]["payload"]["model"] == "qwen3-vl:8b"
    assert len(executor.calls[0]["payload"]["messages"][0]["images"]) == 2
    assert executor.calls[0]["payload"]["format"]["title"] == "_OllamaVisionResponse"
    assert [item.shot_id for item in result.shot_annotations] == ["shot_0", "shot_1"]
    assert result.shot_annotations[0].text_overlay_styles == ["金色标题字"]
    assert result.shot_annotations[0].camera == ["平视"]
    assert result.shot_annotations[0].branding == ["前台墙面标识"]
    assert result.ocr_observations[0].keyframe_id == "key_0"
    assert result.ocr_observations[0].text == "欢迎入住"
    assert result.ocr_observations[0].bounding_box == [0.1, 0.2, 0.8, 0.4]
    assert result.unknowns == ["video_motion_not_observable_from_still_frames"]


def test_ollama_vision_maps_craft_labels_to_shot_annotations(tmp_path: Path) -> None:
    content = {
        "frames": [
            {
                "frame_index": 0,
                "summary": "酒店大堂",
                "labels": ["酒店大堂"],
                "dominant_colors": [],
                "shot_scale": ["特写", "景别"],
                "camera_movement": ["手持", "运镜"],
                "composition": ["居中构图"],
                "camera": ["平视"],
                "lighting": ["暖光"],
                "text_overlay_styles": ["金色标题字"],
                "motion_graphics": [],
                "branding": [],
                "ocr": [],
                "confidence": 0.9,
            },
            {
                "frame_index": 1,
                "summary": "客房全景",
                "labels": ["客房"],
                "dominant_colors": [],
                "shot_scale": ["全景"],
                "camera_movement": ["固定机位"],
                "composition": ["对称构图"],
                "camera": ["仰视"],
                "lighting": ["自然光"],
                "text_overlay_styles": [],
                "motion_graphics": [],
                "branding": [],
                "ocr": [],
                "confidence": 0.88,
            },
        ],
        "unknowns": [],
    }
    executor = RecordingExecutor({"message": {"content": json.dumps(content)}})
    result = OllamaVisionProvider(batch_size=2, executor=executor).analyze(_bundle(tmp_path))

    first, second = result.shot_annotations
    # Field-name echoes are filtered; real labels survive.
    assert first.shot_scale == ["特写"]
    assert first.camera_movement == ["手持"]
    assert first.camera == ["平视"]
    assert first.camera_angle == ["平视"]
    assert second.shot_scale == ["全景"]
    assert second.camera_movement == ["固定机位"]
    assert second.camera_angle == ["仰视"]
    prompt = executor.calls[0]["payload"]["messages"][0]["content"]
    assert "shot_scale" in prompt
    assert "camera_movement" in prompt
    assert "景别" in prompt


def test_vision_transport_classifies_connection_failure_as_unavailable(
    monkeypatch: Any,
) -> None:
    def refuse_connection(*_args: Any, **_kwargs: Any) -> None:
        raise URLError("connection refused")

    monkeypatch.setattr(
        "video_account_distiller.media.providers.urlopen",
        refuse_connection,
    )

    with pytest.raises(VisionProviderUnavailable, match="model service is unavailable"):
        UrllibVisionHttpExecutor().request_json(
            url="http://127.0.0.1:8081/v1/models",
            method="GET",
            payload=None,
            timeout_seconds=1,
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://127.0.0.1:11435",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
    ],
)
def test_ollama_vision_rejects_non_loopback_or_credentialed_urls(base_url: str) -> None:
    with pytest.raises(DistillerError) as caught:
        OllamaVisionProvider(base_url=base_url)
    assert caught.value.code == ErrorCode.SCHEMA_INVALID


def test_ollama_vision_rejects_invalid_frame_mapping(tmp_path: Path) -> None:
    content = {
        "frames": [
            {
                "frame_index": 2,
                "summary": "out of range",
                "labels": [],
                "dominant_colors": [],
                "composition": [],
                "camera": [],
                "lighting": [],
                "text_overlay_styles": [],
                "motion_graphics": [],
                "branding": [],
                "ocr": [],
            }
        ]
    }
    executor = RecordingExecutor({"message": {"content": json.dumps(content)}})
    with pytest.raises(VisionSchemaFailure):
        OllamaVisionProvider(batch_size=2, executor=executor).analyze(_bundle(tmp_path))


def test_ollama_vision_accepts_qwen_structured_output_in_thinking(tmp_path: Path) -> None:
    content = {
        "frames": [
            {
                "frame_index": 0,
                "summary": "酒店走廊",
                "labels": ["走廊"],
            },
            {
                "frame_index": 1,
                "summary": "客房",
                "labels": ["客房"],
            },
        ]
    }
    executor = RecordingExecutor({"message": {"content": "", "thinking": json.dumps(content)}})
    result = OllamaVisionProvider(batch_size=2, executor=executor).analyze(_bundle(tmp_path))
    assert [item.summary for item in result.shot_annotations] == ["酒店走廊", "客房"]


def test_llamacpp_vision_forces_json_and_accepts_markdown_fence(tmp_path: Path) -> None:
    content = {
        "frames": [
            {"frame_index": 0, "summary": "酒店画面", "labels": ["酒店设施"]},
        ]
    }
    wrapped = f"```json\n{json.dumps(content, ensure_ascii=False)}\n```"
    executor = RecordingExecutor({"choices": [{"message": {"content": wrapped}}]})

    result = LlamaCppVisionProvider(batch_size=2, executor=executor).analyze(_bundle(tmp_path))

    payload = executor.calls[0]["payload"]
    assert len(executor.calls) == 2
    assert payload["response_format"]["type"] == "json_object"
    schema = payload["response_format"]["schema"]
    assert schema["properties"]["frames"]["minItems"] == 1
    assert schema["properties"]["frames"]["maxItems"] == 1
    assert schema["required"] == ["frames", "unknowns"]
    assert schema["$defs"]["_OllamaFrameResult"]["properties"]["frame_index"]["const"] == 0
    assert "confidence" in schema["$defs"]["_OllamaFrameResult"]["required"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["max_tokens"] == 4096
    frame_schema = schema["$defs"]["_OllamaFrameResult"]
    assert frame_schema["properties"]["labels"]["maxItems"] == 12
    assert frame_schema["properties"]["labels"]["items"]["maxLength"] == 80
    assert frame_schema["properties"]["ocr"]["maxItems"] == 12
    assert schema["properties"]["unknowns"]["maxItems"] == 12
    assert [item.summary for item in result.shot_annotations] == ["酒店画面", "酒店画面"]


def test_llamacpp_vision_corrects_invalid_json_at_model_layer(tmp_path: Path) -> None:
    corrected = {
        "frames": [
            {"frame_index": 0, "summary": "酒店前台", "labels": ["前台"]},
        ]
    }
    executor = SequencedExecutor(
        [
            {"choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}]},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(corrected, ensure_ascii=False)},
                    }
                ]
            },
            {"choices": [{"message": {"content": json.dumps(corrected)}}]},
        ]
    )

    result = LlamaCppVisionProvider(executor=executor).analyze(_bundle(tmp_path))

    assert len(executor.calls) == 3
    retry_messages = executor.calls[1]["payload"]["messages"]
    assert [message["role"] for message in retry_messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert "严格 JSON Schema 校验" in retry_messages[-1]["content"]
    assert [item.summary for item in result.shot_annotations] == ["酒店前台", "酒店前台"]


def test_llamacpp_vision_restarts_cleanly_after_length_truncation(tmp_path: Path) -> None:
    corrected = {
        "frames": [
            {"frame_index": 0, "summary": "酒店客房", "labels": ["床", "窗帘"]},
        ]
    }
    executor = SequencedExecutor(
        [
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"frames":[{"frame_index":0,"summary":"'},
                    }
                ]
            },
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(corrected, ensure_ascii=False)},
                    }
                ]
            },
            {"choices": [{"message": {"content": json.dumps(corrected)}}]},
        ]
    )

    result = LlamaCppVisionProvider(executor=executor).analyze(_bundle(tmp_path))

    retry_payload = executor.calls[1]["payload"]
    assert [message["role"] for message in retry_payload["messages"]] == ["user"]
    retry_content = retry_payload["messages"][0]["content"]
    assert retry_content[0]["type"] == "text"
    assert "因长度上限被截断" in retry_content[0]["text"]
    assert len([item for item in retry_content if item["type"] == "image_url"]) == 1
    assert retry_payload["max_tokens"] == 4096
    assert [item.summary for item in result.shot_annotations] == ["酒店客房", "酒店客房"]


def test_ollama_model_availability_uses_only_local_registry() -> None:
    executor = RecordingExecutor({"models": [{"name": "qwen3-vl:8b"}, {"name": "other:latest"}]})
    assert ollama_model_available(
        base_url="http://localhost:11434",
        model="qwen3-vl:8b",
        executor=executor,
    )
    assert executor.calls == [
        {
            "url": "http://localhost:11434/api/tags",
            "method": "GET",
            "payload": None,
            "timeout_seconds": 5,
        }
    ]
