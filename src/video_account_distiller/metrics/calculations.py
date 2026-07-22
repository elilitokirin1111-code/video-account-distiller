"""Null-safe statistical formulas from the analysis contract."""

from __future__ import annotations

import math
import statistics
from typing import Literal

MAD_SCALE = 1.4826


def safe_divide(numerator: int | float | None, denominator: int | float | None) -> float | None:
    """Divide known values; return None for missing or zero denominators."""

    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator) / float(denominator)


def median(values: list[float]) -> float | None:
    """Return the median or None for an empty population."""

    return float(statistics.median(values)) if values else None


def mad(values: list[float]) -> float | None:
    """Return the unscaled median absolute deviation."""

    center = median(values)
    if center is None:
        return None
    return median([abs(value - center) for value in values])


def percentile(values: list[float], quantile: float) -> float | None:
    """Return a linearly interpolated percentile for quantile in [0, 1]."""

    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def robust_z_scores(
    values: list[float | None],
    *,
    log_transform: bool = True,
) -> list[float | None]:
    """Calculate account-local Robust Z-scores while preserving missing values."""

    transformed = [
        math.log1p(value) if value is not None and log_transform else value for value in values
    ]
    known = [float(value) for value in transformed if value is not None]
    center = median(known)
    deviation = mad(known)
    if center is None:
        return [None for _ in values]
    if deviation is None or deviation == 0:
        return [0.0 if value is not None else None for value in transformed]
    scale = MAD_SCALE * deviation
    return [None if value is None else (float(value) - center) / scale for value in transformed]


PerformanceBand = Literal["S", "A", "B", "C", "D"]


def performance_band(score: float | None, scores: list[float]) -> PerformanceBand | None:
    """Assign S/A/B/C/D using account-local score percentiles."""

    if score is None or not scores:
        return None
    p95 = percentile(scores, 0.95)
    p80 = percentile(scores, 0.80)
    p40 = percentile(scores, 0.40)
    p20 = percentile(scores, 0.20)
    assert p95 is not None and p80 is not None and p40 is not None and p20 is not None
    if score >= p95:
        return "S"
    if score >= p80:
        return "A"
    if score >= p40:
        return "B"
    if score >= p20:
        return "C"
    return "D"
