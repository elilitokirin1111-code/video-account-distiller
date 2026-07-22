from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_account_distiller.media.pipeline import (
    _audio_features,
    _jpeg_dimensions,
    _selected_shot_indexes,
)
from video_account_distiller.media.providers import (
    StructuredVisionFileProvider,
    VisionSchemaFailure,
)
from video_account_distiller.models import (
    MediaVisionBundle,
    OcrObservation,
    ShotSegment,
    VisionInputKeyframe,
    VisionInputShot,
)


def test_shot_contract_rejects_inconsistent_duration() -> None:
    with pytest.raises(ValidationError):
        ShotSegment(
            shot_id="shot_1",
            index=0,
            start_ms=100,
            end_ms=500,
            duration_ms=500,
        )

    with pytest.raises(ValidationError):
        OcrObservation(
            observation_id="ocr_1",
            text="room 1208",
            shot_id="shot_1",
            keyframe_id="key_1",
            start_ms=500,
            end_ms=100,
        )


def test_keyframe_selection_is_bounded_and_deterministic() -> None:
    assert _selected_shot_indexes(3, 5) == [0, 1, 2]
    assert _selected_shot_indexes(10, 3) == [0, 4, 9]
    assert _selected_shot_indexes(10, 1) == [0]


def test_jpeg_dimensions_are_read_without_an_image_dependency(tmp_path: Path) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x02\x00\x03" + b"\x00" * 12)
    assert _jpeg_dimensions(frame) == (3, 2)


def test_audio_features_preserve_silence_as_a_measured_ratio() -> None:
    silent = b"\x00\x00" * 800
    active = (1200).to_bytes(2, "little", signed=True) * 800
    features = _audio_features(
        silent + active,
        sample_rate=8000,
        window_ms=100,
        silence_threshold_dbfs=-40,
    )
    assert features.status == "complete"
    assert features.has_audio is True
    assert features.analyzed_duration_ms == 200
    assert features.silence_ratio == 0.5
    assert features.activity_ratio == 0.5
    assert [(item.start_ms, item.end_ms) for item in features.silence_intervals] == [(0, 100)]


def test_structured_vision_provider_retries_schema_candidates(tmp_path: Path) -> None:
    output = tmp_path / "vision.json"
    output.write_text(
        json.dumps(
            {
                "model_name": "fixture-vision",
                "media_vision": [
                    {"unknown": "field"},
                    {
                        "shot_annotations": [
                            {
                                "annotation_id": "ann_1",
                                "shot_id": "shot_1",
                                "summary": "酒店大堂",
                            }
                        ],
                        "ocr_observations": [],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bundle = MediaVisionBundle(
        video_id="vid_1",
        media_hash="a" * 64,
        shots=[VisionInputShot(shot_id="shot_1", start_ms=0, end_ms=1000)],
        keyframes=[
            VisionInputKeyframe(
                keyframe_id="key_1",
                shot_id="shot_1",
                timestamp_ms=500,
                path="frame.jpg",
                sha256="b" * 64,
            )
        ],
    )
    provider = StructuredVisionFileProvider(output)
    with pytest.raises(VisionSchemaFailure):
        provider.analyze(bundle)
    assert provider.analyze(bundle).shot_annotations[0].summary == "酒店大堂"
