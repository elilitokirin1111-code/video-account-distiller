"""Calculate observed account changes from normalized point-in-time snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from video_account_distiller.models import AccountSnapshot
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout

GROWTH_FIELDS = ("followers", "following", "total_likes", "video_count", "profile_views")


def _period_days(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / 86_400, 0.0)


def _change(
    start: AccountSnapshot,
    end: AccountSnapshot,
    *,
    period_days: float,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name in GROWTH_FIELDS:
        start_value = getattr(start, name)
        end_value = getattr(end, name)
        delta = None
        per_day = None
        if start_value is not None and end_value is not None:
            delta = end_value - start_value
            if period_days > 0:
                per_day = delta / period_days
        fields[name] = {
            "start": start_value,
            "end": end_value,
            "delta": delta,
            "per_day": per_day,
        }
    return fields


class AccountGrowthService:
    """Read-only growth aggregation; it never fills missing observations with zero."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def summarize(self, *, account_id: str) -> dict[str, Any]:
        snapshots = [
            item
            for item in read_models(
                self.project.normalized_dir / "account_snapshots.parquet",
                AccountSnapshot,
            )
            if item.account_id == account_id
        ]
        deduplicated = {(item.snapshot_at, item.account_snapshot_id): item for item in snapshots}
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (item.snapshot_at, item.account_snapshot_id),
        )
        if not ordered:
            return {
                "ok": True,
                "account_id": account_id,
                "status": "no_snapshots",
                "snapshot_count": 0,
                "period_days": 0.0,
                "first_snapshot": None,
                "latest_snapshot": None,
                "changes": None,
                "intervals": [],
                "warnings": ["repeat_collection_or_import_is_required_for_growth"],
            }

        first = ordered[0]
        latest = ordered[-1]
        period_days = _period_days(first.snapshot_at, latest.snapshot_at)
        intervals = []
        for start, end in zip(ordered, ordered[1:], strict=False):
            interval_days = _period_days(start.snapshot_at, end.snapshot_at)
            intervals.append(
                {
                    "start_snapshot_id": start.account_snapshot_id,
                    "end_snapshot_id": end.account_snapshot_id,
                    "start_at": start.snapshot_at.isoformat(),
                    "end_at": end.snapshot_at.isoformat(),
                    "period_days": interval_days,
                    "changes": _change(start, end, period_days=interval_days),
                }
            )

        warnings: list[str] = []
        if len(ordered) < 2:
            warnings.append("at_least_two_snapshots_are_required_for_growth")
        if len({item.snapshot_at for item in ordered}) < len(ordered):
            warnings.append("multiple_snapshots_share_the_same_timestamp")
        missing_fields = [
            name
            for name in GROWTH_FIELDS
            if getattr(first, name) is None or getattr(latest, name) is None
        ]
        if missing_fields:
            warnings.append("growth_fields_unavailable:" + ",".join(missing_fields))
        return {
            "ok": True,
            "account_id": account_id,
            "status": "ready" if len(ordered) >= 2 and period_days > 0 else "insufficient_history",
            "snapshot_count": len(ordered),
            "period_days": period_days,
            "first_snapshot": first.model_dump(mode="json"),
            "latest_snapshot": latest.model_dump(mode="json"),
            "changes": _change(first, latest, period_days=period_days),
            "intervals": intervals,
            "warnings": warnings,
        }
