from __future__ import annotations

from datetime import UTC

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.utils.hashing import hash_text, sha256_json
from video_account_distiller.utils.ids import new_run_id, stable_id
from video_account_distiller.utils.time import parse_datetime


def test_stable_ids_and_hashes() -> None:
    assert stable_id("acc_", "douyin", "1") == stable_id("acc_", "douyin", "1")
    assert stable_id("acc_", "douyin", "1") != stable_id("acc_", "douyin", "2")
    assert new_run_id().startswith("run_")
    assert len(hash_text("private")) == 64
    assert sha256_json({"b": 2, "a": 1}) == sha256_json({"a": 1, "b": 2})


def test_datetime_parsing_is_timezone_aware() -> None:
    offset = parse_datetime("2026-07-20T10:00:00+08:00")
    naive = parse_datetime("2026-07-20 10:00:00", "Asia/Shanghai")
    assert offset is not None and offset.tzinfo == UTC
    assert naive == offset
    assert parse_datetime("") is None


def test_invalid_datetime_has_stable_error() -> None:
    with pytest.raises(DistillerError) as captured:
        parse_datetime("not-a-time")
    assert captured.value.code == ErrorCode.SCHEMA_INVALID
