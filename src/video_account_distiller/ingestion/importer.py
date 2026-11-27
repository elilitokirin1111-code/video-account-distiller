"""Offline import pipeline with hashing, validation, and idempotence."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from video_account_distiller.adapters.files import FileAdapter
from video_account_distiller.adapters.mapping import (
    MappingResolver,
    load_mapping_file,
)
from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.ingestion.audience_profiles import (
    ConvertedAudienceRecord,
    convert_audience_profile_records,
)
from video_account_distiller.models import (
    Account,
    AudienceProfileSegment,
    Comment,
    DataQualityFlag,
    DataQualityIssue,
    DataSourceTier,
    ImportReceipt,
    MetricSnapshot,
    Platform,
    Video,
)
from video_account_distiller.models.core import TraceFields
from video_account_distiller.quality import QualityReport, write_quality_report
from video_account_distiller.storage import ProjectLayout
from video_account_distiller.utils.hashing import hash_text, sha256_file
from video_account_distiller.utils.ids import new_run_id, stable_id
from video_account_distiller.utils.io import atomic_write_text
from video_account_distiller.utils.time import parse_datetime

EntityName = Literal["accounts", "videos", "metrics", "comments", "audience_profiles"]

INT_FIELDS = {
    "follower_count_current",
    "following_count_current",
    "total_likes_current",
    "video_count_current",
    "follower_count_at_publish",
    "views",
    "impressions",
    "likes",
    "comments",
    "shares",
    "saves",
    "favorites",
    "follows_gained",
    "profile_visits",
    "clicks",
    "leads",
    "orders",
    "like_count",
    "audience_count",
    "sample_size",
}
FLOAT_FIELDS = {
    "duration_seconds",
    "age_hours",
    "avg_watch_time_seconds",
    "completion_rate",
    "three_second_view_rate",
    "five_second_view_rate",
    "revenue",
    "promotion_spend",
    "share",
}
BOOL_FIELDS = {
    "verified",
    "is_ad",
    "is_pinned",
    "is_deleted",
    "is_repost",
    "is_promoted",
    "is_creator_reply",
}
LIST_FIELDS = {"hashtags", "mentions"}
DATETIME_FIELDS = {"created_at", "snapshot_at", "published_at"}
NULL_STRINGS = {"", "null", "none", "nan", "n/a", "na", "-"}


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.casefold() in NULL_STRINGS:
            return None
        return stripped
    return value


def _coerce_bool(value: Any) -> bool | None:
    value = _clean_scalar(value)
    if value is None or isinstance(value, bool):
        return value
    normalized = str(value).casefold()
    if normalized in {"1", "true", "yes", "y", "是"}:
        return True
    if normalized in {"0", "false", "no", "n", "否"}:
        return False
    raise ValueError(f"not a boolean: {value}")


def _coerce_list(value: Any) -> list[str]:
    value = _clean_scalar(value)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value)
    if text.startswith("["):
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    separator = "|" if "|" in text else ","
    return [item.strip() for item in text.split(separator) if item.strip()]


def _coerce_fields(mapped: dict[str, Any], timezone: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, raw_value in mapped.items():
        value = _clean_scalar(raw_value)
        if value is None:
            result[field] = None
        elif field in INT_FIELDS:
            result[field] = int(float(str(value).replace(",", "")))
        elif field in FLOAT_FIELDS:
            result[field] = float(str(value).replace("%", "")) / (
                100.0 if isinstance(value, str) and "%" in value else 1.0
            )
        elif field in BOOL_FIELDS:
            result[field] = _coerce_bool(value)
        elif field in LIST_FIELDS:
            result[field] = _coerce_list(value)
        elif field in DATETIME_FIELDS:
            result[field] = parse_datetime(value, timezone)
        else:
            result[field] = value
    return result


def _internal_account_id(platform: Platform, value: str) -> str:
    return value if value.startswith("acc_") else stable_id("acc_", platform.value, value)


def _internal_video_id(platform: Platform, value: str) -> str:
    return value if value.startswith("vid_") else stable_id("vid_", platform.value, value)


def _trace(
    *,
    record_id: str,
    platform: Platform,
    source_type: str,
    source_uri: str,
    source_record_id: str,
    collected_at: datetime | None,
    run_id: str,
    raw_hash: str,
    flags: list[DataQualityFlag],
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "source_platform": platform,
        "source_type": source_type,
        "source_uri": source_uri,
        "source_record_id": source_record_id,
        "collected_at": collected_at,
        "run_id": run_id,
        "raw_hash": raw_hash,
        "data_quality_flags": flags,
    }


def _build_account(
    values: dict[str, Any], platform: Platform, run_id: str, raw_hash: str, source_uri: str
) -> Account:
    platform_id = str(values["platform_account_id"])
    account_id = _internal_account_id(platform, str(values.get("account_id") or platform_id))
    snapshot_at = values.get("snapshot_at") or datetime.now(UTC)
    trace = _trace(
        record_id=account_id,
        platform=platform,
        source_type="account",
        source_uri=source_uri,
        source_record_id=platform_id,
        collected_at=snapshot_at,
        run_id=run_id,
        raw_hash=raw_hash,
        flags=[],
    )
    payload = {
        **values,
        "account_id": account_id,
        "platform": platform,
        "platform_account_id": platform_id,
        "snapshot_at": snapshot_at,
    }
    return Account(**trace, **payload)


def _build_video(
    values: dict[str, Any], platform: Platform, run_id: str, raw_hash: str, source_uri: str
) -> Video:
    platform_id = str(values["platform_video_id"])
    video_id = _internal_video_id(platform, str(values.get("video_id") or platform_id))
    account_id = _internal_account_id(platform, str(values["account_id"]))
    flags: list[DataQualityFlag] = []
    if values.get("published_at") is None:
        flags.append(DataQualityFlag.MISSING_PUBLISH_TIME)
    if values.get("follower_count_at_publish") is None:
        flags.append(DataQualityFlag.UNKNOWN_FOLLOWER_AT_PUBLISH)
    if values.get("is_repost"):
        flags.append(DataQualityFlag.SUSPECTED_REPOST)
    if values.get("is_deleted"):
        flags.append(DataQualityFlag.DELETED_CONTENT)
    trace = _trace(
        record_id=video_id,
        platform=platform,
        source_type="video",
        source_uri=source_uri,
        source_record_id=platform_id,
        collected_at=values.get("published_at"),
        run_id=run_id,
        raw_hash=raw_hash,
        flags=flags,
    )
    payload = {
        **values,
        "video_id": video_id,
        "account_id": account_id,
        "platform": platform,
        "platform_video_id": platform_id,
    }
    return Video(**trace, **payload)


def _build_metrics(
    values: dict[str, Any], platform: Platform, run_id: str, raw_hash: str, source_uri: str
) -> MetricSnapshot:
    video_id = _internal_video_id(platform, str(values["video_id"]))
    snapshot_at = cast(datetime, values["snapshot_at"])
    snapshot_id = str(
        values.get("metric_snapshot_id")
        or stable_id("ms_", platform.value, video_id, snapshot_at.isoformat())
    )
    flags: list[DataQualityFlag] = []
    if values.get("views") is None:
        flags.append(DataQualityFlag.MISSING_VIEWS)
    if values.get("is_promoted"):
        flags.append(DataQualityFlag.SUSPECTED_PAID_TRAFFIC)
    trace = _trace(
        record_id=snapshot_id,
        platform=platform,
        source_type="metric_snapshot",
        source_uri=source_uri,
        source_record_id=snapshot_id,
        collected_at=snapshot_at,
        run_id=run_id,
        raw_hash=raw_hash,
        flags=flags,
    )
    payload = {
        **values,
        "metric_snapshot_id": snapshot_id,
        "video_id": video_id,
        "snapshot_at": snapshot_at,
    }
    return MetricSnapshot(**trace, **payload)


def _build_comment(
    values: dict[str, Any], platform: Platform, run_id: str, raw_hash: str, source_uri: str
) -> Comment:
    platform_id = str(values["platform_comment_id"])
    comment_id = str(values.get("comment_id") or stable_id("cmt_", platform.value, platform_id))
    author_hash = values.get("author_hash")
    if author_hash is None and values.get("author_id") is not None:
        author_hash = hash_text(str(values["author_id"]))
    values = {key: value for key, value in values.items() if key != "author_id"}
    trace = _trace(
        record_id=comment_id,
        platform=platform,
        source_type="comment",
        source_uri=source_uri,
        source_record_id=platform_id,
        collected_at=values.get("created_at"),
        run_id=run_id,
        raw_hash=raw_hash,
        flags=[],
    )
    payload = {
        **values,
        "comment_id": comment_id,
        "platform_comment_id": platform_id,
        "video_id": _internal_video_id(platform, str(values["video_id"])),
        "author_hash": author_hash,
    }
    return Comment(**trace, **payload)


def _build_audience_profile(
    values: dict[str, Any], platform: Platform, run_id: str, raw_hash: str, source_uri: str
) -> AudienceProfileSegment:
    account_id = _internal_account_id(platform, str(values["account_id"]))
    snapshot_at = cast(datetime, values["snapshot_at"])
    dimension = str(values["dimension"])
    bucket = str(values["bucket"])
    segment_id = str(
        values.get("profile_segment_id")
        or stable_id(
            "aps_",
            platform.value,
            account_id,
            snapshot_at.isoformat(),
            dimension,
            bucket,
        )
    )
    trace = _trace(
        record_id=segment_id,
        platform=platform,
        source_type="audience_profile_segment",
        source_uri=source_uri,
        source_record_id=segment_id,
        collected_at=snapshot_at,
        run_id=run_id,
        raw_hash=raw_hash,
        flags=[],
    )
    payload = {
        **values,
        "profile_segment_id": segment_id,
        "account_id": account_id,
        "snapshot_at": snapshot_at,
        "dimension": dimension,
        "bucket": bucket,
    }
    return AudienceProfileSegment(**trace, **payload)


BUILDERS: dict[
    EntityName,
    Callable[[dict[str, Any], Platform, str, str, str], TraceFields],
] = {
    "accounts": _build_account,
    "videos": _build_video,
    "metrics": _build_metrics,
    "comments": _build_comment,
    "audience_profiles": _build_audience_profile,
}


class ImportService:
    """Import one offline file into immutable raw storage and validated staging."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project
        self.file_adapter = FileAdapter()
        self.mapping_resolver = MappingResolver()

    def import_file(
        self,
        *,
        entity: EntityName,
        source: Path,
        platform: Platform,
        mapping_path: Path | None = None,
        dry_run: bool = False,
        data_source_tier: DataSourceTier = DataSourceTier.PUBLIC,
        authorization_grant_id: str | None = None,
    ) -> tuple[ImportReceipt | None, QualityReport, bool]:
        """Import a file; return receipt, report, and whether it was already imported."""

        source = source.expanduser().resolve()
        self.file_adapter.validate_source(source)
        raw_hash = sha256_file(source)
        state = self.project.load_state()
        existing = next(
            (
                receipt
                for receipt in state.imports
                if receipt.entity == entity
                and receipt.platform == platform
                and receipt.raw_hash == raw_hash
            ),
            None,
        )
        if existing is not None:
            existing_tier = DataSourceTier(existing.data_source_tier)
            if existing_tier not in {DataSourceTier.UNKNOWN, data_source_tier}:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "Input hash was already imported with a different data source tier",
                    details={
                        "existing": existing_tier.value,
                        "requested": data_source_tier.value,
                    },
                )
            report = QualityReport(
                run_id=existing.run_id,
                entity=entity,
                input_hashes=[raw_hash],
                stats={
                    "input_rows": existing.input_rows,
                    "accepted_rows": existing.accepted_rows,
                    "rejected_rows": existing.rejected_rows,
                    "duplicate_rows": existing.duplicate_rows,
                },
                warnings=[
                    "Input hash already imported; no files were changed."
                    + (
                        " Existing provenance is unknown and was not rewritten."
                        if existing_tier == DataSourceTier.UNKNOWN
                        else ""
                    )
                ],
            )
            return existing, report, True

        records = self.file_adapter.load_records(source)
        first_row_number = 2 if source.suffix == ".csv" else 1
        import_records = (
            convert_audience_profile_records(
                records,
                platform=platform,
                first_row_number=first_row_number,
            )
            if entity == "audience_profiles"
            else [
                ConvertedAudienceRecord(first_row_number + offset, record)
                for offset, record in enumerate(records)
            ]
        )
        available_fields = {str(key) for converted in import_records for key in converted.values}
        explicit = load_mapping_file(mapping_path) if mapping_path else None
        config = load_config(self.project.config_path)
        mapping = self.mapping_resolver.resolve(
            entity=entity,
            platform=platform,
            available_fields=available_fields,
            explicit=explicit,
            timezone=config.project.timezone,
        )
        manifest = None
        run_id = new_run_id()
        if not dry_run:
            manifest = self.project.begin_run(
                f"import {entity}",
                input_hashes=[raw_hash],
            )
            run_id = manifest.run_id
        source_uri = f"raw/imports/{entity}/{raw_hash}{source.suffix.lower()}"
        accepted: list[TraceFields] = []
        issues: list[DataQualityIssue] = []
        seen: set[str] = set()
        duplicate_rows = 0

        for converted in import_records:
            row_number = converted.source_row_number
            raw_record = converted.values
            try:
                mapped = self.mapping_resolver.apply(raw_record, mapping)
                values = _coerce_fields(mapped, mapping.timezone)
                model = BUILDERS[entity](
                    values,
                    platform,
                    run_id,
                    raw_hash,
                    source_uri,
                )
                if model.record_id in seen:
                    duplicate_rows += 1
                    issues.append(
                        DataQualityIssue(
                            issue_id=stable_id("dqi_", run_id, entity, row_number, "duplicate"),
                            run_id=run_id,
                            severity="warning",
                            code="duplicate_record",
                            entity=entity,
                            message=f"Duplicate record in input: {model.record_id}",
                            row_number=row_number,
                            raw_hash=raw_hash,
                        )
                    )
                    continue
                seen.add(model.record_id)
                accepted.append(model)
            except (DistillerError, ValidationError, ValueError, TypeError) as exc:
                issues.append(
                    DataQualityIssue(
                        issue_id=stable_id("dqi_", run_id, entity, row_number, type(exc).__name__),
                        run_id=run_id,
                        severity="error",
                        code="schema_invalid",
                        entity=entity,
                        message=str(exc),
                        row_number=row_number,
                        raw_hash=raw_hash,
                    )
                )

        report = QualityReport(
            run_id=run_id,
            entity=entity,
            input_hashes=[raw_hash],
            stats={
                "input_rows": len(records),
                "expanded_rows": len(import_records),
                "accepted_rows": len(accepted),
                "rejected_rows": len(import_records) - len(accepted) - duplicate_rows,
                "duplicate_rows": duplicate_rows,
            },
            issues=issues,
        )
        if dry_run:
            report.warnings.append("Dry run: no project files or state were changed.")
            return None, report, False

        assert manifest is not None

        raw_path = self.project.root / source_uri
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomically preserve the raw source so the hash check is not racy.
        try:
            with open(raw_path, "xb") as dst:
                dst.write(source.read_bytes())
        except FileExistsError:
            pass
        if sha256_file(raw_path) != raw_hash:
            raise DistillerError(ErrorCode.RAW_INTEGRITY, f"Raw copy hash mismatch: {raw_path}")

        staging_path = self.project.root / "staging" / entity / f"{raw_hash}.jsonl"
        lines = "".join(
            json.dumps(model.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for model in accepted
        )
        atomic_write_text(staging_path, lines)
        run_dir = self.project.runs_dir / manifest.run_id
        report_json, report_markdown = write_quality_report(report, run_dir)
        receipt = ImportReceipt(
            entity=entity,
            platform=platform,
            source_name=source.name,
            data_source_tier=data_source_tier.value,
            authorization_grant_id=authorization_grant_id,
            raw_hash=raw_hash,
            raw_path=self.project.relative(raw_path),
            staging_path=self.project.relative(staging_path),
            run_id=manifest.run_id,
            input_rows=len(records),
            accepted_rows=len(accepted),
            rejected_rows=report.stats["rejected_rows"],
            duplicate_rows=duplicate_rows,
            quality_report_json=self.project.relative(report_json),
            quality_report_markdown=self.project.relative(report_markdown),
        )
        state.imports.append(receipt)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts=report.stats,
            output_files=[
                receipt.raw_path,
                cast(str, receipt.staging_path),
                receipt.quality_report_json,
                receipt.quality_report_markdown,
            ],
            warnings=[issue.message for issue in issues if issue.severity == "warning"],
            errors=[issue.message for issue in issues if issue.severity == "error"],
        )
        return receipt, report, False
