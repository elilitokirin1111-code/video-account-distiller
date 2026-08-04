"""Audited public-beta drills, observations, incidents, and release-freeze gates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import tempfile
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import ValidationError

from video_account_distiller.api.tasks import (
    TaskExecutionContext,
    TaskQueueSettings,
    TaskStore,
    TaskWorkerPool,
    enqueue_persistent_task,
    retry_persistent_task,
)
from video_account_distiller.doctor import doctor_report
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models.release import (
    CompatibilitySnapshot,
    ProjectMigrationDrillResult,
    PublicBetaCampaign,
    PublicBetaEvidenceBundleManifest,
    PublicBetaFreezeRecord,
    PublicBetaFreezeVerification,
    PublicBetaIncident,
    PublicBetaIncidentSeverity,
    PublicBetaObservation,
    PublicBetaStatus,
    QueueResilienceDrillResult,
    ReleaseAuditIssue,
)
from video_account_distiller.project_archive import (
    backup_manifest_path,
    restore_project_backup,
    run_backup_recovery_drill,
    verify_project_backup,
)
from video_account_distiller.project_migration import apply_project_migration
from video_account_distiller.recovery import run_task_recovery_drill
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import new_run_id, stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.validation import validate_project
from video_account_distiller.version import CORE_SCHEMA_VERSION, PACKAGE_VERSION

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
_TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}
_BUNDLE_MANIFEST_NAME = "PUBLIC_BETA_EVIDENCE_MANIFEST.json"
_MAX_BUNDLE_FILES = 500
_MAX_BUNDLE_BYTES = 50 * 1024 * 1024


def _require_safe_id(value: str, *, field: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"{field} must be a 1-48 character safe identifier",
            details={"field": field},
        )
    return value


def capture_compatibility_snapshot(
    project: ProjectLayout,
    *,
    machine_label: str,
    observed_at: datetime | None = None,
) -> CompatibilitySnapshot:
    """Capture a secret-free runtime and project compatibility fingerprint."""

    _require_safe_id(machine_label, field="machine_label")
    observed_at = observed_at or datetime.now(UTC)
    report = doctor_report(project.root)
    node_fingerprint = platform.node() or machine_label
    machine_profile_id = stable_id(
        "machine_",
        node_fingerprint,
        platform.system(),
        platform.machine(),
        platform.python_implementation(),
        platform.python_version(),
    )
    capabilities = {
        key: bool(value) for key, value in report.capabilities.model_dump(mode="python").items()
    }
    return CompatibilitySnapshot(
        observed_at=observed_at,
        machine_profile_id=machine_profile_id,
        machine_label_hash=stable_id("machine_label_", machine_label),
        operating_system=report.operating_system,
        architecture=platform.machine() or "unknown",
        python_version=report.python_version,
        python_implementation=platform.python_implementation(),
        package_version=report.package_version,
        core_schema_version=CORE_SCHEMA_VERSION,
        doctor_ok=report.ok,
        project_validation_ok=bool(report.project and report.project.validation_ok),
        capabilities=capabilities,
    )


async def _wait_for_tasks(
    store: TaskStore,
    task_ids: list[str],
    *,
    timeout_seconds: float = 15.0,
) -> list[dict[str, Any]]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        tasks = [store.get(task_id) or {} for task_id in task_ids]
        if all(task.get("status") in _TERMINAL_TASK_STATES for task in tasks):
            return tasks
        if asyncio.get_running_loop().time() >= deadline:
            raise DistillerError(
                ErrorCode.COLLECTION_TIMEOUT,
                "Public-beta queue drill timed out",
                details={"task_ids": task_ids},
            )
        await asyncio.sleep(0.01)


def run_queue_resilience_drill(
    account_labels: list[str],
    *,
    concurrency_limit: int = 2,
    workdir: Path | None = None,
) -> QueueResilienceDrillResult:
    """Exercise bounded parallel account jobs, one injected failure, and explicit retry."""

    unique_labels = list(dict.fromkeys(account_labels))
    if len(unique_labels) < 2 or len(unique_labels) > 20:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Queue resilience drill requires 2-20 unique account labels",
        )
    if concurrency_limit < 2 or concurrency_limit > min(8, len(unique_labels)):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Queue drill concurrency must be between 2 and the bounded account count",
        )

    started_at = datetime.now(UTC)
    base_dir = workdir.expanduser().resolve() if workdir is not None else None
    if base_dir is not None:
        base_dir.mkdir(parents=True, exist_ok=True)
    temporary_root: Path | None = None
    max_observed_concurrent = 0
    active = 0
    lock = threading.Lock()
    failed_once: set[str] = set()
    injected_label = unique_labels[0]
    steps: list[str] = []
    completed_count = 0
    injected_failure_count = 0
    retry_completed = False
    failure_isolated = False

    with tempfile.TemporaryDirectory(prefix="distiller-queue-drill-", dir=base_dir) as temporary:
        temporary_root = Path(temporary).resolve()
        settings = TaskQueueSettings(
            max_concurrent=concurrency_limit,
            max_pending=max(20, len(unique_labels) + 2),
            workflow_concurrency=concurrency_limit,
            provider_concurrency=1,
            model_concurrency=1,
            poll_interval_seconds=0.01,
        )
        store = TaskStore(temporary_root / "tasks.sqlite3", queue_settings=settings)

        def handler(
            context: TaskExecutionContext,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            nonlocal active, max_observed_concurrent
            label_hash = str(payload["account_label_hash"])
            with lock:
                active += 1
                max_observed_concurrent = max(max_observed_concurrent, active)
            try:
                context.progress(0.5, "fault_probe", "isolated account probe running")
                time.sleep(0.05)
                if bool(payload.get("inject_failure")) and label_hash not in failed_once:
                    failed_once.add(label_hash)
                    raise DistillerError(
                        ErrorCode.INTERNAL,
                        "Injected public-beta account failure",
                        details={"fault_injection": True},
                    )
                return {"account_label_hash": label_hash, "probe": "completed"}
            finally:
                with lock:
                    active -= 1

        submissions = [
            enqueue_persistent_task(
                store,
                task_type="public_beta_account_probe",
                resource_class="workflow",
                job_payload={
                    "account_label_hash": stable_id("account_probe_", label),
                    "inject_failure": label == injected_label,
                },
                task_metadata={"scope": "isolated_public_beta_drill"},
                retryable=True,
            )
            for label in unique_labels
        ]
        task_ids = [str(item["task_id"]) for item in submissions]
        steps.append("bounded_account_tasks_enqueued")

        async def scenario() -> None:
            nonlocal completed_count, injected_failure_count, retry_completed
            nonlocal failure_isolated
            pool = TaskWorkerPool(store, {"public_beta_account_probe": handler})
            await pool.start()
            try:
                first_tasks = await _wait_for_tasks(store, task_ids)
                completed_count = sum(task.get("status") == "completed" for task in first_tasks)
                failed_tasks = [task for task in first_tasks if task.get("status") == "failed"]
                injected_failure_count = len(failed_tasks)
                failure_isolated = (
                    completed_count == len(unique_labels) - 1 and len(failed_tasks) == 1
                )
                steps.append("injected_failure_isolated")
                if len(failed_tasks) != 1:
                    return
                retry = retry_persistent_task(store, failed_tasks[0])
                retry_id = str(retry["task_id"])
                steps.append("failed_account_retry_enqueued")
                retried = (await _wait_for_tasks(store, [retry_id]))[0]
                retry_completed = retried.get("status") == "completed"
                if retry_completed:
                    completed_count += 1
                    steps.append("explicit_retry_completed")
            finally:
                await pool.stop()

        asyncio.run(scenario())

    database_removed = temporary_root is not None and not temporary_root.exists()
    parallelism_observed = max_observed_concurrent >= 2
    ok = all(
        (
            parallelism_observed,
            max_observed_concurrent <= concurrency_limit,
            completed_count == len(unique_labels),
            injected_failure_count == 1,
            retry_completed,
            failure_isolated,
            database_removed,
        )
    )
    return QueueResilienceDrillResult(
        ok=ok,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        task_count=len(unique_labels),
        concurrency_limit=concurrency_limit,
        max_observed_concurrent=max_observed_concurrent,
        completed_count=completed_count,
        injected_failure_count=injected_failure_count,
        retry_completed=retry_completed,
        failure_isolated=failure_isolated,
        database_scope="temporary",
        database_removed=database_removed,
        steps=steps or ["drill_failed_before_first_step"],
    )


def run_project_migration_drill(project: ProjectLayout) -> ProjectMigrationDrillResult:
    """Migrate and roll back an isolated legacy project using the production migrator."""

    started_at = datetime.now(UTC)
    temporary_root: Path | None = None
    steps: list[str] = []
    backup_verified = False
    migration_applied = False
    migrated_schema_verified = False
    rollback_verified = False
    validation_errors = 1
    source_schema_version = "0.0.0"
    with tempfile.TemporaryDirectory(prefix="distiller-migration-drill-") as temporary:
        temporary_root = Path(temporary).resolve()
        legacy, _ = ProjectLayout.initialize(
            temporary_root / "迁移 验收项目",
            project_name=f"{project.load_state().project_name}-migration-drill",
        )
        payload: Any = read_json(legacy.state_path)
        if not isinstance(payload, dict):
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Migration drill state is invalid")
        payload["schema_version"] = source_schema_version
        atomic_write_json(legacy.state_path, payload)
        steps.append("legacy_state_fixture_created")

        backup_path = temporary_root / "pre-migration.zip"
        migrated = apply_project_migration(
            legacy,
            backup_path=backup_path,
            confirm=True,
        )
        migration_applied = migrated.applied
        steps.append("production_migrator_applied")
        verification = verify_project_backup(backup_path)
        backup_verified = verification.ok and backup_manifest_path(backup_path).is_file()
        steps.append("pre_migration_backup_verified")

        migrated_state = legacy.load_state()
        migrated_schema_verified = migrated_state.schema_version == CORE_SCHEMA_VERSION
        validation = validate_project(legacy, persist=False)
        validation_errors = validation.error_count
        steps.append("migrated_project_validated")

        rollback_destination = temporary_root / "rollback-project"
        rollback = restore_project_backup(backup_path, rollback_destination)
        rollback_payload: Any = read_json(rollback_destination / ".distiller-state.json")
        rollback_verified = bool(
            rollback.ok
            and isinstance(rollback_payload, dict)
            and rollback_payload.get("schema_version") == source_schema_version
        )
        steps.append("pre_migration_backup_restored")

    workspace_removed = temporary_root is not None and not temporary_root.exists()
    ok = all(
        (
            backup_verified,
            migration_applied,
            migrated_schema_verified,
            rollback_verified,
            validation_errors == 0,
            workspace_removed,
        )
    )
    return ProjectMigrationDrillResult(
        ok=ok,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        source_schema_version=source_schema_version,
        target_schema_version=CORE_SCHEMA_VERSION,
        backup_verified=backup_verified,
        migration_applied=migration_applied,
        migrated_schema_verified=migrated_schema_verified,
        rollback_verified=rollback_verified,
        validation_errors=validation_errors,
        workspace_scope="temporary",
        workspace_removed=workspace_removed,
        steps=steps or ["drill_failed_before_first_step"],
    )


def _evidence_payload(
    campaign: PublicBetaCampaign,
    observations: list[PublicBetaObservation],
    incidents: list[PublicBetaIncident],
) -> dict[str, Any]:
    return {
        "campaign": campaign.model_dump(mode="json"),
        "observations": [
            item.model_dump(mode="json")
            for item in sorted(observations, key=lambda item: item.observation_id)
        ],
        "incidents": [
            item.model_dump(mode="json")
            for item in sorted(incidents, key=lambda item: item.incident_id)
        ],
    }


def _evaluate_public_beta_status(
    campaign: PublicBetaCampaign,
    observations: list[PublicBetaObservation],
    incidents: list[PublicBetaIncident],
    *,
    evaluated_at: datetime,
    installed_version: str,
) -> PublicBetaStatus:
    dates = sorted({item.observed_at.date() for item in observations})
    elapsed_days = (dates[-1] - dates[0]).days + 1 if dates else 0
    machine_profiles = {item.compatibility.machine_profile_id for item in observations}
    account_labels = {
        account_hash for item in observations for account_hash in item.account_label_hashes
    }
    successful = sum(1 for item in observations if item.ok)
    severe_incidents = sum(
        1
        for item in incidents
        if item.severity in {PublicBetaIncidentSeverity.HIGH, PublicBetaIncidentSeverity.CRITICAL}
    )
    blockers: list[str] = []
    if campaign.target_version != installed_version:
        blockers.append("target_version_mismatch")
    if any(item.observed_at > evaluated_at for item in observations):
        blockers.append("future_observation_present")
    if elapsed_days < campaign.min_calendar_days:
        blockers.append("pilot_duration_incomplete")
    if len(dates) < campaign.min_distinct_observation_days:
        blockers.append("daily_observations_incomplete")
    if len(machine_profiles) < campaign.min_machine_profiles:
        blockers.append("machine_coverage_incomplete")
    if len(account_labels) < campaign.min_account_labels:
        blockers.append("account_coverage_incomplete")
    if not observations or successful != len(observations):
        blockers.append("observation_failures_present")
    if severe_incidents:
        blockers.append("high_severity_incidents_present")
    return PublicBetaStatus(
        campaign_id=campaign.campaign_id,
        target_version=campaign.target_version,
        evaluated_at=evaluated_at,
        eligible_for_freeze=not blockers,
        blockers=blockers,
        observation_count=len(observations),
        successful_observations=successful,
        distinct_observation_days=len(dates),
        elapsed_calendar_days=elapsed_days,
        machine_profiles=len(machine_profiles),
        account_labels=len(account_labels),
        high_or_critical_incidents=severe_incidents,
        min_calendar_days=campaign.min_calendar_days,
        min_distinct_observation_days=campaign.min_distinct_observation_days,
        min_machine_profiles=campaign.min_machine_profiles,
        min_account_labels=campaign.min_account_labels,
    )


def _verification_issue(
    code: str,
    message: str,
    *,
    path: str | None = None,
) -> ReleaseAuditIssue:
    return ReleaseAuditIssue(severity="error", code=code, message=message, path=path)


def _verify_public_beta_records(
    *,
    campaign: PublicBetaCampaign,
    freeze: PublicBetaFreezeRecord,
    observations: list[PublicBetaObservation],
    incidents: list[PublicBetaIncident],
    source_path: Path,
    source_kind: Literal["directory", "bundle"],
    expected_version: str | None,
    source_sha256: str | None,
    issues: list[ReleaseAuditIssue],
) -> PublicBetaFreezeVerification:
    if freeze.campaign_id != campaign.campaign_id:
        issues.append(
            _verification_issue(
                "public_beta_campaign_mismatch",
                "Freeze campaign does not match campaign.json",
            )
        )
    if freeze.target_version != campaign.target_version:
        issues.append(
            _verification_issue(
                "public_beta_target_version_mismatch",
                "Freeze target version does not match campaign.json",
            )
        )
    if expected_version is not None and freeze.target_version != expected_version:
        issues.append(
            _verification_issue(
                "public_beta_release_version_mismatch",
                f"Frozen version {freeze.target_version} does not match {expected_version}",
            )
        )
    if not freeze.confirmed:
        issues.append(
            _verification_issue(
                "public_beta_freeze_unconfirmed",
                "Freeze record is not explicitly confirmed",
            )
        )
    if freeze.frozen_at < freeze.status.evaluated_at:
        issues.append(
            _verification_issue(
                "public_beta_freeze_time_invalid",
                "Freeze timestamp precedes its status evaluation",
            )
        )
    if any(item.campaign_id != campaign.campaign_id for item in observations):
        issues.append(
            _verification_issue(
                "public_beta_observation_campaign_mismatch",
                "At least one observation belongs to another campaign",
            )
        )
    if any(item.campaign_id != campaign.campaign_id for item in incidents):
        issues.append(
            _verification_issue(
                "public_beta_incident_campaign_mismatch",
                "At least one incident belongs to another campaign",
            )
        )
    observation_ids = [item.observation_id for item in observations]
    incident_ids = [item.incident_id for item in incidents]
    if len(observation_ids) != len(set(observation_ids)):
        issues.append(
            _verification_issue(
                "public_beta_duplicate_observation",
                "Observation identifiers are not unique",
            )
        )
    if len(incident_ids) != len(set(incident_ids)):
        issues.append(
            _verification_issue(
                "public_beta_duplicate_incident",
                "Incident identifiers are not unique",
            )
        )

    computed_sha256 = sha256_json(_evidence_payload(campaign, observations, incidents))
    if computed_sha256 != freeze.evidence_sha256:
        issues.append(
            _verification_issue(
                "public_beta_evidence_hash_mismatch",
                "Frozen evidence hash does not match the current campaign evidence",
            )
        )
    recomputed_status = _evaluate_public_beta_status(
        campaign,
        observations,
        incidents,
        evaluated_at=freeze.status.evaluated_at,
        installed_version=campaign.target_version,
    )
    if recomputed_status != freeze.status:
        issues.append(
            _verification_issue(
                "public_beta_status_mismatch",
                "Frozen gate status cannot be reproduced from the evidence",
            )
        )
    if not freeze.status.eligible_for_freeze or freeze.status.blockers:
        issues.append(
            _verification_issue(
                "public_beta_freeze_not_eligible",
                "Freeze record does not contain an eligible zero-blocker status",
            )
        )
    return PublicBetaFreezeVerification(
        ok=not any(issue.severity == "error" for issue in issues),
        checked_at=datetime.now(UTC),
        source_path=str(source_path),
        source_kind=source_kind,
        campaign_id=campaign.campaign_id,
        target_version=freeze.target_version,
        frozen_at=freeze.frozen_at,
        declared_evidence_sha256=freeze.evidence_sha256,
        computed_evidence_sha256=computed_sha256,
        source_sha256=source_sha256,
        observation_count=len(observations),
        incident_count=len(incidents),
        issues=issues,
    )


def _failed_verification(
    source: Path,
    *,
    source_kind: Literal["directory", "bundle"],
    issues: list[ReleaseAuditIssue],
    source_sha256: str | None = None,
) -> PublicBetaFreezeVerification:
    return PublicBetaFreezeVerification(
        ok=False,
        checked_at=datetime.now(UTC),
        source_path=str(source),
        source_kind=source_kind,
        source_sha256=source_sha256,
        observation_count=0,
        incident_count=0,
        issues=issues,
    )


def _campaign_document_paths(campaign_dir: Path) -> list[Path]:
    paths = [campaign_dir / "campaign.json", campaign_dir / "freeze.json"]
    observations = campaign_dir / "observations"
    incidents = campaign_dir / "incidents"
    if observations.is_dir():
        paths.extend(sorted(observations.rglob("*.json")))
    if incidents.is_dir():
        paths.extend(sorted(incidents.glob("*.json")))
    return paths


def _verify_campaign_directory(
    campaign_dir: Path,
    *,
    expected_version: str | None,
) -> PublicBetaFreezeVerification:
    campaign_dir = campaign_dir.expanduser().resolve()
    freeze_path = campaign_dir / "freeze.json"
    issues: list[ReleaseAuditIssue] = []
    paths = _campaign_document_paths(campaign_dir)
    missing = [path for path in paths[:2] if not path.is_file()]
    if missing:
        for path in missing:
            issues.append(
                _verification_issue(
                    "public_beta_required_evidence_missing",
                    "Required public-beta evidence file is missing",
                    path=str(path),
                )
            )
        return _failed_verification(freeze_path, source_kind="directory", issues=issues)

    for path in paths:
        if path.is_symlink():
            issues.append(
                _verification_issue(
                    "public_beta_evidence_symlink",
                    "Public-beta evidence files cannot be symbolic links",
                    path=str(path),
                )
            )

    declared = {path.resolve() for path in paths}
    unexpected_json = [
        path for path in campaign_dir.rglob("*.json") if path.resolve() not in declared
    ]
    for path in unexpected_json:
        issues.append(
            _verification_issue(
                "public_beta_untracked_json",
                "Campaign contains a JSON file outside the evidence layout",
                path=str(path),
            )
        )
    try:
        campaign = PublicBetaCampaign.model_validate(read_json(campaign_dir / "campaign.json"))
        freeze = PublicBetaFreezeRecord.model_validate(read_json(freeze_path))
        observations: list[PublicBetaObservation] = []
        incidents: list[PublicBetaIncident] = []
        for path in paths[2:]:
            relative = path.relative_to(campaign_dir)
            if relative.parts[0] == "observations":
                observation = PublicBetaObservation.model_validate(read_json(path))
                if (
                    len(relative.parts) != 3
                    or relative.parts[1] != observation.observed_at.date().isoformat()
                    or path.stem != observation.observation_id
                ):
                    issues.append(
                        _verification_issue(
                            "public_beta_observation_path_mismatch",
                            "Observation path does not match its date and identifier",
                            path=str(path),
                        )
                    )
                observations.append(observation)
            elif relative.parts[0] == "incidents":
                incident = PublicBetaIncident.model_validate(read_json(path))
                if len(relative.parts) != 2 or path.stem != incident.incident_id:
                    issues.append(
                        _verification_issue(
                            "public_beta_incident_path_mismatch",
                            "Incident path does not match its identifier",
                            path=str(path),
                        )
                    )
                incidents.append(incident)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        issues.append(
            _verification_issue(
                "public_beta_evidence_invalid",
                f"Public-beta evidence is unreadable or invalid: {exc}",
                path=str(campaign_dir),
            )
        )
        source_sha256 = sha256_file(freeze_path) if freeze_path.is_file() else None
        return _failed_verification(
            freeze_path,
            source_kind="directory",
            issues=issues,
            source_sha256=source_sha256,
        )
    return _verify_public_beta_records(
        campaign=campaign,
        freeze=freeze,
        observations=observations,
        incidents=incidents,
        source_path=freeze_path,
        source_kind="directory",
        expected_version=expected_version,
        source_sha256=sha256_file(freeze_path),
        issues=issues,
    )


def _unsafe_bundle_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(
        not name
        or "\\" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    )


def _verify_public_beta_bundle(
    bundle: Path,
    *,
    expected_version: str | None,
) -> PublicBetaFreezeVerification:
    bundle = bundle.expanduser().resolve()
    issues: list[ReleaseAuditIssue] = []
    if not bundle.is_file():
        issues.append(
            _verification_issue(
                "public_beta_bundle_missing",
                "Public-beta evidence bundle does not exist",
                path=str(bundle),
            )
        )
        return _failed_verification(bundle, source_kind="bundle", issues=issues)
    source_sha256 = sha256_file(bundle)
    try:
        with zipfile.ZipFile(bundle, mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                issues.append(
                    _verification_issue(
                        "public_beta_bundle_duplicate_member",
                        "Evidence bundle contains duplicate member names",
                        path=str(bundle),
                    )
                )
            if (
                len(infos) > _MAX_BUNDLE_FILES
                or sum(info.file_size for info in infos) > _MAX_BUNDLE_BYTES
            ):
                issues.append(
                    _verification_issue(
                        "public_beta_bundle_size_limit",
                        "Evidence bundle exceeds the bounded file-count or size limit",
                        path=str(bundle),
                    )
                )
            if any(
                info.is_dir() or info.flag_bits & 0x1 or _unsafe_bundle_member(info.filename)
                for info in infos
            ):
                issues.append(
                    _verification_issue(
                        "public_beta_bundle_unsafe_member",
                        "Evidence bundle contains an unsafe, encrypted, or directory member",
                        path=str(bundle),
                    )
                )
            if issues:
                return _failed_verification(
                    bundle,
                    source_kind="bundle",
                    issues=issues,
                    source_sha256=source_sha256,
                )
            if _BUNDLE_MANIFEST_NAME not in names:
                issues.append(
                    _verification_issue(
                        "public_beta_bundle_manifest_missing",
                        "Evidence bundle manifest is missing",
                        path=str(bundle),
                    )
                )
                return _failed_verification(
                    bundle,
                    source_kind="bundle",
                    issues=issues,
                    source_sha256=source_sha256,
                )
            manifest = PublicBetaEvidenceBundleManifest.model_validate_json(
                archive.read(_BUNDLE_MANIFEST_NAME)
            )
            expected_names = {_BUNDLE_MANIFEST_NAME, *manifest.files}
            if set(names) != expected_names:
                issues.append(
                    _verification_issue(
                        "public_beta_bundle_member_mismatch",
                        "Bundle members do not exactly match the signed manifest inventory",
                        path=str(bundle),
                    )
                )
            prefix = f"{manifest.campaign_id}/"
            if any(not name.startswith(prefix) for name in manifest.files):
                issues.append(
                    _verification_issue(
                        "public_beta_bundle_campaign_path_mismatch",
                        "Bundle evidence is outside the declared campaign directory",
                        path=str(bundle),
                    )
                )
            for name, declared_sha256 in manifest.files.items():
                if not re.fullmatch(r"[0-9a-f]{64}", declared_sha256):
                    issues.append(
                        _verification_issue(
                            "public_beta_bundle_file_hash_invalid",
                            "Bundle manifest contains an invalid file hash",
                            path=name,
                        )
                    )
                    continue
                if name not in names:
                    continue
                actual_sha256 = hashlib.sha256(archive.read(name)).hexdigest()
                if actual_sha256 != declared_sha256:
                    issues.append(
                        _verification_issue(
                            "public_beta_bundle_file_hash_mismatch",
                            "Bundle member does not match its declared hash",
                            path=name,
                        )
                    )
            if issues:
                return _failed_verification(
                    bundle,
                    source_kind="bundle",
                    issues=issues,
                    source_sha256=source_sha256,
                )
            with tempfile.TemporaryDirectory(prefix="distiller-beta-verify-") as temporary:
                archive.extractall(temporary)
                verification = _verify_campaign_directory(
                    Path(temporary) / manifest.campaign_id,
                    expected_version=expected_version,
                )
    except (OSError, zipfile.BadZipFile, KeyError, ValidationError) as exc:
        issues.append(
            _verification_issue(
                "public_beta_bundle_invalid",
                f"Public-beta evidence bundle is invalid: {exc}",
                path=str(bundle),
            )
        )
        return _failed_verification(
            bundle,
            source_kind="bundle",
            issues=issues,
            source_sha256=source_sha256,
        )

    issues.extend(verification.issues)
    if verification.campaign_id != manifest.campaign_id:
        issues.append(
            _verification_issue(
                "public_beta_bundle_campaign_mismatch",
                "Bundle manifest campaign does not match the frozen evidence",
            )
        )
    if verification.target_version != manifest.target_version:
        issues.append(
            _verification_issue(
                "public_beta_bundle_version_mismatch",
                "Bundle manifest version does not match the frozen evidence",
            )
        )
    if verification.frozen_at != manifest.frozen_at:
        issues.append(
            _verification_issue(
                "public_beta_bundle_freeze_time_mismatch",
                "Bundle manifest freeze time does not match freeze.json",
            )
        )
    if verification.declared_evidence_sha256 != manifest.evidence_sha256:
        issues.append(
            _verification_issue(
                "public_beta_bundle_evidence_hash_mismatch",
                "Bundle manifest evidence hash does not match freeze.json",
            )
        )
    if verification.observation_count != manifest.observation_count:
        issues.append(
            _verification_issue(
                "public_beta_bundle_observation_count_mismatch",
                "Bundle manifest observation count does not match its evidence",
            )
        )
    if verification.incident_count != manifest.incident_count:
        issues.append(
            _verification_issue(
                "public_beta_bundle_incident_count_mismatch",
                "Bundle manifest incident count does not match its evidence",
            )
        )
    return verification.model_copy(
        update={
            "ok": not any(issue.severity == "error" for issue in issues),
            "checked_at": datetime.now(UTC),
            "source_path": str(bundle),
            "source_kind": "bundle",
            "source_sha256": source_sha256,
            "issues": issues,
        }
    )


def verify_public_beta_evidence(
    source: Path,
    *,
    expected_version: str | None = None,
) -> PublicBetaFreezeVerification:
    """Recompute a frozen campaign from its directory, freeze path, or portable bundle."""

    source = source.expanduser().resolve()
    if source.suffix.casefold() == ".zip":
        return _verify_public_beta_bundle(source, expected_version=expected_version)
    if source.is_dir():
        return _verify_campaign_directory(source, expected_version=expected_version)
    if source.name.casefold() == "freeze.json":
        return _verify_campaign_directory(source.parent, expected_version=expected_version)
    return _failed_verification(
        source,
        source_kind="directory",
        issues=[
            _verification_issue(
                "public_beta_evidence_source_invalid",
                "Expected a campaign directory, freeze.json, or ZIP evidence bundle",
                path=str(source),
            )
        ],
    )


def _deterministic_zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_public_beta_evidence_bundle(
    campaign_dir: Path,
    output: Path,
    *,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic portable bundle only from verified frozen evidence."""

    campaign_dir = campaign_dir.expanduser().resolve()
    output = output.expanduser().resolve()
    verification = _verify_campaign_directory(
        campaign_dir,
        expected_version=expected_version,
    )
    if not verification.ok:
        raise DistillerError(
            ErrorCode.PUBLIC_BETA_GATE_FAILED,
            "Public-beta evidence failed verification and cannot be bundled",
            details={"issues": [issue.model_dump(mode="json") for issue in verification.issues]},
        )
    if output.exists():
        raise DistillerError(
            ErrorCode.PROJECT_EXISTS,
            "Public-beta evidence bundle already exists",
            details={"path": str(output)},
        )
    if output.suffix.casefold() != ".zip":
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Public-beta evidence bundle output must use the .zip extension",
            details={"path": str(output)},
        )
    if output.is_relative_to(campaign_dir):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Public-beta evidence bundle must be outside the campaign directory",
            details={"path": str(output)},
        )
    campaign = PublicBetaCampaign.model_validate(read_json(campaign_dir / "campaign.json"))
    freeze = PublicBetaFreezeRecord.model_validate(read_json(campaign_dir / "freeze.json"))
    paths = _campaign_document_paths(campaign_dir)
    members = {
        f"{campaign.campaign_id}/{path.relative_to(campaign_dir).as_posix()}": path.read_bytes()
        for path in paths
    }
    manifest = PublicBetaEvidenceBundleManifest(
        campaign_id=campaign.campaign_id,
        target_version=freeze.target_version,
        frozen_at=freeze.frozen_at,
        evidence_sha256=freeze.evidence_sha256,
        observation_count=verification.observation_count,
        incident_count=verification.incident_count,
        files={
            name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(members.items())
        },
    )
    manifest_payload = (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(_deterministic_zip_info(_BUNDLE_MANIFEST_NAME), manifest_payload)
            for name, payload in sorted(members.items()):
                archive.writestr(_deterministic_zip_info(name), payload)
        os.replace(temporary_name, output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    bundled = _verify_public_beta_bundle(output, expected_version=expected_version)
    if not bundled.ok:
        output.unlink(missing_ok=True)
        raise DistillerError(
            ErrorCode.PUBLIC_BETA_GATE_FAILED,
            "Created public-beta bundle failed post-write verification",
            details={"issues": [issue.model_dump(mode="json") for issue in bundled.issues]},
        )
    return {
        "ok": True,
        "bundle_path": str(output),
        "bundle_sha256": bundled.source_sha256,
        "manifest": manifest.model_dump(mode="json"),
        "verification": bundled.model_dump(mode="json"),
    }


class PublicBetaService:
    """Persist immutable pilot evidence and decide whether a version may be frozen."""

    def __init__(self, evidence_root: Path) -> None:
        self.evidence_root = evidence_root.expanduser().resolve()

    def _campaign_dir(self, campaign_id: str) -> Path:
        return self.evidence_root / _require_safe_id(campaign_id, field="campaign_id")

    def _campaign_path(self, campaign_id: str) -> Path:
        return self._campaign_dir(campaign_id) / "campaign.json"

    def _freeze_path(self, campaign_id: str) -> Path:
        return self._campaign_dir(campaign_id) / "freeze.json"

    def initialize(
        self,
        *,
        campaign_id: str,
        target_version: str = PACKAGE_VERSION,
        min_calendar_days: int = 7,
        min_distinct_observation_days: int = 7,
        min_machine_profiles: int = 2,
        min_account_labels: int = 3,
    ) -> dict[str, Any]:
        campaign_path = self._campaign_path(campaign_id)
        expected = {
            "campaign_id": campaign_id,
            "target_version": target_version,
            "min_calendar_days": min_calendar_days,
            "min_distinct_observation_days": min_distinct_observation_days,
            "min_machine_profiles": min_machine_profiles,
            "min_account_labels": min_account_labels,
        }
        if campaign_path.is_file():
            campaign = PublicBetaCampaign.model_validate(read_json(campaign_path))
            current = campaign.model_dump(mode="python", exclude={"created_at", "schema_version"})
            if current != expected:
                raise DistillerError(
                    ErrorCode.PROJECT_EXISTS,
                    "Public-beta campaign already exists with different gates",
                    details={"campaign": str(campaign_path)},
                )
            return {
                "ok": True,
                "already_initialized": True,
                "campaign": campaign.model_dump(mode="json"),
                "campaign_path": str(campaign_path),
            }
        campaign = PublicBetaCampaign(
            campaign_id=campaign_id,
            target_version=target_version,
            created_at=datetime.now(UTC),
            min_calendar_days=min_calendar_days,
            min_distinct_observation_days=min_distinct_observation_days,
            min_machine_profiles=min_machine_profiles,
            min_account_labels=min_account_labels,
        )
        atomic_write_json(campaign_path, campaign.model_dump(mode="json"))
        return {
            "ok": True,
            "already_initialized": False,
            "campaign": campaign.model_dump(mode="json"),
            "campaign_path": str(campaign_path),
        }

    def load_campaign(self, campaign_id: str) -> PublicBetaCampaign:
        path = self._campaign_path(campaign_id)
        if not path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                "Public-beta campaign does not exist",
                details={"campaign": str(path)},
            )
        return PublicBetaCampaign.model_validate(read_json(path))

    def _require_open(self, campaign_id: str) -> None:
        if self._freeze_path(campaign_id).is_file():
            raise DistillerError(
                ErrorCode.PUBLIC_BETA_GATE_FAILED,
                "Public-beta campaign is frozen and cannot accept new evidence",
                details={"campaign_id": campaign_id},
            )

    def record_observation(self, observation: PublicBetaObservation) -> Path:
        campaign = self.load_campaign(observation.campaign_id)
        self._require_open(observation.campaign_id)
        if len(observation.account_label_hashes) != len(set(observation.account_label_hashes)):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Observation account label hashes must be unique",
            )
        if observation.compatibility.package_version != campaign.target_version:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Observation package version does not match the campaign target",
                details={
                    "observed": observation.compatibility.package_version,
                    "target": campaign.target_version,
                },
            )
        path = (
            self._campaign_dir(observation.campaign_id)
            / "observations"
            / observation.observed_at.date().isoformat()
            / f"{observation.observation_id}.json"
        )
        if path.exists():
            raise DistillerError(
                ErrorCode.PROJECT_EXISTS,
                "Public-beta observation already exists",
                details={"path": str(path)},
            )
        atomic_write_json(path, observation.model_dump(mode="json"))
        return path

    def observe(
        self,
        *,
        campaign_id: str,
        project: ProjectLayout,
        machine_label: str,
        account_labels: list[str],
        notes: str = "",
    ) -> dict[str, Any]:
        self.load_campaign(campaign_id)
        self._require_open(campaign_id)
        unique_labels = list(dict.fromkeys(account_labels))
        if len(unique_labels) < 2 or len(unique_labels) > 100:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Public-beta observation requires 2-100 unique account labels",
            )
        observed_at = datetime.now(UTC)
        compatibility = capture_compatibility_snapshot(
            project,
            machine_label=machine_label,
            observed_at=observed_at,
        )
        errors: list[str] = []
        queue_result = None
        task_result = None
        backup_result = None
        migration_result = None
        drills = (
            ("queue_resilience", lambda: run_queue_resilience_drill(unique_labels)),
            ("task_recovery", run_task_recovery_drill),
            ("backup_recovery", lambda: run_backup_recovery_drill(project)),
            ("migration_recovery", lambda: run_project_migration_drill(project)),
        )
        results: dict[str, Any] = {}
        for name, operation in drills:
            try:
                results[name] = operation()
            except Exception as exc:
                errors.append(f"{name}:{type(exc).__name__}:{str(exc)[:500]}")
        queue_result = results.get("queue_resilience")
        task_result = results.get("task_recovery")
        backup_result = results.get("backup_recovery")
        migration_result = results.get("migration_recovery")
        required_results = [queue_result, task_result, backup_result, migration_result]
        observation = PublicBetaObservation(
            observation_id=new_run_id(),
            campaign_id=campaign_id,
            observed_at=observed_at,
            account_label_hashes=[stable_id("beta_account_", item) for item in unique_labels],
            compatibility=compatibility,
            queue_resilience=queue_result,
            task_recovery=task_result,
            backup_recovery=backup_result,
            migration_recovery=migration_result,
            ok=(
                compatibility.doctor_ok
                and compatibility.project_validation_ok
                and not errors
                and all(result is not None and bool(result.ok) for result in required_results)
            ),
            errors=errors,
            notes=notes,
        )
        path = self.record_observation(observation)
        return {
            "ok": True,
            "observation": observation.model_dump(mode="json"),
            "observation_path": str(path),
        }

    def record_incident(
        self,
        *,
        campaign_id: str,
        severity: PublicBetaIncidentSeverity,
        summary: str,
    ) -> dict[str, Any]:
        self.load_campaign(campaign_id)
        self._require_open(campaign_id)
        incident = PublicBetaIncident(
            incident_id=new_run_id(),
            campaign_id=campaign_id,
            occurred_at=datetime.now(UTC),
            severity=severity,
            summary=summary,
        )
        path = self._campaign_dir(campaign_id) / "incidents" / f"{incident.incident_id}.json"
        atomic_write_json(path, incident.model_dump(mode="json"))
        return {
            "ok": True,
            "incident": incident.model_dump(mode="json"),
            "incident_path": str(path),
        }

    def _observations(self, campaign_id: str) -> list[PublicBetaObservation]:
        root = self._campaign_dir(campaign_id) / "observations"
        if not root.is_dir():
            return []
        return [
            PublicBetaObservation.model_validate(read_json(path))
            for path in sorted(root.rglob("*.json"))
        ]

    def _incidents(self, campaign_id: str) -> list[PublicBetaIncident]:
        root = self._campaign_dir(campaign_id) / "incidents"
        if not root.is_dir():
            return []
        return [
            PublicBetaIncident.model_validate(read_json(path))
            for path in sorted(root.glob("*.json"))
        ]

    def status(
        self,
        campaign_id: str,
        *,
        evaluated_at: datetime | None = None,
    ) -> PublicBetaStatus:
        campaign = self.load_campaign(campaign_id)
        evaluated_at = evaluated_at or datetime.now(UTC)
        observations = self._observations(campaign_id)
        incidents = self._incidents(campaign_id)
        return _evaluate_public_beta_status(
            campaign,
            observations,
            incidents,
            evaluated_at=evaluated_at,
            installed_version=PACKAGE_VERSION,
        )

    def verify_freeze(self, campaign_id: str) -> PublicBetaFreezeVerification:
        """Recompute and validate a frozen campaign without changing its evidence."""

        return _verify_campaign_directory(
            self._campaign_dir(campaign_id),
            expected_version=PACKAGE_VERSION,
        )

    def bundle(self, campaign_id: str, *, output: Path) -> dict[str, Any]:
        """Create a portable deterministic archive from a verified freeze."""

        return build_public_beta_evidence_bundle(
            self._campaign_dir(campaign_id),
            output,
            expected_version=PACKAGE_VERSION,
        )

    def freeze(
        self,
        campaign_id: str,
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        freeze_path = self._freeze_path(campaign_id)
        if freeze_path.is_file():
            verification = self.verify_freeze(campaign_id)
            if not verification.ok:
                raise DistillerError(
                    ErrorCode.PUBLIC_BETA_GATE_FAILED,
                    "Existing release freeze evidence failed verification",
                    details={
                        "issues": [issue.model_dump(mode="json") for issue in verification.issues]
                    },
                )
            record = PublicBetaFreezeRecord.model_validate(read_json(freeze_path))
            return {
                "ok": True,
                "already_frozen": True,
                "freeze": record.model_dump(mode="json"),
                "freeze_path": str(freeze_path),
                "verification": verification.model_dump(mode="json"),
            }
        status = self.status(campaign_id)
        if not status.eligible_for_freeze:
            raise DistillerError(
                ErrorCode.PUBLIC_BETA_GATE_FAILED,
                "Public-beta evidence is not eligible for release freeze",
                details={"blockers": status.blockers},
            )
        if not confirm:
            raise DistillerError(
                ErrorCode.PUBLIC_BETA_GATE_FAILED,
                "Release freeze requires explicit confirmation",
                details={"required": "confirm=true"},
            )
        campaign = self.load_campaign(campaign_id)
        observations = self._observations(campaign_id)
        incidents = self._incidents(campaign_id)
        evidence_sha256 = sha256_json(_evidence_payload(campaign, observations, incidents))
        record = PublicBetaFreezeRecord(
            campaign_id=campaign_id,
            target_version=campaign.target_version,
            frozen_at=datetime.now(UTC),
            evidence_sha256=evidence_sha256,
            status=status,
            confirmed=True,
        )
        atomic_write_json(freeze_path, record.model_dump(mode="json"))
        verification = self.verify_freeze(campaign_id)
        if not verification.ok:
            freeze_path.unlink(missing_ok=True)
            raise DistillerError(
                ErrorCode.PUBLIC_BETA_GATE_FAILED,
                "New release freeze failed post-write verification",
                details={
                    "issues": [issue.model_dump(mode="json") for issue in verification.issues]
                },
            )
        return {
            "ok": True,
            "already_frozen": False,
            "freeze": record.model_dump(mode="json"),
            "freeze_path": str(freeze_path),
            "verification": verification.model_dump(mode="json"),
        }
