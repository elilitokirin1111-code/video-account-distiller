from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.media.providers import (
    OllamaVisionProvider,
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
