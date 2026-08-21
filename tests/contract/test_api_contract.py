from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from video_account_distiller.adapters.collaboration import HttpResponse
from video_account_distiller.api.app import create_app
from video_account_distiller.api.schemas import SampleParams
from video_account_distiller.api.task_jobs import SampleJob
from video_account_distiller.api.tasks import TaskQueueSettings, TaskStore
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
        if payload.get("status") in {"completed", "failed", "cancelled"}:
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
        assert "/api/task-queue" in _json(openapi)["paths"]
        assert "/api/tasks/{task_id}" in _json(openapi)["paths"]
        assert "/api/tasks/{task_id}/cancel" in _json(openapi)["paths"]
        assert "/api/tasks/{task_id}/retry" in _json(openapi)["paths"]
        assert "/api/doctor/task-recovery-drill" in _json(openapi)["paths"]
        assert (
            "/api/projects/{project_path}/analyze/accounts/{account_id}/media/reparse"
            in _json(openapi)["paths"]
        )
        assert (
            "/api/projects/{project_path}/analyze/accounts/{account_id}/media/"
            "reparse-candidates" in _json(openapi)["paths"]
        )

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


def test_weknora_knowledge_base_discovery_uses_unique_ids(
    project: ProjectLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        ok = True
        text = ""

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "data": [
                    {"id": "kb-2", "name": "同名知识库", "type": "document"},
                    {"id": "kb-1", "name": "同名知识库", "type": "document"},
                ]
            }

    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.requests.get",
        lambda *args, **kwargs: Response(),
    )
    encoded = _project_path(project.root)

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        response = client.post(
            f"/api/projects/{encoded}/knowledge/weknora/knowledge-bases",
            json={"base_url": "http://localhost:8080", "api_key": "sk-test"},
        )

    assert response.status_code == 200
    payload = _json(response)
    assert payload["ok"] is True
    assert [item["id"] for item in payload["knowledge_bases"]] == ["kb-1", "kb-2"]


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
        assert task["task_type"] == "collection_analyze"
        assert task["resource_class"] == "provider"
        assert task["durable"] is True
        assert task["retryable"] is True
        result = task["result"]
        assert result["request"]["provider"] == "tikhub"
        assert result["request"]["count"] == 50
        assert result["request"]["comments_per_video"] == 0
        assert result["provider_calls"]["total_max"] == 5


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
        assert task["resource_class"] == "workflow"
        assert task["durable"] is True
        assert task["executed_by"]
        assert task["stage"] == "completed"
        result = task["result"]
        assert result["request"]["provider"] == "mediacrawler"
        assert result["request"]["comment_video_limit"] == 20
        assert result["workflow_plan"]["media_limit"] == 20
        assert result["workflow_plan"]["external_model_calls"] == 0
        assert result["workflow_plan"]["knowledge_export"] is True
        assert result["diagnostics"]["project"]["initialized"] is True

        knowledge_submitted = client.post(
            f"/api/projects/{encoded}/workflows/account-distill",
            params={"dry_run": "true"},
            json={
                "url": "https://v.douyin.com/demo/",
                "count": 20,
                "media_limit": 20,
                "distillation_mode": "knowledge",
                "video_knowledge_provider": "llamacpp",
            },
        )
        assert knowledge_submitted.status_code == 200
        knowledge_task = _wait_for_task(
            client,
            str(_json(knowledge_submitted)["task_id"]),
        )
        assert knowledge_task["status"] == "completed"
        knowledge_plan = knowledge_task["result"]["workflow_plan"]
        assert knowledge_plan["mode"] == "account_video_knowledge"
        assert knowledge_plan["distillation_mode"] == "knowledge"
        assert knowledge_plan["video_knowledge"]["enabled"] is True
        assert "video_knowledge" in knowledge_plan["stages"]
        assert "distill" not in knowledge_plan["stages"]
        assert "report" not in knowledge_plan["stages"]
        assert knowledge_plan["knowledge_export"] is False

        invalid = client.post(
            f"/api/projects/{encoded}/workflows/account-distill",
            params={"dry_run": "true"},
            json={
                "url": "https://v.douyin.com/demo/",
                "media_limit": 20_001,
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
    data_gaps = {"rows": [{"field": "metric.revenue", "availability": "unknown"}]}
    report_dir.joinpath("data-gaps.json").write_text(
        json.dumps(data_gaps),
        encoding="utf-8",
    )
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
        assert payload["data_gaps"] == data_gaps


def test_sample_and_report_use_durable_analysis_queue(
    phase2_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(phase2_project.root)
    account_id = stable_id("acc_", "douyin", "phase2-hotel")

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        sample_submission = _json(
            client.post(
                f"/api/projects/{encoded}/sample/{account_id}",
                params={"dry_run": "true"},
                json={"size": 5},
            )
        )
        sample = _wait_for_task(client, str(sample_submission["task_id"]))

        report_submission = _json(
            client.post(
                f"/api/projects/{encoded}/report/{account_id}",
                params={"dry_run": "true"},
                json={"sample_size": 5},
            )
        )
        report = _wait_for_task(client, str(report_submission["task_id"]))

    assert sample["status"] == "completed"
    assert sample["task_type"] == "sample"
    assert sample["resource_class"] == "analysis"
    assert sample["durable"] is True
    assert report["status"] == "completed"
    assert report["task_type"] == "report"
    assert report["resource_class"] == "analysis"
    assert report["durable"] is True


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


def test_task_queue_status_contract(tmp_path: Path) -> None:
    settings = TaskQueueSettings()
    with TestClient(create_app(tmp_path / "tasks.sqlite3", task_queue_settings=settings)) as client:
        response = client.get("/api/task-queue")

    assert response.status_code == 200
    payload = _json(response)
    assert payload["ok"] is True
    assert payload["limits"]["max_concurrent"] == settings.max_concurrent
    assert payload["limits"]["workflow_concurrency"] == settings.workflow_concurrency
    assert payload["by_status"] == {}


def test_cancelling_task_is_finalized_as_cancelled_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "tasks.sqlite3"
    first = TaskStore(path)
    first.create("task_cancelling")
    first.update("task_cancelling", status="running", progress=0.4)

    cancelling = first.request_cancel("task_cancelling")
    assert cancelling["status"] == "cancelling"
    assert cancelling["cancel_requested"] is True

    recovered = TaskStore(path).get("task_cancelling")
    assert recovered is not None
    assert recovered["status"] == "cancelled"
    assert recovered["progress"] == 0.4


def test_account_distill_task_can_retry_from_persisted_inputs(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    task_db = tmp_path / "tasks.sqlite3"
    app = create_app(task_db)
    with TestClient(app) as client:
        store: TaskStore = app.state.tasks
        store.create(
            "task_retryable",
            initial={
                "task_type": "account_distill",
                "retryable": True,
                "task_metadata": {
                    "project_path": str(project.root),
                    "body": {
                        "url": "https://v.douyin.com/demo/",
                        "count": 20,
                        "comments_per_video": 10,
                        "comment_video_limit": 20,
                    },
                    "dry_run": True,
                },
            },
        )
        store.update(
            "task_retryable",
            status="failed",
            error={
                "code": "E_TASK_INTERRUPTED",
                "message": "interrupted",
                "details": {"retryable": True},
            },
        )

        retried = client.post("/api/tasks/task_retryable/retry")
        assert retried.status_code == 200
        submission = _json(retried)
        assert submission["retried_from"] == "task_retryable"

        task = _wait_for_task(client, str(submission["task_id"]))
        assert task["status"] == "completed"
        assert task["retried_from"] == "task_retryable"
        assert task["result"]["dry_run"] is True
        assert task["result"]["request"]["count"] == 20


def test_account_distill_task_can_retry_with_overrides(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    task_db = tmp_path / "tasks.sqlite3"
    app = create_app(task_db)
    with TestClient(app) as client:
        store: TaskStore = app.state.tasks
        store.create(
            "task_overridable",
            initial={
                "task_type": "account_distill",
                "retryable": True,
                "task_metadata": {
                    "project_path": str(project.root),
                    "body": {
                        "url": "https://v.douyin.com/demo/",
                        "count": 20,
                        "text_provider": "cloud",
                        "cloud_base_url": "https://api.deepseek.com",
                        "cloud_text_model": "deepseek-v4-flash",
                        "knowledge_analysis": {
                            "provider": "bailian",
                            "model": "qwen3.7-plus",
                            "template": "content_strategy",
                            "reasoning_effort": "high",
                            "max_video_analyses": 20,
                            "confirm_cloud_upload": True,
                            "confirm_cost": True,
                        },
                    },
                    "dry_run": True,
                },
            },
        )
        store.update(
            "task_overridable",
            status="failed",
            error={
                "code": "E_ADAPTER_AUTH",
                "message": "quota exhausted",
                "details": {"http_status": 403},
            },
        )

        retried = client.post(
            "/api/tasks/task_overridable/retry",
            json={
                "overrides": {
                    "knowledge_analysis": {
                        "provider": "bailian",
                        "model": "qwen-max",
                        "template": "content_strategy",
                        "reasoning_effort": "high",
                        "max_video_analyses": 20,
                        "confirm_cloud_upload": True,
                        "confirm_cost": True,
                    },
                    "cloud_base_url": "https://ws-demo.maas.aliyuncs.com/compatible-mode/v1",
                    "cloud_text_model": "qwen-max",
                }
            },
        )
        assert retried.status_code == 200
        submission = _json(retried)
        task = _wait_for_task(client, str(submission["task_id"]))
        assert task["status"] == "completed"
        body = task["task_metadata"]["body"]
        assert body["knowledge_analysis"]["model"] == "qwen-max"
        assert body["cloud_base_url"].endswith("/compatible-mode/v1")
        assert body["cloud_text_model"] == "qwen-max"

        # Non-allowlisted fields are rejected before enqueueing.
        rejected = client.post(
            "/api/tasks/task_overridable/retry",
            json={"overrides": {"cloud_api_key": "sk-should-not-be-overridden"}},
        )
        assert rejected.status_code == 422 or (
            rejected.status_code == 200 and not isinstance(_json(rejected).get("task_id"), str)
        )


def test_account_distill_budget_failure_retries_with_automatic_budget(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    task_db = tmp_path / "tasks.sqlite3"
    app = create_app(task_db)
    with TestClient(app) as client:
        store: TaskStore = app.state.tasks
        body = {
            "url": "https://v.douyin.com/demo/",
            "count": 50,
            "comments_per_video": 20,
            "comment_video_limit": 50,
            "max_provider_calls": 100,
        }
        store.create(
            "task_budget_retryable",
            initial={
                "task_type": "account_distill",
                "retryable": True,
                "task_metadata": {
                    "project_path": str(project.root),
                    "body": body,
                    "dry_run": True,
                },
            },
        )
        store.update(
            "task_budget_retryable",
            status="failed",
            error={
                "code": "E_COLLECTION_BUDGET_EXCEEDED",
                "message": "planned calls exceed custom budget",
                "details": {
                    "max_provider_calls": 100,
                    "planned_provider_calls_max": 105,
                },
            },
        )

        retried = client.post("/api/tasks/task_budget_retryable/retry")
        assert retried.status_code == 200
        task = _wait_for_task(client, str(_json(retried)["task_id"]))

        assert task["status"] == "completed"
        assert task["task_metadata"]["body"]["max_provider_calls"] is None
        assert task["result"]["budget"]["max_provider_calls"] is None
        assert task["result"]["budget"]["within_limit"] is True
        assert task["result"]["provider_calls"]["total_max"] == 105


def test_generic_durable_task_can_retry_from_serialized_job(
    phase2_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    job = SampleJob(
        project_path=str(phase2_project.root),
        account_id=account_id,
        body=SampleParams(size=5),
        dry_run=True,
    )
    app = create_app(tmp_path / "tasks.sqlite3")
    store: TaskStore = app.state.tasks
    store.create(
        "task_sample_retryable",
        initial={
            "task_type": "sample",
            "resource_class": "analysis",
            "durable": True,
            "retryable": True,
            "job_payload": job.model_dump(mode="json"),
        },
    )
    store.update(
        "task_sample_retryable",
        status="failed",
        error={
            "code": "E_TASK_INTERRUPTED",
            "message": "interrupted",
            "details": {"retryable": True},
        },
    )

    with TestClient(app) as client:
        retried = client.post("/api/tasks/task_sample_retryable/retry")
        assert retried.status_code == 200
        submission = _json(retried)
        assert submission["retried_from"] == "task_sample_retryable"
        task = _wait_for_task(client, str(submission["task_id"]))

    assert task["status"] == "completed"
    assert task["task_type"] == "sample"
    assert task["result"]["dry_run"] is True


def test_task_cancel_endpoint_is_idempotent(tmp_path: Path) -> None:
    app = create_app(tmp_path / "tasks.sqlite3")
    with TestClient(app) as client:
        store: TaskStore = app.state.tasks
        store.create("task_running")
        store.update("task_running", status="running", progress=0.25)

        first = client.post("/api/tasks/task_running/cancel")
        assert first.status_code == 200
        assert _json(first)["status"] == "cancelling"

        second = client.post("/api/tasks/task_running/cancel")
        assert second.status_code == 200
        assert _json(second)["status"] == "cancelling"


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
        assert payload["context_version"] == "1.1.0"
        assert payload["account"]["account_id"] == account_id
        assert payload["analysis_contract"]


class _MemoryCloudCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, provider: str) -> str | None:
        return self.values.get(provider)

    def set(self, provider: str, credential: str) -> None:
        self.values[provider] = credential

    def delete(self, provider: str) -> bool:
        return self.values.pop(provider, None) is not None


class _OpenAIContractExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout": timeout,
            }
        )
        result = {
            "executive_summary": "账号上下文可用，建议先建立连续观察周期。",
            "findings": [
                {
                    "classification": "observed_fact",
                    "title": "账号记录可用",
                    "statement": "受限上下文包含一个标准化账号快照。",
                    "evidence_refs": ["context://account"],
                    "confidence": "high",
                }
            ],
            "priority_actions": [
                {
                    "priority": 1,
                    "action": "建立连续观察",
                    "rationale": "当前增长上下文尚不足以判断趋势。",
                    "evidence_refs": ["context://growth"],
                }
            ],
            "experiments": [],
            "limitations": ["缺少多个分隔时间点的账号快照。"],
        }
        response = {
            "id": "resp_contract",
            "status": "completed",
            "model": "gpt-5.6-terra",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(result, ensure_ascii=False),
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 80, "output_tokens": 40, "total_tokens": 120},
        }
        return HttpResponse(
            200,
            json.dumps(response, ensure_ascii=False).encode("utf-8"),
        )


def test_cloud_model_settings_and_ephemeral_gpt_analysis_contract(
    normalized_project: ProjectLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = _project_path(normalized_project.root)
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    secret = "sk-contract-temporary-secret"
    executor = _OpenAIContractExecutor()
    task_db = tmp_path / "gpt-tasks.sqlite3"
    app = create_app(task_db)
    app.state.cloud_credentials = _MemoryCloudCredentialStore()
    app.state.openai_executor = executor
    body = {
        "model": "gpt-5.6-terra",
        "template": "account_health",
        "reasoning_effort": "low",
        "max_video_analyses": 5,
        "confirm_cloud_upload": True,
        "confirm_cost": True,
    }

    with TestClient(app) as client:
        settings_path = f"/api/projects/{encoded}/settings/cloud-model"
        settings = client.get(settings_path)
        assert settings.status_code == 200
        assert _json(settings)["allow_cloud_model_upload"] is False
        assert _json(settings)["api_key_configured"] is False

        blocked = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis",
            json=body,
        )
        assert blocked.status_code == 402
        assert _json(blocked)["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
        assert not executor.calls

        enabled = client.put(
            settings_path,
            json={"allow_cloud_model_upload": True},
        )
        assert enabled.status_code == 200
        assert _json(enabled)["allow_cloud_model_upload"] is True
        assert _json(enabled)["api_key_persisted"] is False

        unconfirmed = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis",
            json={**body, "confirm_cost": False},
        )
        assert unconfirmed.status_code == 402
        assert not executor.calls

        preview = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis/preview",
            json=body,
        )
        assert preview.status_code == 200
        preview_payload = _json(preview)
        assert preview_payload["remote_call_performed"] is False
        assert preview_payload["model"] == "gpt-5.6-terra"
        assert preview_payload["cost_preview"]["conservative_maximum_usd"] > 0
        assert preview_payload["request_fingerprints"]["context_hash"]
        assert not executor.calls

        missing_credential = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis",
            json=body,
        )
        assert missing_credential.status_code == 401
        assert _json(missing_credential)["error"]["code"] == "E_ADAPTER_AUTH"
        assert not executor.calls

        monkeypatch.setenv("OPENAI_API_KEY", secret)
        submitted = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis",
            json=body,
        )
        assert submitted.status_code == 200
        submission = _json(submitted)
        assert submission["durable"] is False
        assert submission["retryable"] is False
        task = _wait_for_task(client, str(submission["task_id"]))

    assert task["status"] == "completed"
    assert task["task_type"] == "gpt_account_analysis"
    assert task["resource_class"] == "model"
    assert task["durable"] is False
    assert task["retryable"] is False
    assert secret not in json.dumps(task, ensure_ascii=False)
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["headers"]["Authorization"] == f"Bearer {secret}"
    assert secret not in (call["body"] or b"").decode("utf-8")

    outputs = task["result"]["outputs"]
    assert len(outputs) == 6
    assert task["result"]["knowledge_export"]["document_path"] in outputs
    assert task["result"]["knowledge_export"]["evidence_document_path"] in outputs
    for relative in outputs:
        path = normalized_project.root / relative
        assert path.is_file()
        assert secret not in path.read_text(encoding="utf-8")
    for database_file in tmp_path.glob("gpt-tasks.sqlite3*"):
        assert secret.encode("utf-8") not in database_file.read_bytes()
    audit = task["result"]["audit"]
    assert audit["privacy"]["api_key_source"] == "OPENAI_API_KEY"
    assert audit["response"]["estimated_cost"]["estimated_total_usd"] is not None
    assert task["result"]["evaluation"]["evaluation_version"] == "account-analysis-eval-v2"


def test_cloud_preset_round_trips_into_project_config(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    """Cloud endpoint presets persist in distiller.yaml and never echo the key."""
    from video_account_distiller.config import load_config

    task_db = tmp_path / "preset-tasks.sqlite3"
    app = create_app(task_db)
    app.state.cloud_credentials = _MemoryCloudCredentialStore()
    encoded = quote(str(normalized_project.root), safe="")
    secret = "sk-preset-secret-value"
    preset_path = f"/api/projects/{encoded}/settings/cloud-preset"

    with TestClient(app) as client:
        empty = client.get(preset_path)
        assert empty.status_code == 200
        payload = _json(empty)
        assert payload["ok"] is True
        assert payload["cloud_api_key_configured"] is False
        assert payload["cloud_base_url"] is None

        saved = client.put(
            preset_path,
            json={
                "cloud_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "cloud_api_key": secret,
                "cloud_text_model": "qwen3.7-plus",
                "cloud_vision_model": "qwen-vl-max-latest",
            },
        )
        assert saved.status_code == 200
        saved_payload = _json(saved)
        assert saved_payload["cloud_api_key_configured"] is True
        assert saved_payload["cloud_base_url"] == (
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        assert secret not in json.dumps(saved_payload, ensure_ascii=False)

        config = load_config(normalized_project.config_path)
        assert config.models.cloud_base_url == ("https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert config.models.cloud_api_key == secret
        assert config.models.cloud_text_model == "qwen3.7-plus"
        assert config.models.cloud_vision_model == "qwen-vl-max-latest"

        read_back = client.get(preset_path)
        read_payload = _json(read_back)
        assert read_payload["cloud_api_key_configured"] is True
        assert read_payload["cloud_text_model"] == "qwen3.7-plus"
        assert secret not in json.dumps(read_payload, ensure_ascii=False)

        cleared = client.put(
            preset_path,
            json={
                "cloud_base_url": "",
                "cloud_api_key": "",
                "cloud_text_model": "",
                "cloud_vision_model": "",
            },
        )
        assert cleared.status_code == 200
        assert _json(cleared)["cloud_api_key_configured"] is False
        assert _json(cleared)["cloud_base_url"] is None
        config = load_config(normalized_project.config_path)
        assert config.models.cloud_api_key is None
        assert config.models.cloud_base_url is None

    # The preset API key is stored only in the project-local config, never in
    # the API response bodies or the task database.
    assert secret.encode("utf-8") not in task_db.read_bytes()


class _BailianContractExecutor(_OpenAIContractExecutor):
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout": timeout,
            }
        )
        if method == "GET":
            response = {
                "object": "list",
                "data": [
                    {"id": "qwen3.7-plus", "object": "model"},
                    {"id": "unsupported-model", "object": "model"},
                ],
            }
            return HttpResponse(200, json.dumps(response).encode("utf-8"))
        result = {
            "executive_summary": "账号上下文可用，建议先建立连续观察周期。",
            "findings": [
                {
                    "classification": "observed_fact",
                    "title": "账号记录可用",
                    "statement": "受限上下文包含一个标准化账号快照。",
                    "evidence_refs": ["context://account"],
                    "confidence": "high",
                }
            ],
            "priority_actions": [
                {
                    "priority": 1,
                    "action": "建立连续观察",
                    "rationale": "当前增长上下文尚不足以判断趋势。",
                    "evidence_refs": ["context://growth"],
                }
            ],
            "experiments": [],
            "limitations": ["缺少多个分隔时间点的账号快照。"],
        }
        response = {
            "id": "chatcmpl_bailian_contract",
            "model": "qwen3.7-plus",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(result, ensure_ascii=False),
                    },
                }
            ],
            "usage": {"prompt_tokens": 80, "completion_tokens": 40, "total_tokens": 120},
        }
        return HttpResponse(200, json.dumps(response, ensure_ascii=False).encode("utf-8"))


def test_bailian_credential_is_validated_persisted_and_used_without_request_secret(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(normalized_project.root)
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    secret = "sk-bailian-contract-temporary-secret"
    executor = _BailianContractExecutor()
    app = create_app(tmp_path / "bailian-tasks.sqlite3")
    credentials = _MemoryCloudCredentialStore()
    app.state.cloud_credentials = credentials
    app.state.bailian_executor = executor
    body = {
        "provider": "bailian",
        "model": "qwen3.7-plus",
        "template": "account_health",
        "reasoning_effort": "low",
        "max_video_analyses": 5,
        "confirm_cloud_upload": True,
        "confirm_cost": True,
    }

    with TestClient(app) as client:
        settings_path = f"/api/projects/{encoded}/settings/cloud-model"
        settings = _json(client.get(settings_path))
        assert settings["providers"]["bailian"]["api_key_configured"] is False
        saved = client.put(
            "/api/cloud-model/credentials/bailian",
            json={"api_key": secret},
        )
        assert saved.status_code == 200
        assert _json(saved)["credential_storage"] == "operating_system_keyring"
        assert _json(saved)["models"] == ["qwen3.7-plus"]
        assert credentials.get("bailian") == secret
        configured = _json(client.get(settings_path))["providers"]["bailian"]
        assert configured["api_key_configured"] is True
        assert configured["stored_in_os_keyring"] is True
        assert (
            client.put(
                settings_path,
                json={"allow_cloud_model_upload": True},
            ).status_code
            == 200
        )
        preview = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis/preview",
            json=body,
        )
        assert preview.status_code == 200
        preview_payload = _json(preview)
        assert preview_payload["provider"] == "bailian"
        assert preview_payload["cost_preview"]["currency"] == "CNY"
        assert preview_payload["cost_preview"]["conservative_maximum_cny"] > 0

        submitted = client.post(
            f"/api/projects/{encoded}/accounts/{account_id}/gpt-analysis",
            json=body,
        )
        assert submitted.status_code == 200
        task = _wait_for_task(client, str(_json(submitted)["task_id"]))
        deleted = client.delete("/api/cloud-model/credentials/bailian")
        assert deleted.status_code == 200
        assert _json(deleted)["deleted"] is True

    assert task["status"] == "completed"
    assert credentials.get("bailian") is None
    assert len(executor.calls) == 2
    call = executor.calls[1]
    assert call["url"].endswith("/compatible-mode/v1/chat/completions")
    assert call["headers"]["Authorization"] == f"Bearer {secret}"
    assert secret not in (call["body"] or b"").decode("utf-8")
    audit = task["result"]["audit"]
    assert audit["privacy"]["api_key_source"] == "operating_system_keyring"
    assert audit["response"]["estimated_cost"]["currency"] == "CNY"
    assert audit["response"]["estimated_cost"]["estimated_total_cny"] is not None
    for database_file in tmp_path.glob("bailian-tasks.sqlite3*"):
        assert secret.encode("utf-8") not in database_file.read_bytes()


def test_local_knowledge_export_replaces_openkb_routes(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(normalized_project.root)
    account_id = stable_id("acc_", "douyin", "hotel-demo")

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        exported = client.post(
            f"/api/projects/{encoded}/knowledge/local/accounts/{account_id}/export",
            params={"dry_run": "true"},
            json={},
        )
        assert exported.status_code == 200
        export_payload = _json(exported)
        assert export_payload["dry_run"] is True
        assert export_payload["manifest"]["account_id"] == account_id

        assert export_payload["document_path"].startswith("knowledge-outbox/local/")

        retired = client.post(
            f"/api/projects/{encoded}/knowledge/openkb/accounts/{account_id}/export",
            params={"dry_run": "true"},
            json={},
        )
        assert retired.status_code == 404


def test_account_video_knowledge_route_enqueues_durable_batch_preview(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    encoded = _project_path(normalized_project.root)
    account_id = stable_id("acc_", "douyin", "hotel-demo")

    with TestClient(create_app(tmp_path / "video-knowledge-tasks.sqlite3")) as client:
        submitted = client.post(
            (f"/api/projects/{encoded}/knowledge/local/accounts/{account_id}/distill-videos"),
            params={"dry_run": "true"},
            json={"provider": "none"},
        )
        assert submitted.status_code == 200
        submitted_payload = _json(submitted)
        assert submitted_payload["resource_class"] == "model"
        assert submitted_payload["durable"] is True

        task = _wait_for_task(client, str(submitted_payload["task_id"]))

    assert task["status"] == "completed"
    assert task["result"]["dry_run"] is True
    assert task["result"]["plan"]["document_shape"] == "one_markdown_per_video"
