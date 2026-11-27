from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from video_account_distiller.adapters.mapping import MappingResolver
from video_account_distiller.models import AudienceProfileSegment, Platform
from video_account_distiller.version import AUDIENCE_PROFILE_SCHEMA_VERSION


def _segment(**overrides: object) -> AudienceProfileSegment:
    payload: dict[str, object] = {
        "record_id": "aps_test",
        "source_platform": Platform.DOUYIN,
        "source_type": "audience_profile_segment",
        "source_record_id": "aps_test",
        "collected_at": datetime(2026, 7, 29, tzinfo=UTC),
        "run_id": "run_test",
        "raw_hash": "0" * 64,
        "profile_segment_id": "aps_test",
        "account_id": "acc_test",
        "snapshot_at": datetime(2026, 7, 29, tzinfo=UTC),
        "dimension": "gender",
        "bucket": "female",
        "share": 0.62,
        "sample_size": 100,
        "source_schema_version": "douyin-creator-profile/2026-07",
    }
    payload.update(overrides)
    return AudienceProfileSegment.model_validate(payload)


def test_audience_profile_contract_is_versioned_and_nullable() -> None:
    segment = _segment()

    assert segment.schema_version == AUDIENCE_PROFILE_SCHEMA_VERSION
    assert segment.share == 0.62
    assert segment.audience_count is None

    with pytest.raises(ValidationError):
        _segment(share=1.01)
    with pytest.raises(ValidationError):
        _segment(share=None, audience_count=None)
    with pytest.raises(ValidationError):
        _segment(share=None, audience_count=101, sample_size=100)


def test_douyin_creator_metric_mapping_covers_private_fields() -> None:
    resolver = MappingResolver()
    resolved = resolver.resolve(
        entity="metrics",
        platform=Platform.DOUYIN,
        available_fields={
            "video_id",
            "snapshot_at",
            "展现量",
            "平均播放时长",
            "完播率",
            "主页访问量",
            "新增粉丝",
            "点击量",
            "线索数",
            "成交订单数",
            "成交金额",
        },
    )

    assert resolved.mapping_version == "2"
    assert resolved.fields["impressions"] == "展现量"
    assert resolved.fields["avg_watch_time_seconds"] == "平均播放时长"
    assert resolved.fields["completion_rate"] == "完播率"
    assert resolved.fields["profile_visits"] == "主页访问量"
    assert resolved.fields["follows_gained"] == "新增粉丝"
    assert resolved.fields["clicks"] == "点击量"
    assert resolved.fields["leads"] == "线索数"
    assert resolved.fields["orders"] == "成交订单数"
    assert resolved.fields["revenue"] == "成交金额"
