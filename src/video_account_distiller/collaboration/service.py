"""Orchestration for authorized exports, table syncs, batches, teams, and schedules."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
import yaml
from pydantic import TypeAdapter, ValidationError

from video_account_distiller.adapters.collaboration import (
    CollaborationAdapter,
    HttpExecutor,
    build_collaboration_adapter,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.ingestion import ImportService
from video_account_distiller.models import Platform, Publication
from video_account_distiller.models.collaboration import (
    AuthorizedExportManifest,
    BatchManifest,
    BatchResult,
    BatchTask,
    BatchTaskResult,
    ConnectorConfig,
    FeishuBitableConfig,
    GoogleSheetsConfig,
    ScheduledSnapshotTask,
    SnapshotScheduleResult,
    SyncReceipt,
    TeamConfig,
    TeamMember,
    TeamRole,
)
from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

CONNECTOR_ADAPTER: TypeAdapter[ConnectorConfig] = TypeAdapter(
    FeishuBitableConfig | GoogleSheetsConfig
)
TABLE_BY_ENTITY = {
    "accounts": "accounts",
    "videos": "videos",
    "metrics": "metric_snapshots",
    "comments": "comments",
}


def _load_document(path: Path) -> Any:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Input file not found: {path}")
    try:
        if path.suffix.casefold() in {".yaml", ".yml"}:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        return read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Could not parse structured input: {path}",
            details={"reason": str(exc)},
        ) from exc


def load_connector_config(path: Path) -> ConnectorConfig:
    """Load a strict connector config that contains environment variable names, not secrets."""

    try:
        return CONNECTOR_ADAPTER.validate_python(_load_document(path))
    except ValidationError as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Invalid collaboration connector config",
            details={"reason": str(exc)},
        ) from exc


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _resolve_relative(base_file: Path, value: Any, *, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise DistillerError(ErrorCode.SCHEMA_INVALID, f"Batch parameter {key} must be a path")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_file.parent / candidate
    return candidate.resolve()


class CollaborationService:
    """Bridge validated collaboration rows into and out of the platform-neutral data kernel."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def import_authorized_export(
        self,
        *,
        manifest_path: Path,
        mapping_path: Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        manifest_path = manifest_path.expanduser().resolve()
        try:
            manifest = AuthorizedExportManifest.model_validate(_load_document(manifest_path))
        except ValidationError as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Invalid authorized export manifest",
                details={"reason": str(exc)},
            ) from exc
        manifest.authorization.require("read")
        data_path = Path(manifest.data_file).expanduser()
        if not data_path.is_absolute():
            data_path = manifest_path.parent / data_path
        data_path = data_path.resolve()
        if not data_path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING, f"Export data file not found: {data_path}"
            )
        actual_hash = sha256_file(data_path)
        if actual_hash != manifest.data_sha256:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Authorized export data hash does not match its manifest",
                details={"expected": manifest.data_sha256, "actual": actual_hash},
            )
        receipt, quality, already_imported = ImportService(self.project).import_file(
            entity=manifest.entity,
            source=data_path,
            platform=manifest.platform,
            mapping_path=mapping_path,
            dry_run=dry_run,
        )
        manifest_artifact: str | None = None
        if not dry_run:
            manifest_hash = sha256_file(manifest_path)
            target = self.project.root / "raw" / "authorized-manifests" / f"{manifest_hash}.json"
            if not target.exists():
                atomic_write_json(target, manifest.model_dump(mode="json"))
            manifest_artifact = self.project.relative(target)
            self._touch_state(batch=False)
        return {
            "ok": quality.error_count == 0 or quality.stats["accepted_rows"] > 0,
            "dry_run": dry_run,
            "already_imported": already_imported,
            "authorization_grant_id": manifest.authorization.grant_id,
            "manifest_path": manifest_artifact,
            "receipt": receipt.model_dump(mode="json") if receipt else None,
            "quality": quality.as_dict(),
        }

    def pull(
        self,
        *,
        adapter: CollaborationAdapter,
        entity: str,
        platform: Platform,
        mapping_path: Path | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if entity not in TABLE_BY_ENTITY:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, f"Unsupported sync entity: {entity}")
        result = adapter.read_records()
        raw_payload = {
            "connector": result.connector.value,
            "connector_id": result.connector_id,
            "source_reference": result.source_reference,
            "raw_pages": result.raw_pages,
        }
        source_hash = sha256_json(raw_payload)
        sync_id = stable_id(
            "sync_", result.connector, result.connector_id, "pull", entity, source_hash
        )
        existing = self._load_sync(sync_id)
        if existing is not None and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_synced": True,
                "sync": existing.model_dump(mode="json"),
                "quality": None,
            }
        with tempfile.TemporaryDirectory(prefix="distiller-sync-") as directory:
            export_path = Path(directory) / f"{entity}.json"
            atomic_write_json(export_path, result.records)
            receipt, quality, already_imported = ImportService(self.project).import_file(
                entity=cast(Any, entity),
                source=export_path,
                platform=platform,
                mapping_path=mapping_path,
                dry_run=dry_run,
            )
        sync = SyncReceipt(
            sync_id=sync_id,
            connector=result.connector,
            connector_id=result.connector_id,
            direction="pull",
            entity=cast(Any, entity),
            platform=platform,
            authorization_grant_id=adapter.authorization.grant_id,
            source_hash=source_hash,
            requested_row_count=len(result.records),
            row_count=len(result.records),
            created_at=result.fetched_at,
            run_id=receipt.run_id if receipt else None,
            dry_run=dry_run,
        )
        if not dry_run:
            raw_target = (
                self.project.root
                / "raw"
                / "collaboration"
                / result.connector.value
                / f"{source_hash}.json"
            )
            if not raw_target.exists():
                atomic_write_json(raw_target, raw_payload)
            sync.artifact_paths = [self.project.relative(raw_target)]
            self._save_sync(sync)
            self._touch_state(batch=False)
        return {
            "ok": quality.error_count == 0 or quality.stats["accepted_rows"] > 0,
            "dry_run": dry_run,
            "already_synced": already_imported,
            "sync": sync.model_dump(mode="json"),
            "quality": quality.as_dict(),
        }

    def push(
        self,
        *,
        adapter: CollaborationAdapter,
        entity: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        table = TABLE_BY_ENTITY.get(entity)
        if table is None:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, f"Unsupported sync entity: {entity}")
        table_path = self.project.normalized_dir / f"{table}.parquet"
        if not table_path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"Normalized table is not available: {table}",
            )
        records = cast(list[dict[str, Any]], _json_safe(pq.read_table(table_path).to_pylist()))
        source_hash = sha256_json(records)
        sync_id = stable_id(
            "sync_",
            adapter.connector_kind,
            adapter.connector_id,
            "push",
            entity,
            source_hash,
        )
        existing = self._load_sync(sync_id)
        if existing is not None and not dry_run:
            return {
                "ok": existing.status == "complete",
                "dry_run": False,
                "already_synced": True,
                "sync": existing.model_dump(mode="json"),
                "adapter_result": None,
            }
        if dry_run:
            now = datetime.now(UTC)
            sync = SyncReceipt(
                sync_id=sync_id,
                connector=adapter.connector_kind,
                connector_id=adapter.connector_id,
                direction="push",
                entity=cast(Any, entity),
                authorization_grant_id=adapter.authorization.grant_id,
                source_hash=source_hash,
                requested_row_count=len(records),
                row_count=len(records),
                created_at=now,
                dry_run=True,
            )
            return {
                "ok": True,
                "dry_run": True,
                "already_synced": False,
                "sync": sync.model_dump(mode="json"),
                "adapter_result": None,
            }
        write_result = adapter.append_records(records)
        sync = SyncReceipt(
            sync_id=sync_id,
            connector=write_result.connector,
            connector_id=write_result.connector_id,
            direction="push",
            entity=cast(Any, entity),
            authorization_grant_id=adapter.authorization.grant_id,
            source_hash=source_hash,
            status=(
                "complete"
                if write_result.accepted_rows == write_result.requested_rows
                else "partial"
            ),
            requested_row_count=write_result.requested_rows,
            row_count=write_result.accepted_rows,
            created_at=write_result.written_at,
        )
        self._save_sync(sync)
        self._touch_state(batch=False)
        return {
            "ok": write_result.accepted_rows == write_result.requested_rows,
            "dry_run": False,
            "already_synced": False,
            "sync": sync.model_dump(mode="json"),
            "adapter_result": write_result.model_dump(mode="json"),
        }

    def _load_sync(self, sync_id: str) -> SyncReceipt | None:
        path = self.project.root / "collaboration" / "syncs" / sync_id / "sync.json"
        return SyncReceipt.model_validate(read_json(path)) if path.is_file() else None

    def _save_sync(self, receipt: SyncReceipt) -> Path:
        path = self.project.root / "collaboration" / "syncs" / receipt.sync_id / "sync.json"
        if path.exists():
            existing = SyncReceipt.model_validate(read_json(path))
            if existing.source_hash != receipt.source_hash:
                raise DistillerError(ErrorCode.RAW_INTEGRITY, "Sync receipt ID collision")
            return path
        atomic_write_json(path, receipt.model_dump(mode="json"))
        return path

    def _touch_state(self, *, batch: bool) -> None:
        state = self.project.load_state()
        if batch:
            state.last_batch_at = datetime.now(UTC)
        else:
            state.last_collaboration_at = datetime.now(UTC)
        self.project.save_state(state)


class SnapshotScheduleService:
    """Expose due publication snapshots for an external scheduler without collecting them."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def plan(self, *, now: datetime | None = None, dry_run: bool = False) -> SnapshotScheduleResult:
        current = now or datetime.now(UTC)
        available: dict[str, list[int]] = {}
        with DuckDBStore(self.project.normalized_dir) as store:
            if "metric_snapshots" in store.available_tables():
                rows = store.query(
                    "SELECT video_id, age_hours FROM metric_snapshots "
                    "WHERE age_hours IS NOT NULL ORDER BY video_id, age_hours"
                )
                for row in rows:
                    available.setdefault(str(row["video_id"]), []).append(int(row["age_hours"]))
        tasks: list[ScheduledSnapshotTask] = []
        for path in sorted((self.project.root / "publications").glob("*/publication.json")):
            publication = Publication.model_validate(read_json(path))
            for item in publication.snapshot_plan:
                due_at = publication.published_at + timedelta(hours=item.target_age_hours)
                has_snapshot = any(
                    age >= item.target_age_hours for age in available.get(publication.video_id, [])
                )
                status = "available" if has_snapshot else "due" if due_at <= current else "future"
                tasks.append(
                    ScheduledSnapshotTask(
                        task_id=stable_id(
                            "snap_", publication.publication_id, item.target_age_hours
                        ),
                        publication_id=publication.publication_id,
                        video_id=publication.video_id,
                        platform=publication.platform,
                        target_age_hours=item.target_age_hours,
                        due_at=due_at,
                        status=cast(Any, status),
                    )
                )
        tasks.sort(key=lambda task: (task.due_at, task.task_id))
        future = [task.due_at for task in tasks if task.status == "future"]
        result = SnapshotScheduleResult(
            generated_at=current,
            tasks=tasks,
            next_due_at=min(future) if future else None,
        )
        if not dry_run:
            target = self.project.root / "collaboration" / "schedules" / "snapshot-plan.json"
            atomic_write_json(target, result.model_dump(mode="json"))
        return result


class TeamConfigService:
    """Create and validate credential-free team policy configuration."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project
        self.path = project.root / "team.yaml"

    def initialize(
        self, *, owner_id: str, owner_name: str | None = None
    ) -> tuple[TeamConfig, bool]:
        if self.path.exists():
            return self.load(), True
        config = TeamConfig(
            team_id=stable_id("team_", self.project.load_state().project_id),
            name=f"{self.project.load_state().project_name} team",
            members=[
                TeamMember(
                    member_id=owner_id,
                    display_name=owner_name,
                    role=TeamRole.OWNER,
                )
            ],
            created_at=datetime.now(UTC),
        )
        atomic_write_text(
            self.path,
            yaml.safe_dump(config.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        )
        return config, False

    def load(self) -> TeamConfig:
        if not self.path.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Team config not found: {self.path}")
        try:
            return TeamConfig.model_validate(_load_document(self.path))
        except ValidationError as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Invalid team configuration",
                details={"reason": str(exc)},
            ) from exc


class BatchService:
    """Run a validated list of adapter and snapshot operations with isolated task results."""

    def __init__(self, project: ProjectLayout, *, executor: HttpExecutor | None = None) -> None:
        self.project = project
        self.executor = executor
        self.collaboration = CollaborationService(project)

    def run(self, *, manifest_path: Path, dry_run: bool = False) -> BatchResult:
        manifest_path = manifest_path.expanduser().resolve()
        try:
            manifest = BatchManifest.model_validate(_load_document(manifest_path))
        except ValidationError as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Invalid batch manifest",
                details={"reason": str(exc)},
            ) from exc
        started = datetime.now(UTC)
        run_manifest = None
        if not dry_run:
            run_manifest = self.project.begin_run(
                "batch run", input_hashes=[sha256_file(manifest_path)]
            )
        task_results: list[BatchTaskResult] = []
        for task in manifest.tasks:
            try:
                output = self._run_task(task, base_file=manifest_path, dry_run=dry_run)
                task_results.append(
                    BatchTaskResult(
                        task_id=task.task_id,
                        operation=task.operation,
                        status="success",
                        output=cast(dict[str, Any], _json_safe(output)),
                    )
                )
            except DistillerError as exc:
                task_results.append(
                    BatchTaskResult(
                        task_id=task.task_id,
                        operation=task.operation,
                        status="failed",
                        error=exc.as_dict()["error"],
                    )
                )
                if not manifest.continue_on_error:
                    break
            except Exception as exc:
                wrapped = DistillerError(
                    ErrorCode.INTERNAL,
                    "Unexpected batch task failure",
                    details={"type": type(exc).__name__},
                )
                task_results.append(
                    BatchTaskResult(
                        task_id=task.task_id,
                        operation=task.operation,
                        status="failed",
                        error=wrapped.as_dict()["error"],
                    )
                )
                if not manifest.continue_on_error:
                    break
        result = BatchResult(
            batch_id=manifest.batch_id,
            started_at=started,
            finished_at=datetime.now(UTC),
            dry_run=dry_run,
            tasks=task_results,
        )
        if not dry_run:
            target = (
                self.project.root
                / "collaboration"
                / "batches"
                / manifest.batch_id
                / "batch-result.json"
            )
            result.artifact_path = self.project.relative(target)
            atomic_write_json(target, result.model_dump(mode="json"))
            assert run_manifest is not None
            failures = [item for item in task_results if item.status == "failed"]
            self.project.finish_run(
                run_manifest,
                success=not failures,
                processed_counts={
                    "tasks": len(task_results),
                    "succeeded": len(task_results) - len(failures),
                    "failed": len(failures),
                },
                output_files=[self.project.relative(target)],
                errors=[str(item.error) for item in failures],
            )
            self.collaboration._touch_state(batch=True)
        return result

    def _run_task(self, task: BatchTask, *, base_file: Path, dry_run: bool) -> dict[str, Any]:
        params = task.parameters
        if task.operation == "authorized-export":
            manifest = _resolve_relative(base_file, params.get("manifest"), key="manifest")
            mapping = (
                _resolve_relative(base_file, params["mapping"], key="mapping")
                if params.get("mapping")
                else None
            )
            return self.collaboration.import_authorized_export(
                manifest_path=manifest, mapping_path=mapping, dry_run=dry_run
            )
        if task.operation in {"sync-pull", "sync-push"}:
            config_path = _resolve_relative(
                base_file, params.get("connector_config"), key="connector_config"
            )
            config = load_connector_config(config_path)
            adapter = build_collaboration_adapter(config, executor=self.executor)
            entity = str(params.get("entity", ""))
            if task.operation == "sync-push":
                return self.collaboration.push(adapter=adapter, entity=entity, dry_run=dry_run)
            try:
                platform = Platform(str(params["platform"]))
            except (KeyError, ValueError) as exc:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "sync-pull task requires a supported platform",
                ) from exc
            mapping = (
                _resolve_relative(base_file, params["mapping"], key="mapping")
                if params.get("mapping")
                else None
            )
            return self.collaboration.pull(
                adapter=adapter,
                entity=entity,
                platform=platform,
                mapping_path=mapping,
                dry_run=dry_run,
            )
        schedule = SnapshotScheduleService(self.project).plan(dry_run=dry_run)
        return schedule.model_dump(mode="json")
