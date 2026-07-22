"""Timezone-aware timestamp parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from video_account_distiller.errors import DistillerError, ErrorCode


def parse_datetime(value: object, timezone: str = "UTC") -> datetime | None:
    """Parse common ISO timestamps and attach the configured zone when naive."""

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Invalid datetime: {value}",
                details={"value": str(value)},
            ) from exc
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        except ZoneInfoNotFoundError as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Unknown timezone: {timezone}",
            ) from exc
    return parsed.astimezone(UTC)
