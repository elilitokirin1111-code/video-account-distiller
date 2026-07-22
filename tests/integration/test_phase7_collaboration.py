from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from video_account_distiller.collaboration import (
    BatchService,
    CollaborationService,
    SnapshotScheduleService,
    TeamConfigService,
)
from video_account_distiller.models import (
    AdapterReadResult,
    AdapterWriteResult,
    AuthorizationGrant,
    AuthorizedExportManifest,
    BatchManifest,
    BatchTask,
    ConnectorKind,
    Platform,
    Publication,
    SnapshotPlanItem,
)
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.io import atomic_write_json
from video_account_distiller.validation import validate_project


def _grant() -> AuthorizationGrant:
    return AuthorizationGrant.model_validate(
        {
            "grant_id": "grant-export",
            "connector": ConnectorKind.AUTHORIZED_EXPORT,
            "confirmed_by": "owner",
            "confirmed_at": "2026-07-20T00:00:00Z",
            "scopes": ["read"],
            "source_reference": "user-provided platform export",
        }
    )


class StubAdapter:
    connector_kind = ConnectorKind.FEISHU_BITABLE
    connector_id = "stub-table"

    def __init__(self) -> None:
        self.authorization = AuthorizationGrant.model_validate(
            {
                "grant_id": "grant-stub",
                "connector": self.connector_kind,
                "confirmed_by": "owner",
                "confirmed_at": "2026-07-20T00:00:00Z",
                "scopes": ["read", "write"],
                "source_reference": "bitable:stub-table",
            }
        )
        self.write_calls = 0

    def read_records(self) -> AdapterReadResult:
        return AdapterReadResult(
            connector=self.connector_kind,
            connector_id=self.connector_id,
            source_reference="stub:hotel-accounts",
            fetched_at=datetime(2026, 7, 22, tzinfo=UTC),
            records=[
                {
                    "platform_account_id": "remote-hotel",
                    "display_name": "Remote Hotel",
                    "snapshot_at": "2026-07-22T00:00:00Z",
                }
            ],
            raw_pages=[{"records": [{"platform_account_id": "remote-hotel"}]}],
        )

    def append_records(self, records: list[dict[str, Any]]) -> AdapterWriteResult:
        self.write_calls += 1
        return AdapterWriteResult(
            connector=self.connector_kind,
            connector_id=self.connector_id,
            target_reference="stub:hotel-accounts",
            written_at=datetime(2026, 7, 22, tzinfo=UTC),
            requested_rows=len(records),
            accepted_rows=len(records),
        )


def _authorized_manifest(tmp_path: Path, fixtures_dir: Path) -> Path:
    data = fixtures_dir / "normal" / "accounts.csv"
    manifest = AuthorizedExportManifest(
        entity="accounts",
        platform=Platform.DOUYIN,
        data_file=str(data),
        data_sha256=sha256_file(data),
        exported_at=datetime(2026, 7, 20, tzinfo=UTC),
        authorization=_grant(),
    )
    path = tmp_path / "authorized-export.json"
    atomic_write_json(path, manifest.model_dump(mode="json"))
    return path


def test_authorized_export_team_batch_and_status_are_traceable(
    project: ProjectLayout, fixtures_dir: Path, tmp_path: Path
) -> None:
    manifest = _authorized_manifest(tmp_path, fixtures_dir)
    imported = CollaborationService(project).import_authorized_export(manifest_path=manifest)
    NormalizationService(project).normalize()

    team, existed = TeamConfigService(project).initialize(
        owner_id="owner-1", owner_name="Hotel Operator"
    )
    batch_path = tmp_path / "batch.json"
    atomic_write_json(
        batch_path,
        BatchManifest(
            batch_id="batch-phase7",
            tasks=[BatchTask(task_id="schedule", operation="snapshot-plan")],
        ).model_dump(mode="json"),
    )
    batch = BatchService(project).run(manifest_path=batch_path)

    assert imported["quality"]["stats"]["accepted_rows"] == 1
    assert imported["manifest_path"].startswith("raw/authorized-manifests/")
    assert existed is False
    assert team.members[0].role.value == "owner"
    assert batch.tasks[0].status == "success"
    assert batch.artifact_path == ("collaboration/batches/batch-phase7/batch-result.json")
    status = project_status(project)
    assert status["collaboration"]["batch_results"] == 1
    assert status["collaboration"]["team_configured"] is True
    validation = validate_project(project)
    assert validation.error_count == 0
    assert validation.stats["phase7_artifacts"] >= 2


def test_snapshot_schedule_marks_due_and_dry_run_does_not_write(project: ProjectLayout) -> None:
    published_at = datetime.now(UTC) - timedelta(hours=2)
    publication = Publication(
        publication_id="pub_phase7",
        candidate_id="cand_phase7",
        account_id="acc_phase7",
        video_id="vid_phase7",
        published_at=published_at,
        platform=Platform.DOUYIN,
        snapshot_plan=[SnapshotPlanItem(label="t1h", target_age_hours=1, status="planned")],
        created_at=published_at,
        run_id="run_phase7",
        input_hash="0" * 64,
    )
    publication_path = (
        project.root / "publications" / publication.publication_id / "publication.json"
    )
    atomic_write_json(publication_path, publication.model_dump(mode="json"))

    result = SnapshotScheduleService(project).plan(dry_run=True)

    assert result.tasks[0].status == "due"
    assert not (project.root / "collaboration" / "schedules" / "snapshot-plan.json").exists()
    SnapshotScheduleService(project).plan()
    assert (project.root / "collaboration" / "schedules" / "snapshot-plan.json").is_file()


def test_collaboration_pull_and_push_preserve_raw_and_are_idempotent(
    project: ProjectLayout,
) -> None:
    adapter = StubAdapter()
    service = CollaborationService(project)

    pulled = service.pull(adapter=adapter, entity="accounts", platform=Platform.DOUYIN)
    repeated_pull = service.pull(adapter=adapter, entity="accounts", platform=Platform.DOUYIN)
    NormalizationService(project).normalize()
    pushed = service.push(adapter=adapter, entity="accounts")
    repeated_push = service.push(adapter=adapter, entity="accounts")

    assert pulled["sync"]["row_count"] == 1
    assert repeated_pull["already_synced"] is True
    assert list((project.root / "raw" / "collaboration").glob("*/*.json"))
    assert pushed["adapter_result"]["accepted_rows"] == 1
    assert repeated_push["already_synced"] is True
    assert adapter.write_calls == 1
    assert validate_project(project).error_count == 0
