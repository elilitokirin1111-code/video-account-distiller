"""Version-aware conversion of creator audience-profile exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import Platform


@dataclass(frozen=True)
class ConvertedAudienceRecord:
    """One normalized long-form record tied to its original source row."""

    source_row_number: int
    values: dict[str, Any]


@dataclass(frozen=True)
class _WideField:
    dimension: str
    bucket: str


_DIMENSION_FIELDS = ("dimension", "dimension_key", "画像维度")
_BUCKET_FIELDS = ("bucket", "segment", "label", "人群分组")
_SOURCE_VERSION_FIELDS = (
    "source_schema_version",
    "export_schema_version",
    "schema_version",
    "导出版本",
)
_SEGMENT_ID_FIELDS = ("profile_segment_id", "segment_id")

# These aliases describe the currently supported Douyin creator-center wide
# export family. Keep them explicit: unknown columns must not be guessed into
# a demographic bucket.
_DOUYIN_WIDE_FIELDS: dict[str, _WideField] = {
    "女性粉丝占比": _WideField("gender", "female"),
    "女粉丝占比": _WideField("gender", "female"),
    "男性粉丝占比": _WideField("gender", "male"),
    "男粉丝占比": _WideField("gender", "male"),
    "18岁以下粉丝占比": _WideField("age", "under_18"),
    "18-23岁粉丝占比": _WideField("age", "18-23"),
    "24-30岁粉丝占比": _WideField("age", "24-30"),
    "31-40岁粉丝占比": _WideField("age", "31-40"),
    "41-50岁粉丝占比": _WideField("age", "41-50"),
    "50岁以上粉丝占比": _WideField("age", "over_50"),
    "一线城市粉丝占比": _WideField("city_tier", "tier_1"),
    "新一线城市粉丝占比": _WideField("city_tier", "new_tier_1"),
    "二线城市粉丝占比": _WideField("city_tier", "tier_2"),
    "三线城市粉丝占比": _WideField("city_tier", "tier_3"),
    "四线城市粉丝占比": _WideField("city_tier", "tier_4"),
    "五线城市粉丝占比": _WideField("city_tier", "tier_5"),
}

_SUPPORTED_WIDE_VERSION_PREFIXES: dict[Platform, tuple[str, ...]] = {
    Platform.DOUYIN: (
        "douyin-creator-profile/",
        "douyin-creator-profile-wide/",
        "audience-profile-wide/1",
    ),
}


def _first_present(record: dict[str, Any], fields: tuple[str, ...]) -> Any | None:
    for field in fields:
        value = record.get(field)
        if value is not None and (not isinstance(value, str) or value.strip()):
            return value
    return None


def _is_long_form(record: dict[str, Any]) -> bool:
    return (
        _first_present(record, _DIMENSION_FIELDS) is not None
        and _first_present(record, _BUCKET_FIELDS) is not None
    )


def _normalize_share(value: Any, *, field: str, row_number: int) -> float:
    """Normalize a wide-table percentage without silently guessing its unit."""

    raw = value.strip().replace(",", "") if isinstance(value, str) else value
    is_percent = isinstance(raw, str) and raw.endswith("%")
    numeric_text = raw[:-1] if is_percent else raw
    try:
        numeric = float(numeric_text)
    except (TypeError, ValueError) as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Audience profile share is not numeric",
            details={"field": field, "row_number": row_number, "value": str(value)},
        ) from exc

    # All built-in wide aliases explicitly say 占比. Creator exports commonly
    # encode them either as 62%, 62, or 0.62, so the header supplies the unit
    # signal for values greater than one.
    if is_percent or numeric > 1:
        numeric /= 100
    if not 0 <= numeric <= 1:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Audience profile share must be between 0% and 100%",
            details={"field": field, "row_number": row_number, "value": str(value)},
        )
    return numeric


def _wide_fields(platform: Platform) -> dict[str, _WideField]:
    if platform == Platform.DOUYIN:
        return _DOUYIN_WIDE_FIELDS
    return {}


def _require_supported_wide_version(platform: Platform, version: str, row_number: int) -> None:
    prefixes = _SUPPORTED_WIDE_VERSION_PREFIXES.get(platform, ())
    if not any(version.startswith(prefix) for prefix in prefixes):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Unsupported wide audience-profile export version",
            details={
                "platform": platform.value,
                "source_schema_version": version,
                "row_number": row_number,
                "supported_prefixes": list(prefixes),
            },
        )


def convert_audience_profile_records(
    records: list[dict[str, Any]],
    *,
    platform: Platform,
    first_row_number: int = 1,
) -> list[ConvertedAudienceRecord]:
    """Convert supported long or wide exports into canonical long-form rows.

    Long-form rows pass through unchanged. A supported wide row expands into
    one record per observed demographic bucket while preserving its source row
    number for quality reporting.
    """

    converted: list[ConvertedAudienceRecord] = []
    wide_fields = _wide_fields(platform)
    for offset, record in enumerate(records):
        row_number = first_row_number + offset
        if _is_long_form(record):
            converted.append(ConvertedAudienceRecord(row_number, dict(record)))
            continue

        version_value = _first_present(record, _SOURCE_VERSION_FIELDS)
        if version_value is None:
            raise DistillerError(
                ErrorCode.FIELD_MAPPING_REQUIRED,
                "Wide audience-profile rows require a source schema version",
                details={"row_number": row_number, "available": sorted(record)},
            )
        version = str(version_value).strip()
        _require_supported_wide_version(platform, version, row_number)

        observed = [
            (field, spec, record.get(field))
            for field, spec in wide_fields.items()
            if record.get(field) is not None
            and (not isinstance(record.get(field), str) or str(record.get(field)).strip())
        ]
        if not observed:
            raise DistillerError(
                ErrorCode.FIELD_MAPPING_REQUIRED,
                "Supported audience-profile export contains no recognized profile columns",
                details={
                    "platform": platform.value,
                    "source_schema_version": version,
                    "row_number": row_number,
                    "available": sorted(record),
                    "recognized": sorted(wide_fields),
                },
            )

        metadata = {
            key: value
            for key, value in record.items()
            if key not in wide_fields and key not in _SEGMENT_ID_FIELDS
        }
        for field, spec, value in observed:
            converted.append(
                ConvertedAudienceRecord(
                    row_number,
                    {
                        **metadata,
                        "dimension": spec.dimension,
                        "bucket": spec.bucket,
                        "share": _normalize_share(value, field=field, row_number=row_number),
                        "source_schema_version": version,
                    },
                )
            )
    return converted
