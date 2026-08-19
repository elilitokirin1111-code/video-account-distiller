from __future__ import annotations

import json
from typing import Any

import pytest

from video_account_distiller.adapters.collaboration import HttpResponse
from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import (
    AnalysisProviderKind,
    BailianChatCompletionsProvider,
    BailianModel,
    DeepSeekChatCompletionsProvider,
    DeepSeekModel,
    GptAccountAnalysis,
    GptAnalysisOptions,
    OpenAIModel,
    OpenAIResponsesProvider,
    ReasoningEffort,
    RemoteAccountAnalysisService,
    render_account_learning_report,
)
from video_account_distiller.insights.gpt_analysis import GPT_ANALYSIS_VERSION, ProviderAnalysis
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_text, read_json


@pytest.fixture(autouse=True)
def _isolate_cloud_base_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the host machine's cloud endpoint environment."""
    for name in ("DASHSCOPE_BASE_URL", "DEEPSEEK_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


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
            "imitation_playbooks": [
                {
                    "title": "把连续主题做成可比较系列",
                    "learned_insight": "系列化的价值不是重复，而是减少变量并积累观众预期。",
                    "why_it_works": "相近主题与结构让账号更容易识别真正影响表现的变化。",
                    "copy_this": ["固定内容母题", "每次只替换一个关键变量"],
                    "do_not_copy": ["照搬他人标题和场景"],
                    "adaptation_steps": ["选择一个高相关母题", "连续制作三组单变量内容"],
                    "suitable_for": ["需要形成稳定栏目但样本不足的账号"],
                    "evidence_refs": [evidence_ref],
                    "confidence": "medium",
                }
            ],
            "creative_extensions": [
                {
                    "title": "同一服务的三种住客视角",
                    "derived_from": "连续主题可形成可比较样本",
                    "concept": "围绕同一服务分别用首次入住、亲子和商务住客视角表达。",
                    "execution": ["保持开头结构一致", "只替换人物需求和冲突"],
                    "trend_relevance": "evergreen_extension",
                    "risk_or_boundary": "不能把角色设定包装成真实住客证言。",
                    "evidence_refs": [evidence_ref],
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
            "knowledge_cards": [
                {
                    "title": "把连续主题当作待验证的稳定性机制",
                    "claim": "同一主题的连续发布应通过对照实验验证，而不是直接视为增长规则。",
                    "knowledge_type": "experimental_rule",
                    "mechanism": "连续主题减少内容变量，有助于区分主题机制与随机曝光。",
                    "competing_explanations": ["表现变化也可能来自发布时间或平台分发波动。"],
                    "falsifier": "三组同主题对照仍无稳定差异时撤销该命题。",
                    "decision": "先做三组单变量配对实验，再决定是否进入团队模板。",
                    "scope": ["当前账号", "同一内容支柱"],
                    "boundary_conditions": ["需补齐可比较的播放或互动效率指标"],
                    "tradeoff": "降低短期选题多样性，以换取更清晰的学习信号。",
                    "success_condition": "三组实验中至少两组目标指标高于对照。",
                    "stop_condition": "连续三组未优于账号基线即停止。",
                    "target_metric": "engagement_rate_by_view",
                    "maturity_level": 3,
                    "evidence_refs": [evidence_ref],
                    "confidence": "medium",
                }
            ],
            "limitations": ["缺少多个分隔时间点的账号快照。"],
        }
    )


def test_learning_report_prioritizes_transferable_playbooks_and_creative_extensions() -> None:
    report = render_account_learning_report({"result": _analysis().model_dump(mode="json")})

    assert "账号运营学习报告" in report
    assert "可模仿打法" in report
    assert "把连续主题做成可比较系列" in report
    assert "灵感与延伸创意" in report
    assert "同一服务的三种住客视角" in report
    assert "Evidence" not in report
    assert "证据与严谨分析附录" not in report


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
    provider_name = "fake_deepseek"
    model_name = "deepseek-v4-flash"

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


def test_bailian_provider_uses_json_mode_and_environment_only_credential() -> None:
    expected = _analysis()
    response = {
        "id": "chatcmpl_bailian_123",
        "model": "qwen3.7-plus",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(expected.model_dump(mode="json"), ensure_ascii=False),
                },
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 60,
            "total_tokens": 180,
            "prompt_tokens_details": {"cached_tokens": 20},
        },
    }
    executor = RecordingExecutor(response)
    provider = BailianChatCompletionsProvider(
        model=BailianModel.QWEN_3_7_PLUS,
        reasoning_effort=ReasoningEffort.LOW,
        executor=executor,
        credential_loader=lambda: "sk-bailian-temporary-secret",
    )

    result = provider.analyze(
        instructions="Analyze with evidence.",
        context_json='{"account":{"account_id":"acc_test"}}',
    )

    assert result.analysis == expected
    assert result.response_id == "chatcmpl_bailian_123"
    assert result.usage == {
        "input_tokens": 120,
        "output_tokens": 60,
        "total_tokens": 180,
        "input_tokens_details": {"cached_tokens": 20},
    }
    call = executor.calls[0]
    assert call["url"] == ("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
    assert call["headers"]["Authorization"] == "Bearer sk-bailian-temporary-secret"
    payload: Any = json.loads(call["body"])
    assert payload["model"] == "qwen3.7-plus"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["enable_thinking"] is True
    assert payload["max_tokens"] == 16_384
    assert "JSON Schema" in payload["messages"][0]["content"]
    assert "sk-bailian-temporary-secret" not in call["body"].decode("utf-8")


def test_bailian_provider_uses_larger_output_budget_for_reasoning_models() -> None:
    """Long-context reasoning models must not truncate the full JSON analysis."""
    expected = _analysis()
    response = {
        "id": "chatcmpl_bailian_16384",
        "model": "qwen3.8-max",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(expected.model_dump(mode="json"), ensure_ascii=False),
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 60, "total_tokens": 160},
    }
    executor = RecordingExecutor(response)
    provider = BailianChatCompletionsProvider(
        model=BailianModel.QWEN_3_8_MAX,
        reasoning_effort=ReasoningEffort.HIGH,
        executor=executor,
        credential_loader=lambda: "sk-bailian-temporary-secret",
    )

    result = provider.analyze(
        instructions="Analyze with evidence.",
        context_json='{"account":{"account_id":"acc_test"}}',
    )

    assert result.analysis == expected
    payload: Any = json.loads(executor.calls[0]["body"])
    assert payload["max_tokens"] == 16_384


def test_bailian_provider_reports_truncated_completion_readably() -> None:
    """A length-truncated response must surface as a readable, actionable error."""
    response = {
        "id": "chatcmpl_bailian_truncated",
        "model": "qwen3.8-max",
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": '{"executive_summary": "unfinished...',
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 8_000, "total_tokens": 8_100},
    }
    executor = RecordingExecutor(response)
    provider = BailianChatCompletionsProvider(
        model=BailianModel.QWEN_3_8_MAX,
        reasoning_effort=ReasoningEffort.HIGH,
        executor=executor,
        credential_loader=lambda: "sk-bailian-temporary-secret",
    )

    with pytest.raises(DistillerError) as exc:
        provider.analyze(
            instructions="Analyze with evidence.",
            context_json='{"account":{"account_id":"acc_test"}}',
        )

    assert exc.value.code is ErrorCode.MODEL_SCHEMA_INVALID
    assert "truncated" in exc.value.message
    assert exc.value.details["finish_reason"] == "length"
    assert "qwen3.8-max" in exc.value.details["hint"]


def test_bailian_provider_attaches_validation_field_errors() -> None:
    """Local schema failures must name the offending field for diagnosis."""
    response = {
        "id": "chatcmpl_bailian_badfield",
        "model": "qwen3.8-max",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "executive_summary": "x",
                            "findings": [],
                            "priority_actions": [
                                {
                                    "priority": 9,
                                    "action": "a",
                                    "rationale": "r",
                                    "evidence_refs": ["context://account"],
                                }
                            ],
                            "experiments": [],
                            "limitations": ["l"],
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    executor = RecordingExecutor(response)
    provider = BailianChatCompletionsProvider(
        model=BailianModel.QWEN_3_8_MAX,
        reasoning_effort=ReasoningEffort.HIGH,
        executor=executor,
        credential_loader=lambda: "sk-bailian-temporary-secret",
    )

    with pytest.raises(DistillerError) as exc:
        provider.analyze(
            instructions="Analyze with evidence.",
            context_json='{"account":{"account_id":"acc_test"}}',
        )

    assert exc.value.code is ErrorCode.MODEL_SCHEMA_INVALID
    locations = [item["loc"] for item in exc.value.details["validation_errors"]]
    assert any("priority" in location for location in locations)


def test_deepseek_v4_flash_provider_enables_thinking_and_json_mode() -> None:
    expected = _analysis()
    response = {
        "id": "chatcmpl_deepseek_123",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(expected.model_dump(mode="json"), ensure_ascii=False),
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
    }
    executor = RecordingExecutor(response)
    provider = DeepSeekChatCompletionsProvider(
        model=DeepSeekModel.V4_FLASH,
        reasoning_effort=ReasoningEffort.HIGH,
        executor=executor,
        credential_loader=lambda: "sk-deepseek-temporary-secret",
    )

    result = provider.analyze(
        instructions="Analyze with evidence.",
        context_json='{"account":{"account_id":"acc_test"}}',
    )

    assert result.analysis == expected
    payload: Any = json.loads(executor.calls[0]["body"])
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 16_384
    assert "sk-deepseek-temporary-secret" not in executor.calls[0]["body"].decode("utf-8")


def test_deepseek_provider_falls_back_to_reasoning_content() -> None:
    """Thinking-mode DeepSeek may put the whole JSON in reasoning_content."""
    expected = _analysis()
    response = {
        "id": "chatcmpl_deepseek_reasoning",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": json.dumps(
                        expected.model_dump(mode="json"), ensure_ascii=False
                    ),
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
    }
    executor = RecordingExecutor(response)
    provider = DeepSeekChatCompletionsProvider(
        model=DeepSeekModel.V4_FLASH,
        reasoning_effort=ReasoningEffort.HIGH,
        executor=executor,
        credential_loader=lambda: "sk-deepseek-temporary-secret",
    )

    result = provider.analyze(
        instructions="Analyze with evidence.",
        context_json='{"account":{"account_id":"acc_test"}}',
    )

    assert result.analysis == expected
    assert result.response_id == "chatcmpl_deepseek_reasoning"


def test_deepseek_provider_reports_truncated_completion_readably() -> None:
    """A length-truncated DeepSeek response must surface a readable error."""
    response = {
        "id": "chatcmpl_deepseek_truncated",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": '{"executive_summary": "unfinished...',
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 8_000, "total_tokens": 8_100},
    }
    executor = RecordingExecutor(response)
    provider = DeepSeekChatCompletionsProvider(
        model=DeepSeekModel.V4_FLASH,
        reasoning_effort=ReasoningEffort.HIGH,
        executor=executor,
        credential_loader=lambda: "sk-deepseek-temporary-secret",
    )

    with pytest.raises(DistillerError) as exc:
        provider.analyze(
            instructions="Analyze with evidence.",
            context_json='{"account":{"account_id":"acc_test"}}',
        )

    assert exc.value.code is ErrorCode.MODEL_SCHEMA_INVALID
    assert "truncated" in exc.value.message
    assert exc.value.details["finish_reason"] == "length"
    assert "deepseek-v4-flash" in exc.value.details["hint"]


def test_cloud_analysis_options_reject_cross_provider_models() -> None:
    defaults = GptAnalysisOptions()
    assert defaults.provider is AnalysisProviderKind.DEEPSEEK
    assert defaults.model is DeepSeekModel.V4_FLASH
    assert defaults.reasoning_effort is ReasoningEffort.HIGH

    options = GptAnalysisOptions(
        provider=AnalysisProviderKind.BAILIAN,
        model=BailianModel.QWEN_3_7_PLUS,
    )
    assert options.provider is AnalysisProviderKind.BAILIAN

    with pytest.raises(ValueError, match="not available for provider"):
        GptAnalysisOptions(
            provider=AnalysisProviderKind.BAILIAN,
            model=OpenAIModel.TERRA,
        )


def test_bailian_provider_rejects_non_alibaba_endpoint() -> None:
    with pytest.raises(DistillerError, match="approved Alibaba Cloud HTTPS"):
        BailianChatCompletionsProvider(
            model=BailianModel.QWEN_3_7_PLUS,
            reasoning_effort=ReasoningEffort.LOW,
            credential_loader=lambda: "unused",
            base_url="https://example.com/compatible-mode/v1",
        )


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
        options.provider.value,
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
    assert audit["privacy"]["api_key_source"] == "DEEPSEEK_API_KEY"
    assert audit["privacy"]["raw_response_persisted"] is False
    assert audit["response"]["response_id"] == "resp_test"
    assert audit["response"]["estimated_cost"]["estimated_total_usd"] == 0.000028
    evaluation: Any = read_json(evaluation_path)
    statuses = {item["id"]: item["status"] for item in evaluation["checks"]}
    assert statuses["citation_completeness"] == "pass"
    assert statuses["evidence_allowlist_integrity"] == "pass"
    assert statuses["conclusion_stability"] == "insufficient_runs"
    assert statuses["knowledge_asset_completeness"] == "pass"
    assert statuses["knowledge_promotion_safety"] == "pass"
    assert statuses["derived_analysis_boundary"] == "pass"
    claim_paths = first["analysis"]["knowledge_claim_paths"]
    assert len(claim_paths) == 1
    claim: Any = read_json(normalized_project.root / claim_paths[0])
    assert claim["status"] == "experimental"
    assert claim["validated"] is False
    assert claim["requires_human_review"] is True
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
