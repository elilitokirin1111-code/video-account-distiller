from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.models import (
    OpenKBAddResponse,
    OpenKBFileResult,
    OpenKBInitResponse,
    OpenKBQueryResponse,
    OpenKBRemoveResponse,
    OpenKBStatusResponse,
    OpenKBTarget,
)
from video_account_distiller.knowledge.service import OpenKBIntegrationService
from video_account_distiller.reports import ReportService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json


class FakeOpenKBClient:
    def __init__(self) -> None:
        self.target = OpenKBTarget(
            base_url="http://127.0.0.1:7566",
            kb="distiller-tests",
        )
        self.token_configured = False
        self.calls: list[tuple[str, str | None]] = []

    def init_kb(self) -> OpenKBInitResponse:
        self.calls.append(("init", None))
        return OpenKBInitResponse(kb=self.target.kb, created=True)

    def add_document(self, path: Path, *, payload_hash: str) -> OpenKBAddResponse:
        self.calls.append(("add", payload_hash))
        return OpenKBAddResponse(
            kb=self.target.kb,
            files=[
                OpenKBFileResult(
                    original_name=path.name,
                    saved_path=f"raw/{path.name}",
                    status="added",
                )
            ],
            added_count=1,
        )

    def remove_document(self, identifier: str) -> OpenKBRemoveResponse:
        self.calls.append(("remove", identifier))
        return OpenKBRemoveResponse(status="removed", name=identifier)

    def status(self) -> OpenKBStatusResponse:
        self.calls.append(("status", None))
        return OpenKBStatusResponse(raw_count=1, total_indexed=1)

    def query(self, question: str, *, save: bool = False) -> OpenKBQueryResponse:
        self.calls.append(("query", question))
        return OpenKBQueryResponse(answer="grounded answer", saved_path=None)


def test_openkb_sync_is_idempotent_and_replaces_changed_document(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    report_result = ReportService(phase4_project).generate_account_health(account_id=account_id)
    client = FakeOpenKBClient()
    service = OpenKBIntegrationService(phase4_project, client)  # type: ignore[arg-type]

    first = service.sync_account(
        account_id=account_id,
        confirm_model_processing=True,
    )
    assert first["status"] == "synced"
    assert [call[0] for call in client.calls] == ["init", "add"]

    second = service.sync_account(
        account_id=account_id,
        confirm_model_processing=True,
    )
    assert second["status"] == "skipped"
    assert [call[0] for call in client.calls] == ["init", "add"]

    other_client = FakeOpenKBClient()
    other_client.target = other_client.target.model_copy(update={"kb": "another-target"})
    other_service = OpenKBIntegrationService(phase4_project, other_client)  # type: ignore[arg-type]
    target_change = other_service.sync_account(
        account_id=account_id,
        confirm_model_processing=False,
        dry_run=True,
    )
    assert target_change["would_upload"] is True
    assert target_change["would_remove_previous"] is False
    assert other_client.calls == []

    report_path = phase4_project.root / report_result["outputs"][0]
    report = read_json(report_path)
    report["warnings"] = [*report.get("warnings", []), "knowledge-refresh"]
    atomic_write_json(report_path, report)
    third = service.sync_account(
        account_id=account_id,
        confirm_model_processing=True,
    )

    assert third["status"] == "synced"
    assert [call[0] for call in client.calls] == ["init", "add", "init", "remove", "add"]
    assert isinstance(first["sync"], dict)
    assert isinstance(third["sync"], dict)
    assert third["sync"]["payload_hash"] != first["sync"]["payload_hash"]


def test_openkb_model_work_requires_confirmation(
    normalized_project: ProjectLayout,
) -> None:
    client = FakeOpenKBClient()
    service = OpenKBIntegrationService(normalized_project, client)  # type: ignore[arg-type]

    with pytest.raises(DistillerError) as sync_exc:
        service.sync_account(
            account_id=stable_id("acc_", "douyin", "hotel-demo"),
            confirm_model_processing=False,
        )
    assert sync_exc.value.code is ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED
    assert client.calls == []

    with pytest.raises(DistillerError) as query_exc:
        service.query(question="What changed?", confirm_model_processing=False)
    assert query_exc.value.code is ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED
    assert client.calls == []


def test_openkb_query_is_marked_derived(
    normalized_project: ProjectLayout,
) -> None:
    client = FakeOpenKBClient()
    service = OpenKBIntegrationService(normalized_project, client)  # type: ignore[arg-type]

    result = service.query(
        question="What changed?",
        confirm_model_processing=True,
    )

    assert result["answer"] == "grounded answer"
    assert result["authoritative"] is False
    assert result["analysis_contract"]
