from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.media.pipeline import (
    _audio_features,
    _generate_vision,
    _jpeg_dimensions,
    _keyframe_points,
    _selected_shot_indexes,
)
from video_account_distiller.media.providers import (
    StructuredVisionFileProvider,
    VisionProviderUnavailable,
    VisionSchemaFailure,
)
from video_account_distiller.models import (
    MediaVisionAnnotation,
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


def test_keyframe_points_cover_opening_ending_and_full_timeline() -> None:
    shots = [
        ShotSegment(shot_id="shot_0", index=0, start_ms=0, end_ms=1_000, duration_ms=1_000),
        ShotSegment(shot_id="shot_1", index=1, start_ms=1_000, end_ms=9_000, duration_ms=8_000),
        ShotSegment(shot_id="shot_2", index=2, start_ms=9_000, end_ms=60_000, duration_ms=51_000),
    ]

    points = _keyframe_points(shots, duration_ms=60_000, maximum=8)
    timestamps = [timestamp_ms for _, timestamp_ms in points]

    assert len(points) == 8
    assert timestamps[0] == 250
    assert timestamps[-1] == 59_749
    assert any(15_000 <= value <= 25_000 for value in timestamps)
    assert any(35_000 <= value <= 45_000 for value in timestamps)


def test_short_single_shot_gets_more_than_one_visual_sample() -> None:
    shots = [ShotSegment(shot_id="shot_0", index=0, start_ms=0, end_ms=8_000, duration_ms=8_000)]

    points = _keyframe_points(shots, duration_ms=8_000, maximum=12)

    assert len(points) == 4
    assert points[0][1] == 250
    assert points[-1][1] == 7_749


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


def test_strict_vision_reports_unavailable_service_instead_of_schema_error(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    bundle = MediaVisionBundle(
        video_id="vid_unavailable",
        media_hash="a" * 64,
        shots=[VisionInputShot(shot_id="shot_1", start_ms=0, end_ms=1000)],
        keyframes=[
            VisionInputKeyframe(
                keyframe_id="key_1",
                shot_id="shot_1",
                timestamp_ms=500,
                path=str(frame),
                sha256="b" * 64,
            )
        ],
    )

    class UnavailableProvider:
        provider_name = "llamacpp"
        model_name = "qwen3-vl-8b"
        input_hash = None

        def analyze(self, _bundle: MediaVisionBundle) -> MediaVisionAnnotation:
            raise VisionProviderUnavailable("model service is unavailable: URLError")

    with pytest.raises(DistillerError) as caught:
        _generate_vision(
            bundle=bundle,
            provider=UnavailableProvider(),
            max_attempts=2,
            strict=True,
        )

    assert caught.value.code == ErrorCode.MODEL_UNAVAILABLE
    assert caught.value.details == {
        "provider": "llamacpp",
        "model": "qwen3-vl-8b",
        "attempts": 2,
        "errors": [
            "model service is unavailable: URLError",
            "model service is unavailable: URLError",
        ],
    }
