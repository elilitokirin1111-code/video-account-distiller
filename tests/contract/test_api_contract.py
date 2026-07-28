from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from video_account_distiller.api.app import create_app
from video_account_distiller.api.tasks import TaskStore
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

pytestmark = pytest.mark.enable_socket


def _project_path(path: Path) -> str:
    return quote(path.as_posix(), safe="")


def _json(response: Any) -> dict[str, Any]:
    payload: Any = response.json()
    assert isinstance(payload, dict)
    return payload


def _wait_for_task(client: TestClient, task_id: str) -> dict[str, Any]:
    for _ in range(100):
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        payload = _json(response)
        if payload.get("status") in {"completed", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"Task did not finish: {task_id}")


def test_health_openapi_and_missing_task_contract(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert _json(health) == {"status": "ok", "version": "1.0.0"}

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert "/api/tasks" in _json(openapi)["paths"]
        assert "/api/tasks/{task_id}" in _json(openapi)["paths"]

        missing = client.get("/api/tasks/missing")
        assert missing.status_code == 404
        assert _json(missing)["detail"] == "Task not found: missing"


def test_project_init_status_and_validation_contract(tmp_path: Path) -> None:
    root = tmp_path / "API 项目"
    encoded = _project_path(root)

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        initialized = client.post(
            "/api/projects/init",
            json={"path": str(root), "name": "API contract"},
        )
        assert initialized.status_code == 200
        assert _json(initialized)["data"]["already_initialized"] is False

        initialized_again = client.post(
            "/api/projects/init",
            json={"path": str(root), "name": "ignored"},
        )
        assert initialized_again.status_code == 200
        assert _json(initialized_again)["data"]["already_initialized"] is True

        status = client.get(f"/api/projects/{encoded}/status")
        assert status.status_code == 200
        assert _json(status)["ok"] is True

        validation = client.get(f"/api/projects/{encoded}/validate")
        assert validation.status_code == 200
        assert _json(validation)["ok"] is True


def test_collection_dry_run_uses_bounded_default_and_completes_task(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(project.root)

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        submitted = client.post(
            f"/api/projects/{encoded}/collection/analyze",
            params={"dry_run": "true"},
            json={"url": "https://www.douyin.com/user/demo"},
        )
        assert submitted.status_code == 200
        submission = _json(submitted)
        assert submission["status"] == "pending"

        task = _wait_for_task(client, str(submission["task_id"]))
        assert task["status"] == "completed"
        assert task["progress"] == 1.0
        result = task["result"]
        assert result["request"]["provider"] == "tikhub"
        assert result["request"]["count"] == 20
        assert result["request"]["comments_per_video"] == 0
        assert result["provider_calls"]["total_max"] == 3


def test_self_service_workflow_dry_run_reports_local_readiness(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(project.root)

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        submitted = client.post(
            f"/api/projects/{encoded}/workflows/account-distill",
            params={"dry_run": "true"},
            json={
                "url": "https://v.douyin.com/demo/",
                "count": 20,
                "comments_per_video": 10,
                "comment_video_limit": 20,
            },
        )
        assert submitted.status_code == 200
        submission = _json(submitted)
        task = _wait_for_task(client, str(submission["task_id"]))

        assert task["status"] == "completed"
        assert task["progress"] == 1.0
        assert task["task_type"] == "account_distill"
        assert task["stage"] == "completed"
        result = task["result"]
        assert result["request"]["provider"] == "mediacrawler"
        assert result["request"]["comment_video_limit"] == 20
        assert result["workflow_plan"]["media_limit"] == 20
        assert result["workflow_plan"]["external_model_calls"] == 0
        assert result["workflow_plan"]["knowledge_export"] is True
        assert result["diagnostics"]["project"]["initialized"] is True

        invalid = client.post(
            f"/api/projects/{encoded}/workflows/account-distill",
            params={"dry_run": "true"},
            json={
                "url": "https://v.douyin.com/demo/",
                "media_limit": 21,
            },
        )
        assert invalid.status_code == 422

        all_videos = client.post(
            f"/api/projects/{encoded}/workflows/account-distill",
            params={"dry_run": "true"},
            json={
                "url": "https://v.douyin.com/demo/",
                "all_videos": True,
                "comments_per_video": 5,
                "comment_video_limit": 200,
                "max_provider_calls": 5_000,
                "media_limit": 5,
            },
        )
        assert all_videos.status_code == 200
        all_task = _wait_for_task(client, str(_json(all_videos)["task_id"]))
        assert all_task["status"] == "completed"
        assert all_task["result"]["request"]["count"] is None
        assert all_task["result"]["request"]["comment_video_limit"] == 200


def test_task_failure_persists_and_separate_databases_are_isolated(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(project.root)
    task_db = tmp_path / "persistent-tasks.sqlite3"

    with TestClient(create_app(task_db)) as first_client:
        submitted = first_client.post(
            f"/api/projects/{encoded}/collection/analyze",
            json={"url": "https://www.douyin.com/user/demo"},
        )
        submission = _json(submitted)
        task_id = str(submission["task_id"])
        task = _wait_for_task(first_client, task_id)

        assert task["status"] == "failed"
        assert task["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
        assert task["error"]["details"]["next"].startswith("pass --confirm-provider-cost")

    with TestClient(create_app(task_db)) as second_client:
        persisted = second_client.get(f"/api/tasks/{task_id}")
        assert persisted.status_code == 200
        assert _json(persisted)["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
        listed = _json(second_client.get("/api/tasks"))
        assert listed["count"] == 1
        assert listed["tasks"][0]["task_id"] == task_id

    with TestClient(create_app(tmp_path / "isolated.sqlite3")) as isolated_client:
        assert isolated_client.get(f"/api/tasks/{task_id}").status_code == 404


def test_report_listing_and_content_contract(project: ProjectLayout, tmp_path: Path) -> None:
    account_id = "acc_demo"
    report_id = "report_demo"
    report_dir = project.root / "reports" / "accounts" / account_id / report_id
    report_dir.mkdir(parents=True)
    report = {"account_id": account_id, "summary": "healthy"}
    report_dir.joinpath("report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    report_dir.joinpath("report.md").write_text("# 健康报告\n", encoding="utf-8")
    encoded = _project_path(project.root)

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        listed = client.get(f"/api/projects/{encoded}/reports/")
        assert listed.status_code == 200
        assert _json(listed)["data"]["reports"] == [
            f"reports/accounts/{account_id}/{report_id}/report.json"
        ]

        content = client.get(f"/api/projects/{encoded}/reports/accounts/{account_id}/{report_id}/")
        assert content.status_code == 200
        payload = _json(content)
        assert payload["data"] == report
        assert payload["markdown"] == "# 健康报告\n"


def test_interrupted_task_is_recovered_with_stable_retryable_error(tmp_path: Path) -> None:
    path = tmp_path / "tasks.sqlite3"
    first = TaskStore(path)
    first.create("task_interrupted")
    first.update("task_interrupted", status="running")

    recovered = TaskStore(path).get("task_interrupted")

    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["error"] == {
        "code": "E_TASK_INTERRUPTED",
        "message": "Task was interrupted by an API restart",
        "details": {"retryable": True},
    }


def test_growth_and_analysis_context_endpoints(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(normalized_project.root)
    account_id = stable_id("acc_", "douyin", "hotel-demo")

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        growth = client.get(f"/api/projects/{encoded}/accounts/{account_id}/growth")
        assert growth.status_code == 200
        assert _json(growth)["account_id"] == account_id

        context = client.get(
            f"/api/projects/{encoded}/accounts/{account_id}/analysis-context",
            params={"max_video_analyses": 5},
        )
        assert context.status_code == 200
        payload = _json(context)
        assert payload["context_version"] == "1.0.0"
        assert payload["account"]["account_id"] == account_id
        assert payload["analysis_contract"]


def test_openkb_export_and_confirmation_contract(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(normalized_project.root)
    account_id = stable_id("acc_", "douyin", "hotel-demo")

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        exported = client.post(
            f"/api/projects/{encoded}/knowledge/openkb/accounts/{account_id}/export",
            params={"dry_run": "true"},
            json={},
        )
        assert exported.status_code == 200
        export_payload = _json(exported)
        assert export_payload["dry_run"] is True
        assert export_payload["manifest"]["account_id"] == account_id

        sync = client.post(
            f"/api/projects/{encoded}/knowledge/openkb/accounts/{account_id}/sync",
            json={},
        )
        assert sync.status_code == 402
        assert _json(sync)["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"

        query = client.post(
            f"/api/projects/{encoded}/knowledge/openkb/query",
            json={"question": "What changed?"},
        )
        assert query.status_code == 402
        assert _json(query)["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
