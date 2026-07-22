"""Null-safe descriptive statistics for Phase 2 reports."""

from __future__ import annotations

from datetime import datetime

from video_account_distiller.metrics.calculations import percentile
from video_account_distiller.models import NumericSummary


def summarize_numeric(
    values: list[float | None],
    *,
    evidence_id: str,
) -> NumericSummary:
    """Return a null-aware five-number summary."""

    known = sorted(float(value) for value in values if value is not None)
    return NumericSummary(
        count=len(known),
        missing_count=len(values) - len(known),
        minimum=known[0] if known else None,
        p25=percentile(known, 0.25),
        median=percentile(known, 0.50),
        p75=percentile(known, 0.75),
        maximum=known[-1] if known else None,
        evidence_id=evidence_id,
    )


def publication_gaps_days(published_at: list[datetime | None]) -> list[float | None]:
    """Return chronological publication gaps, preserving an unknown marker."""

    known = sorted(value for value in published_at if value is not None)
    gaps: list[float | None] = [
        (current - previous).total_seconds() / 86_400
        for previous, current in zip(known, known[1:], strict=False)
    ]
    if any(value is None for value in published_at):
        gaps.append(None)
    return gaps


def publication_frequency_weekly(published_at: list[datetime | None]) -> float | None:
    """Return posts per week for a non-zero observed date span."""

    known = sorted(value for value in published_at if value is not None)
    if len(known) < 2:
        return None
    span_days = (known[-1] - known[0]).total_seconds() / 86_400
    if span_days <= 0:
        return None
    return len(known) / (span_days / 7)


def longest_low_streak(bands_by_time: list[tuple[datetime | None, str]]) -> int:
    """Return the longest chronological C/D performance streak."""

    ordered = sorted(
        bands_by_time,
        key=lambda item: item[0].timestamp() if item[0] is not None else float("inf"),
    )
    longest = 0
    current = 0
    for _, band in ordered:
        if band in {"C", "D"}:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
