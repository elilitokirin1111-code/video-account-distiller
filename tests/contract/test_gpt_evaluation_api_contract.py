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
from video_account_distiller.config import load_config
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_text

pytestmark = pytest.mark.enable_socket


class EvaluationExecutor:
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
        analysis = {
            "executive_summary": "The evidence supports a bounded account review.",
            "findings": [
                {
                    "classification": "observed_fact",
                    "title": "A normalized account snapshot is available",
                    "statement": "The submitted context contains a normalized account snapshot.",
                    "evidence_refs": ["context://account"],
                    "confidence": "high",
                }
            ],
            "priority_actions": [
                {
                    "priority": 1,
                    "action": "Continue comparable observations.",
                    "rationale": "Growth conclusions require evidence across time.",
                    "evidence_refs": ["context://growth"],
                }
            ],
            "experiments": [],
            "limitations": ["Only submitted local artifacts were reviewed."],
        }
        response = {
            "id": f"resp_eval_{len(self.calls)}",
            "status": "completed",
            "model": "gpt-5.6-terra",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(analysis),
                        }
                    ],
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        }
        return HttpResponse(200, json.dumps(response).encode())


def _enable_cloud(project: ProjectLayout) -> None:
    config = load_config(project.config_path)
    updated = config.model_copy(
        update={"privacy": config.privacy.model_copy(update={"allow_cloud_model_upload": True})}
    )
    atomic_write_text(project.config_path, updated.as_yaml())


def _wait_for_task(client: TestClient, task_id: str) -> dict[str, Any]:
    for _ in range(200):
        response = client.get(f"/api/tasks/{task_id}")
        payload: dict[str, Any] = response.json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"task did not complete: {task_id}")


def test_gpt_evaluation_api_is_preview_bound_ephemeral_and_secret_free(
    normalized_project: ProjectLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    encoded = quote(str(normalized_project.root), safe="")
    suite = {
        "version": "gpt-evaluation-suite-v1",
        "suite_id": "api-regression",
        "description": "API contract suite",
        "max_total_cost_usd": 1.0,
        "stability_threshold": 0.6,
        "cases": [
            {
                "case_id": "health",
                "account_id": account_id,
                "model": "gpt-5.6-terra",
                "template": "account_health",
                "reasoning_effort": "low",
                "max_video_analyses": 5,
                "runs_per_case": 2,
            }
        ],
    }
    preview_body = {"suite": suite, "campaign_id": "api-acceptance"}
    executor = EvaluationExecutor()
    secret = "sk-evaluation-contract-secret"
    app = create_app(tmp_path / "evaluation-tasks.sqlite3")
    app.state.openai_executor = executor

    with TestClient(app) as client:
        preview_response = client.post(
            f"/api/projects/{encoded}/gpt-evaluations/preview",
            json=preview_body,
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert preview["remote_call_performed"] is False
        assert preview["planned_independent_runs"] == 2
        assert not executor.calls

        blocked = client.post(
            f"/api/projects/{encoded}/gpt-evaluations/run",
            json={
                **preview_body,
                "confirmed_preview_hash": preview["preview_hash"],
                "confirm_cloud_upload": False,
                "confirm_cost": False,
                "confirm_independent_paid_runs": False,
            },
        )
        assert blocked.status_code == 402
        assert blocked.json()["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
        assert not executor.calls

        _enable_cloud(normalized_project)
        monkeypatch.setenv("OPENAI_API_KEY", secret)
        submitted = client.post(
            f"/api/projects/{encoded}/gpt-evaluations/run",
            json={
                **preview_body,
                "confirmed_preview_hash": preview["preview_hash"],
                "confirm_cloud_upload": True,
                "confirm_cost": True,
                "confirm_independent_paid_runs": True,
            },
        )
        assert submitted.status_code == 200, submitted.text
        submission = submitted.json()
        assert submission["durable"] is False
        assert submission["retryable"] is False
        task = _wait_for_task(client, submission["task_id"])

    assert task["status"] == "completed", task
    assert task["task_type"] == "gpt_regression_evaluation"
    assert task["result"]["acceptance_status"] == "pass"
    assert task["result"]["counts"]["remote_calls_performed"] == 2
    assert len(executor.calls) == 2
    assert secret not in json.dumps(task)
    for path in tmp_path.glob("evaluation-tasks.sqlite3*"):
        assert secret.encode() not in path.read_bytes()
