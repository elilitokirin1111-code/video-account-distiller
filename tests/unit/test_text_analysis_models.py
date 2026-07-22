from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_account_distiller.models import (
    BlindVideoBundle,
    HookType,
    TranscriptInputSegment,
    VideoSemanticAnnotation,
)


def test_blind_bundle_schema_has_no_performance_fields() -> None:
    bundle = BlindVideoBundle(
        video_id="vid_test",
        platform="douyin",
        transcript_segments=[TranscriptInputSegment(segment_id="ts_1", text="开头")],
    )
    payload = bundle.model_dump(mode="json")
    assert not {
        "views",
        "likes",
        "performance_score",
        "performance_band",
    }.intersection(payload)


def test_semantic_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        VideoSemanticAnnotation.model_validate(
            {
                "primary_pillar": "hotel",
                "content_goal": "education",
                "funnel_stage": "interest",
                "hook": {"primary_type": HookType.UNKNOWN},
                "structure_segments": [],
                "narrative_type": "unknown",
                "information_density": "unknown",
                "cta": {"primary_type": "none"},
                "confidence": 0.1,
                "views": 100,
            }
        )
