from __future__ import annotations

import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models.release import (
    PublicBetaIncidentSeverity,
    PublicBetaObservation,
)
from video_account_distiller.release.audit import (
    audit_release_candidate,
    write_checksum_manifest,
)
from video_account_distiller.release.public_beta import (
    PublicBetaService,
    run_project_migration_drill,
    run_queue_resilience_drill,
    verify_public_beta_evidence,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.version import PACKAGE_VERSION

pytestmark = pytest.mark.enable_socket
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_public_beta_queue_and_migration_drills_are_isolated(
    project: ProjectLayout,
) -> None:
    queue = run_queue_resilience_drill(["hotel-a", "hotel-b", "hotel-c"])
    migration = run_project_migration_drill(project)

    assert queue.ok is True
    assert queue.max_observed_concurrent == 2
    assert queue.completed_count == 3
    assert queue.injected_failure_count == 1
    assert queue.retry_completed is True
    assert queue.failure_isolated is True
    assert queue.database_removed is True
    assert migration.ok is True
    assert migration.backup_verified is True
    assert migration.migration_applied is True
    assert migration.migrated_schema_verified is True
    assert migration.rollback_verified is True
    assert migration.workspace_removed is True


def _record_pilot_days(
    service: PublicBetaService,
    base: PublicBetaObservation,
    *,
    campaign_id: str,
) -> None:
    now = base.observed_at
    for offset in range(1, 7):
        observed_at = now - timedelta(days=offset)
        compatibility = base.compatibility.model_copy(
            update={
                "observed_at": observed_at,
                "machine_profile_id": (
                    "machine_second" if offset == 1 else base.compatibility.machine_profile_id
                ),
            }
        )
        observation = base.model_copy(
            deep=True,
            update={
                "observation_id": f"observation-{campaign_id}-{offset}",
                "campaign_id": campaign_id,
                "observed_at": observed_at,
                "compatibility": compatibility,
            },
        )
        service.record_observation(observation)


def test_public_beta_requires_real_duration_coverage_and_zero_severe_incidents(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    service = PublicBetaService(tmp_path / "evidence")
    initialized = service.initialize(campaign_id="release-pilot")
    assert initialized["already_initialized"] is False
    assert service.initialize(campaign_id="release-pilot")["already_initialized"] is True

    first_result = service.observe(
        campaign_id="release-pilot",
        project=project,
        machine_label="windows-primary",
        account_labels=["account-a", "account-b", "account-c"],
    )
    base = PublicBetaObservation.model_validate(first_result["observation"])
    first_status = service.status("release-pilot")
    assert first_status.eligible_for_freeze is False
    assert "pilot_duration_incomplete" in first_status.blockers
    assert "machine_coverage_incomplete" in first_status.blockers

    _record_pilot_days(service, base, campaign_id="release-pilot")
    ready = service.status(
        "release-pilot",
        evaluated_at=base.observed_at + timedelta(minutes=1),
    )
    assert ready.eligible_for_freeze is True
    assert ready.distinct_observation_days == 7
    assert ready.elapsed_calendar_days == 7
    assert ready.machine_profiles == 2
    assert ready.account_labels == 3

    with pytest.raises(DistillerError) as unconfirmed:
        service.freeze("release-pilot", confirm=False)
    assert unconfirmed.value.code is ErrorCode.PUBLIC_BETA_GATE_FAILED

    frozen = service.freeze("release-pilot", confirm=True)
    assert frozen["already_frozen"] is False
    assert frozen["freeze"]["confirmed"] is True
    assert frozen["verification"]["ok"] is True
    assert service.freeze("release-pilot", confirm=False)["already_frozen"] is True
    with pytest.raises(DistillerError) as immutable:
        service.record_observation(base.model_copy(update={"observation_id": "after-freeze"}))
    assert immutable.value.code is ErrorCode.PUBLIC_BETA_GATE_FAILED

    verified = service.verify_freeze("release-pilot")
    assert verified.ok is True
    assert verified.declared_evidence_sha256 == verified.computed_evidence_sha256

    first_bundle = tmp_path / "public-beta-one.zip"
    second_bundle = tmp_path / "public-beta-two.zip"
    first_result = service.bundle("release-pilot", output=first_bundle)
    second_result = service.bundle("release-pilot", output=second_bundle)
    assert first_result["bundle_sha256"] == second_result["bundle_sha256"]
    assert first_bundle.read_bytes() == second_bundle.read_bytes()
    bundled = verify_public_beta_evidence(first_bundle, expected_version=PACKAGE_VERSION)
    assert bundled.ok is True
    assert bundled.source_kind == "bundle"
    assert bundled.observation_count == 7

    release_audit = audit_release_candidate(
        REPOSITORY_ROOT,
        public_beta_evidence=first_bundle,
        require_public_beta_freeze=True,
    )
    assert release_audit.ok is True
    assert release_audit.public_beta_required is True
    assert release_audit.public_beta_verified is True
    assert release_audit.public_beta_evidence_sha256 == first_result["bundle_sha256"]

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    checksummed_bundle = artifacts / (f"video-account-distiller-public-beta-{PACKAGE_VERSION}.zip")
    shutil.copyfile(first_bundle, checksummed_bundle)
    write_checksum_manifest(artifacts)
    covered_audit = audit_release_candidate(
        REPOSITORY_ROOT,
        artifact_dir=artifacts,
        public_beta_evidence=checksummed_bundle,
        require_public_beta_freeze=True,
    )
    assert covered_audit.public_beta_verified is True
    assert not any(
        issue.code == "public_beta_evidence_not_in_artifacts" for issue in covered_audit.issues
    )
    uncovered_audit = audit_release_candidate(
        REPOSITORY_ROOT,
        artifact_dir=artifacts,
        public_beta_evidence=first_bundle,
        require_public_beta_freeze=True,
    )
    assert any(
        issue.code == "public_beta_evidence_not_in_artifacts" for issue in uncovered_audit.issues
    )

    wrong_version = verify_public_beta_evidence(first_bundle, expected_version="9.9.9")
    assert wrong_version.ok is False
    assert any(
        issue.code == "public_beta_release_version_mismatch" for issue in wrong_version.issues
    )

    tampered_root = tmp_path / "tampered-evidence"
    shutil.copytree(tmp_path / "evidence", tampered_root)
    tampered_observation = next((tampered_root / "release-pilot" / "observations").rglob("*.json"))
    tampered_payload = read_json(tampered_observation)
    tampered_payload["notes"] = "changed after freeze"
    atomic_write_json(tampered_observation, tampered_payload)
    atomic_write_json(tampered_root / "release-pilot" / "untracked.json", {"ok": False})
    tampered_service = PublicBetaService(tampered_root)
    tampered_verification = tampered_service.verify_freeze("release-pilot")
    assert tampered_verification.ok is False
    assert any(
        issue.code == "public_beta_evidence_hash_mismatch" for issue in tampered_verification.issues
    )
    assert any(issue.code == "public_beta_untracked_json" for issue in tampered_verification.issues)
    with pytest.raises(DistillerError) as tampered_freeze:
        tampered_service.freeze("release-pilot", confirm=False)
    assert tampered_freeze.value.code is ErrorCode.PUBLIC_BETA_GATE_FAILED

    status_tampered_root = tmp_path / "status-tampered-evidence"
    shutil.copytree(tmp_path / "evidence", status_tampered_root)
    status_freeze = status_tampered_root / "release-pilot" / "freeze.json"
    status_payload = read_json(status_freeze)
    status_payload["status"]["observation_count"] = 999
    atomic_write_json(status_freeze, status_payload)
    status_verification = PublicBetaService(status_tampered_root).verify_freeze("release-pilot")
    assert status_verification.ok is False
    assert any(issue.code == "public_beta_status_mismatch" for issue in status_verification.issues)

    tampered_bundle = tmp_path / "tampered-bundle.zip"
    with (
        zipfile.ZipFile(first_bundle, mode="r") as source,
        zipfile.ZipFile(tampered_bundle, mode="w") as destination,
    ):
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename.endswith("campaign.json"):
                payload += b" "
            destination.writestr(info, payload)
    tampered_archive_verification = verify_public_beta_evidence(tampered_bundle)
    assert tampered_archive_verification.ok is False
    assert any(
        issue.code == "public_beta_bundle_file_hash_mismatch"
        for issue in tampered_archive_verification.issues
    )

    service.initialize(campaign_id="incident-pilot")
    incident_base = base.model_copy(
        deep=True,
        update={
            "observation_id": "incident-base",
            "campaign_id": "incident-pilot",
        },
    )
    service.record_observation(incident_base)
    _record_pilot_days(service, incident_base, campaign_id="incident-pilot")
    service.record_incident(
        campaign_id="incident-pilot",
        severity=PublicBetaIncidentSeverity.HIGH,
        summary="Injected high-severity release blocker",
    )
    blocked = service.status(
        "incident-pilot",
        evaluated_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert blocked.eligible_for_freeze is False
    assert blocked.high_or_critical_incidents == 1
    assert "high_severity_incidents_present" in blocked.blockers


def test_public_beta_rejects_campaign_gate_drift(tmp_path: Path) -> None:
    service = PublicBetaService(tmp_path / "evidence")
    service.initialize(campaign_id="immutable-config", min_account_labels=3)

    with pytest.raises(DistillerError) as drift:
        service.initialize(campaign_id="immutable-config", min_account_labels=4)
    assert drift.value.code is ErrorCode.PROJECT_EXISTS


def test_public_beta_bundle_rejects_unsafe_archive_members(tmp_path: Path) -> None:
    bundle = tmp_path / "unsafe.zip"
    escaped = tmp_path.parent / f"{tmp_path.name}-escaped.json"
    with zipfile.ZipFile(bundle, mode="w") as archive:
        archive.writestr(f"../{escaped.name}", b"{}")

    verification = verify_public_beta_evidence(bundle)

    assert verification.ok is False
    assert any(issue.code == "public_beta_bundle_unsafe_member" for issue in verification.issues)
    assert not escaped.exists()
