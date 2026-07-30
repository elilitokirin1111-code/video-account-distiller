"""Deterministic normalization and record-level deduplication."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from video_account_distiller.models import (
    Account,
    AccountSnapshot,
    AudienceProfileSegment,
    Comment,
    DataQualityIssue,
    MetricSnapshot,
    TranscriptSegment,
    Video,
)
from video_account_distiller.models.core import TraceFields
from video_account_distiller.quality import QualityReport, write_quality_report
from video_account_distiller.storage.parquet import write_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

MODEL_BY_ENTITY: dict[str, type[TraceFields]] = {
    "accounts": Account,
    "videos": Video,
    "metrics": MetricSnapshot,
    "comments": Comment,
    "transcripts": TranscriptSegment,
    "audience_profiles": AudienceProfileSegment,
}
OUTPUT_BY_ENTITY = {
    "accounts": "accounts.parquet",
    "videos": "videos.parquet",
    "metrics": "metric_snapshots.parquet",
    "comments": "comments.parquet",
    "transcripts": "transcripts.parquet",
    "audience_profiles": "audience_profiles.parquet",
}


def _deduplicate(records: list[TraceFields]) -> tuple[list[TraceFields], list[str]]:
    selected: dict[str, TraceFields] = {}
    conflicts: list[str] = []
    for record in records:
        record_id = record.record_id
        current = selected.get(record_id)
        if current is None:
            selected[record_id] = record
            continue
        current_payload = current.model_dump(mode="json", exclude={"run_id", "ingested_at"})
        next_payload = record.model_dump(mode="json", exclude={"run_id", "ingested_at"})
        if current_payload == next_payload:
            continue
        conflicts.append(record_id)
        current_key = (current.ingested_at, current.raw_hash)
        next_key = (record.ingested_at, record.raw_hash)
        if next_key > current_key:
            selected[record_id] = record
    return [selected[key] for key in sorted(selected)], sorted(set(conflicts))


def _account_snapshots(accounts: list[Account]) -> list[AccountSnapshot]:
    snapshots: list[AccountSnapshot] = []
    for account in accounts:
        snapshot_id = stable_id(
            "as_", account.account_id, account.snapshot_at.isoformat(), account.raw_hash
        )
        snapshots.append(
            AccountSnapshot(
                record_id=snapshot_id,
                source_platform=account.source_platform,
                source_type="account_snapshot",
                source_uri=account.source_uri,
                source_record_id=account.source_record_id,
                collected_at=account.snapshot_at,
                ingested_at=account.ingested_at,
                run_id=account.run_id,
                raw_hash=account.raw_hash,
                data_quality_flags=account.data_quality_flags,
                account_snapshot_id=snapshot_id,
                account_id=account.account_id,
                snapshot_at=account.snapshot_at,
                followers=account.follower_count_current,
                following=account.following_count_current,
                total_likes=account.total_likes_current,
                video_count=account.video_count_current,
                profile_views=None,
                source="account_export",
            )
        )
    return snapshots


class NormalizationService:
    """Rebuild all normalized tables solely from validated staging artifacts."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def normalize(self, *, dry_run: bool = False) -> dict[str, Any]:
        """Validate, deduplicate, and atomically write normalized Parquet tables."""

        all_records: dict[str, list[TraceFields]] = {}
        conflict_ids: dict[str, list[str]] = {}
        input_hashes = sorted({receipt.raw_hash for receipt in self.project.load_state().imports})
        manifest = (
            None if dry_run else self.project.begin_run("normalize", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest is not None else stable_id("run_dry_", *input_hashes)

        for entity, model_type in MODEL_BY_ENTITY.items():
            loaded: list[TraceFields] = []
            for path in sorted((self.project.root / "staging" / entity).glob("*.jsonl")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        loaded.append(model_type.model_validate_json(line))
            deduplicated, conflicts = _deduplicate(loaded)
            all_records[entity] = deduplicated
            conflict_ids[entity] = conflicts

        issues: list[DataQualityIssue] = []
        for entity, conflicts in conflict_ids.items():
            for record_id in conflicts:
                issues.append(
                    DataQualityIssue(
                        issue_id=stable_id("dqi_", run_id, entity, record_id),
                        run_id=run_id,
                        severity="warning",
                        code="duplicate_record_conflict",
                        entity=entity,
                        message=f"Conflicting duplicate resolved deterministically: {record_id}",
                    )
                )

        counts = {entity: len(records) for entity, records in all_records.items()}
        report = QualityReport(
            run_id=run_id,
            entity="normalization",
            input_hashes=input_hashes,
            stats=counts,
            issues=issues,
        )
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "run_id": run_id,
                "counts": counts,
                "quality": report.as_dict(),
            }

        output_files: list[str] = []
        for entity, records in all_records.items():
            if not records:
                continue
            output_path = self.project.normalized_dir / OUTPUT_BY_ENTITY[entity]
            write_models(output_path, records)
            output_files.append(self.project.relative(output_path))

        accounts = [record for record in all_records["accounts"] if isinstance(record, Account)]
        snapshots = _account_snapshots(accounts)
        if snapshots:
            snapshot_path = self.project.normalized_dir / "account_snapshots.parquet"
            write_models(snapshot_path, snapshots)
            output_files.append(self.project.relative(snapshot_path))

        assert manifest is not None
        report_paths = write_quality_report(report, self.project.runs_dir / manifest.run_id)
        output_files.extend(self.project.relative(path) for path in report_paths)
        state = self.project.load_state()
        state.last_normalized_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts=counts,
            output_files=output_files,
            warnings=[issue.message for issue in issues],
        )
        return {
            "ok": True,
            "dry_run": False,
            "run_id": manifest.run_id,
            "counts": counts,
            "outputs": output_files,
            "quality": report.as_dict(),
        }
