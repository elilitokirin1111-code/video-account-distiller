from __future__ import annotations

import json
from typing import Any

import pytest

from video_account_distiller.adapters.collaboration import HttpResponse
from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import (
    GptAccountAnalysis,
    GptAnalysisOptions,
    OpenAIModel,
    OpenAIResponsesProvider,
    ReasoningEffort,
    RemoteAccountAnalysisService,
)
from video_account_distiller.insights.gpt_analysis import GPT_ANALYSIS_VERSION, ProviderAnalysis
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_text, read_json


def _analysis(evidence_ref: str = "context://account") -> GptAccountAnalysis:
    return GptAccountAnalysis.model_validate(
        {
            "executive_summary": "账号已有可验证的内容基础，但仍需补足观察周期。",
            "findings": [
                {
                    "classification": "observed_fact",
                    "title": "账号资料可用",
                    "statement": "当前上下文包含账号公开快照。",
                    "evidence_refs": [evidence_ref],
                    "confidence": "high",
                }
            ],
            "priority_actions": [
                {
                    "priority": 1,
                    "action": "建立连续观察周期",
                    "rationale": "增长判断需要多个分隔时间点。",
                    "evidence_refs": ["context://growth"],
                }
            ],
            "experiments": [
                {
                    "hypothesis": "连续发布同一主题有助于形成可比较样本。",
                    "action": "连续四周每周发布两条同主题作品。",
                    "primary_metric": "engagement_rate_by_view",
                    "observation_window": "4 weeks",
                    "evidence_refs": ["context://data-availability"],
                }
            ],
            "limitations": ["缺少多个分隔时间点的账号快照。"],
        }
    )


class RecordingExecutor:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
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
        return HttpResponse(
            200,
            json.dumps(self.response, ensure_ascii=False).encode("utf-8"),
        )


class RecordingProvider:
    provider_name = "fake_openai"
    model_name = "gpt-5.6-terra"

    def __init__(self, analysis: GptAccountAnalysis) -> None:
        self.analysis = analysis
        self.contexts: list[dict[str, Any]] = []

    def analyze(self, *, instructions: str, context_json: str) -> ProviderAnalysis:
        assert "Evidence allowlist" in instructions
        context: Any = json.loads(context_json)
        assert isinstance(context, dict)
        self.contexts.append(context)
        return ProviderAnalysis(
            response_id="resp_test",
            model=self.model_name,
            status="completed",
            analysis=self.analysis,
            usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )


def _enable_cloud(project: ProjectLayout) -> None:
    config = load_config(project.config_path)
    updated = config.model_copy(
        update={"privacy": config.privacy.model_copy(update={"allow_cloud_model_upload": True})}
    )
    atomic_write_text(project.config_path, updated.as_yaml())


def test_openai_responses_provider_uses_strict_schema_and_store_false() -> None:
    expected = _analysis()
    response = {
        "id": "resp_123",
        "status": "completed",
        "model": "gpt-5.6-terra",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(expected.model_dump(mode="json"), ensure_ascii=False),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 10},
        },
    }
    executor = RecordingExecutor(response)
    provider = OpenAIResponsesProvider(
        model=OpenAIModel.TERRA,
        reasoning_effort=ReasoningEffort.LOW,
        executor=executor,
        credential_loader=lambda: "sk-temporary-secret",
    )

    result = provider.analyze(
        instructions="Analyze with evidence.",
        context_json='{"account":{"account_id":"acc_test"}}',
    )

    assert result.analysis == expected
    assert result.response_id == "resp_123"
    assert result.usage["input_tokens_details"]["cached_tokens"] == 20
    call = executor.calls[0]
    assert call["url"] == "https://api.openai.com/v1/responses"
    assert call["headers"]["Authorization"] == "Bearer sk-temporary-secret"
    payload: Any = json.loads(call["body"])
    assert payload["model"] == "gpt-5.6-terra"
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["additionalProperties"] is False
    assert "sk-temporary-secret" not in call["body"].decode("utf-8")


def test_remote_analysis_requires_project_and_per_run_confirmations(
    normalized_project: ProjectLayout,
) -> None:
    provider = RecordingProvider(_analysis())
    service = RemoteAccountAnalysisService(normalized_project, provider)
    options = GptAnalysisOptions(
        confirm_cloud_upload=True,
        confirm_cost=True,
    )

    with pytest.raises(DistillerError) as disabled:
        service.analyze(account_id="acc_missing", options=options)
    assert disabled.value.code is ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED
    assert not provider.contexts

    _enable_cloud(normalized_project)
    with pytest.raises(DistillerError) as unconfirmed:
        service.analyze(
            account_id="acc_missing",
            options=GptAnalysisOptions(confirm_cloud_upload=True),
        )
    assert unconfirmed.value.code is ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED
    assert not provider.contexts


def test_remote_analysis_is_redacted_audited_and_idempotent(
    normalized_project: ProjectLayout,
) -> None:
    _enable_cloud(normalized_project)
    provider = RecordingProvider(_analysis())
    service = RemoteAccountAnalysisService(normalized_project, provider)
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    options = GptAnalysisOptions(
        confirm_cloud_upload=True,
        confirm_cost=True,
    )

    preview = RemoteAccountAnalysisService.preview(
        normalized_project,
        account_id=account_id,
        options=options,
    )
    first = service.analyze(account_id=account_id, options=options)
    second = service.analyze(account_id=account_id, options=options)

    assert preview["remote_call_performed"] is False
    assert preview["cost_preview"]["conservative_maximum_usd"] > 0
    assert preview["data_scope"]["raw_comments_included"] is False
    assert first["already_generated"] is False
    assert second["already_generated"] is True
    assert first["analysis"]["analysis_id"] == stable_id(
        "gpta_",
        account_id,
        GPT_ANALYSIS_VERSION,
        options.model.value,
        options.template.value,
        options.reasoning_effort.value,
        preview["request_fingerprints"]["context_hash"],
        preview["request_fingerprints"]["prompt_hash"],
    )
    assert len(provider.contexts) == 1
    uploaded = provider.contexts[0]
    uploaded_text = json.dumps(uploaded, ensure_ascii=False)
    for key in (
        "platform_account_id",
        "profile_url",
        "raw_hash",
        "source_file",
        "source_row",
    ):
        assert f'"{key}"' not in uploaded_text
    assert uploaded["evidence_catalog"]

    analysis_path = normalized_project.root / first["outputs"][0]
    audit_path = normalized_project.root / first["outputs"][1]
    evaluation_path = normalized_project.root / first["outputs"][2]
    report_path = normalized_project.root / first["outputs"][3]
    assert analysis_path.is_file()
    assert audit_path.is_file()
    assert evaluation_path.is_file()
    assert report_path.is_file()
    audit: Any = read_json(audit_path)
    assert audit["request"]["store"] is False
    assert audit["privacy"]["api_key_persisted"] is False
    assert audit["privacy"]["api_key_source"] == "OPENAI_API_KEY"
    assert audit["privacy"]["raw_response_persisted"] is False
    assert audit["response"]["response_id"] == "resp_test"
    assert audit["response"]["estimated_cost"]["estimated_total_usd"] == 0.001
    evaluation: Any = read_json(evaluation_path)
    statuses = {item["id"]: item["status"] for item in evaluation["checks"]}
    assert statuses["citation_completeness"] == "pass"
    assert statuses["evidence_allowlist_integrity"] == "pass"
    assert statuses["conclusion_stability"] == "insufficient_runs"
    assert statuses["derived_analysis_boundary"] == "pass"
    assert "sk-" not in audit_path.read_text(encoding="utf-8")


def test_remote_analysis_rejects_invented_evidence_refs(
    normalized_project: ProjectLayout,
) -> None:
    _enable_cloud(normalized_project)
    provider = RecordingProvider(_analysis("invented://evidence"))
    service = RemoteAccountAnalysisService(normalized_project, provider)
    account_id = stable_id("acc_", "douyin", "hotel-demo")

    with pytest.raises(DistillerError) as invalid:
        service.analyze(
            account_id=account_id,
            options=GptAnalysisOptions(
                confirm_cloud_upload=True,
                confirm_cost=True,
            ),
        )

    assert invalid.value.code is ErrorCode.MODEL_SCHEMA_INVALID
    assert invalid.value.details["invalid_evidence_refs"] == ["invented://evidence"]
