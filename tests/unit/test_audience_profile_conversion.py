from __future__ import annotations

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.ingestion import convert_audience_profile_records
from video_account_distiller.models import Platform


def test_long_audience_profile_rows_pass_through_with_source_row() -> None:
    record = {
        "account_id": "creator",
        "snapshot_at": "2026-07-29T08:00:00Z",
        "dimension": "gender",
        "bucket": "female",
        "share": "62%",
        "source_schema_version": "douyin-creator-profile/2026-07",
    }

    converted = convert_audience_profile_records(
        [record],
        platform=Platform.DOUYIN,
        first_row_number=2,
    )

    assert len(converted) == 1
    assert converted[0].source_row_number == 2
    assert converted[0].values == record
    assert converted[0].values is not record


def test_douyin_wide_audience_profile_expands_and_normalizes_units() -> None:
    converted = convert_audience_profile_records(
        [
            {
                "account_id": "creator",
                "snapshot_at": "2026-07-29T08:00:00Z",
                "导出版本": "douyin-creator-profile/2026-07",
                "女性粉丝占比": "62%",
                "男性粉丝占比": 38,
                "18-23岁粉丝占比": 0.25,
                "样本数": 100,
            }
        ],
        platform=Platform.DOUYIN,
        first_row_number=2,
    )

    assert [item.source_row_number for item in converted] == [2, 2, 2]
    assert [
        (item.values["dimension"], item.values["bucket"], item.values["share"])
        for item in converted
    ] == [
        ("gender", "female", 0.62),
        ("gender", "male", 0.38),
        ("age", "18-23", 0.25),
    ]
    assert all(
        item.values["source_schema_version"] == "douyin-creator-profile/2026-07"
        for item in converted
    )


def test_wide_audience_profile_rejects_unsupported_version() -> None:
    with pytest.raises(DistillerError) as captured:
        convert_audience_profile_records(
            [
                {
                    "account_id": "creator",
                    "snapshot_at": "2026-07-29T08:00:00Z",
                    "导出版本": "douyin-creator-profile-v0",
                    "女性粉丝占比": "62%",
                }
            ],
            platform=Platform.DOUYIN,
        )

    assert captured.value.code == ErrorCode.SCHEMA_INVALID
    assert captured.value.details["source_schema_version"] == "douyin-creator-profile-v0"
