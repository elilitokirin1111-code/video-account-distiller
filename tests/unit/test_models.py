from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from video_account_distiller.models import Account, MetricSnapshot, Platform


def trace(record_id: str) -> dict[str, object]:
    return {
        "record_id": record_id,
        "source_platform": Platform.DOUYIN,
        "source_type": "test",
        "source_uri": None,
        "source_record_id": "source",
        "collected_at": datetime.now(UTC),
        "run_id": "run_test",
        "raw_hash": "0" * 64,
    }


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Account.model_validate(
            {
                **trace("acc_test"),
                "account_id": "acc_test",
                "platform": Platform.DOUYIN,
                "platform_account_id": "source",
                "snapshot_at": datetime.now(UTC),
                "silently_dropped": "not allowed",
            }
        )


def test_negative_metrics_are_invalid() -> None:
    with pytest.raises(ValidationError):
        MetricSnapshot.model_validate(
            {
                **trace("ms_test"),
                "metric_snapshot_id": "ms_test",
                "video_id": "vid_test",
                "snapshot_at": datetime.now(UTC),
                "views": -1,
            }
        )


def test_unknown_metrics_remain_none() -> None:
    snapshot = MetricSnapshot.model_validate(
        {
            **trace("ms_test"),
            "metric_snapshot_id": "ms_test",
            "video_id": "vid_test",
            "snapshot_at": datetime.now(UTC),
        }
    )
    assert snapshot.views is None
    assert snapshot.shares is None
    assert snapshot.saves is None
