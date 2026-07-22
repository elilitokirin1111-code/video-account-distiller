from __future__ import annotations

from datetime import UTC, datetime, timedelta

from video_account_distiller.reports.statistics import (
    longest_low_streak,
    publication_frequency_weekly,
    publication_gaps_days,
    summarize_numeric,
)


def test_numeric_summary_preserves_missing_values() -> None:
    summary = summarize_numeric([1.0, None, 3.0, 5.0], evidence_id="evi_test")
    assert summary.count == 3
    assert summary.missing_count == 1
    assert summary.p25 == 2.0
    assert summary.median == 3.0
    assert summary.p75 == 4.0
    assert summary.evidence_id == "evi_test"


def test_publication_statistics_are_null_safe() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    dates = [start, start + timedelta(days=7), start + timedelta(days=14), None]
    assert publication_gaps_days(dates) == [7.0, 7.0, None]
    assert publication_frequency_weekly(dates) == 1.5
    assert publication_frequency_weekly([start]) is None
    assert publication_frequency_weekly([start, start]) is None


def test_longest_low_streak_uses_chronological_order() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bands = [
        (start + timedelta(days=3), "B"),
        (start, "C"),
        (start + timedelta(days=1), "D"),
        (start + timedelta(days=2), "C"),
        (None, "D"),
    ]
    assert longest_low_streak(bands) == 3
