from __future__ import annotations

import math

import pytest

from video_account_distiller.metrics.calculations import (
    mad,
    median,
    percentile,
    performance_band,
    robust_z_scores,
    safe_divide,
)


def test_safe_divide_preserves_null_and_zero_distinction() -> None:
    assert safe_divide(None, 10) is None
    assert safe_divide(1, None) is None
    assert safe_divide(1, 0) is None
    assert safe_divide(0, 10) == 0.0
    assert safe_divide(5, 10) == 0.5


def test_median_mad_and_percentile() -> None:
    values = [1.0, 2.0, 3.0, 100.0]
    assert median(values) == 2.5
    assert mad(values) == 1.0
    assert percentile(values, 0) == 1.0
    assert percentile(values, 1) == 100.0
    assert percentile([4.0], 0.95) == 4.0
    with pytest.raises(ValueError):
        percentile(values, 2)


def test_robust_z_score_uses_log1p_and_keeps_null() -> None:
    result = robust_z_scores([0.0, 10.0, 100.0, None])
    assert result[-1] is None
    assert result[0] is not None and result[0] < 0
    assert result[2] is not None and result[2] > 0
    assert math.isfinite(result[1] or 0)


def test_zero_mad_degrades_to_no_relative_difference() -> None:
    assert robust_z_scores([5.0, 5.0, None], log_transform=False) == [0.0, 0.0, None]
    assert robust_z_scores([None, None]) == [None, None]


def test_performance_bands() -> None:
    scores = [float(value) for value in range(100)]
    assert performance_band(99, scores) == "S"
    assert performance_band(85, scores) == "A"
    assert performance_band(50, scores) == "B"
    assert performance_band(25, scores) == "C"
    assert performance_band(0, scores) == "D"
    assert performance_band(None, scores) is None
