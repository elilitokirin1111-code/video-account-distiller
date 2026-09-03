"""API schema regression tests for the self-service distillation workflow."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

import pytest
from pydantic import ValidationError

from video_account_distiller.api.schemas import (
    AccountDistillWorkflowParams,
    AccountMediaReparseParams,
    materialize_account_distill_cloud_routing,
    resolve_account_distill_cloud_credential_provider,
)
from video_account_distiller.insights import AnalysisProviderKind, DeepSeekModel, ReasoningEffort


@pytest.mark.parametrize(
    "vision_provider",
    ["ollama", "llamacpp", "cloud", None],
)
def test_account_distill_accepts_current_vision_providers(
    vision_provider: Literal["ollama", "llamacpp", "cloud"] | None,
) -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        vision_provider=vision_provider,
    )
    assert params.vision_provider == vision_provider


def test_account_distill_rejects_unknown_vision_provider() -> None:
    with pytest.raises(ValidationError):
        AccountDistillWorkflowParams(
            url="https://www.douyin.com/user/demo",
            vision_provider=cast(Any, "sdxl"),
        )


def test_account_distill_accepts_video_content_knowledge_mode() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        distillation_mode="knowledge",
        video_knowledge_provider="llamacpp",
    )

    assert params.distillation_mode == "knowledge"
    assert params.video_knowledge_provider == "llamacpp"


def test_account_distill_accepts_complete_creative_mode() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        distillation_mode="creative_learning",
        distill_video_knowledge=True,
        video_knowledge_provider="cloud",
        video_knowledge_model="deepseek-v4-flash",
    )

    assert params.distillation_mode == "creative_learning"
    assert params.distill_video_knowledge is True
    assert params.video_knowledge_model == "deepseek-v4-flash"


def test_bailian_deepseek_v4_requires_workspace_specific_text_endpoint() -> None:
    with pytest.raises(ValidationError, match="工作空间专属 MaaS"):
        AccountDistillWorkflowParams(
            url="https://www.douyin.com/user/demo",
            cloud_credential_provider="bailian",
            cloud_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            cloud_text_model="deepseek-v4-flash",
            video_knowledge_provider="cloud",
            video_knowledge_model="deepseek-v4-flash",
        )

    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        cloud_credential_provider="bailian",
        cloud_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        cloud_text_base_url=(
            "https://workspace-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
        cloud_text_model="deepseek-v4-flash",
        video_knowledge_provider="cloud",
        video_knowledge_model="deepseek-v4-flash",
    )

    assert params.cloud_text_base_url is not None
    assert ".maas.aliyuncs.com/" in params.cloud_text_base_url


def test_bailian_qwen_text_model_can_use_generic_dashscope_endpoint() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        cloud_credential_provider="bailian",
        cloud_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        cloud_text_model="qwen3.7-plus",
        video_knowledge_model="qwen3.7-plus",
    )

    assert params.cloud_text_model == "qwen3.7-plus"


def test_cloud_provider_inference_considers_text_endpoint() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        vision_provider=None,
        text_provider="cloud",
        cloud_text_base_url="https://api.deepseek.com/v1",
        cloud_text_model="deepseek-chat",
    )

    assert resolve_account_distill_cloud_credential_provider(params) == "deepseek"


def test_cloud_routing_materializes_provider_safe_default_before_key_lookup() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        vision_provider="cloud",
        cloud_credential_provider="bailian",
        cloud_vision_model="qwen-vl-max-latest",
    )

    routed = materialize_account_distill_cloud_routing(params)

    assert routed.cloud_credential_provider == "bailian"
    assert routed.cloud_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_cloud_routing_rejects_mismatched_project_preset_before_key_lookup() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        vision_provider="cloud",
        cloud_credential_provider="bailian",
        cloud_vision_model="qwen-vl-max-latest",
    )

    with pytest.raises(ValidationError, match="域名不一致"):
        materialize_account_distill_cloud_routing(
            params,
            fallback_base_url="https://api.deepseek.com/v1",
        )


def test_cloud_routes_reject_cross_provider_endpoints() -> None:
    with pytest.raises(ValidationError, match="属于不同服务商"):
        AccountDistillWorkflowParams(
            url="https://www.douyin.com/user/demo",
            vision_provider="cloud",
            text_provider="cloud",
            cloud_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            cloud_text_base_url="https://api.deepseek.com/v1",
            cloud_vision_model="qwen-vl-max-latest",
            cloud_text_model="deepseek-chat",
        )


@pytest.mark.parametrize(
    ("provider", "cloud_base_url", "cloud_text_base_url"),
    [
        ("deepseek", "https://dashscope.aliyuncs.com/compatible-mode/v1", None),
        ("openai", None, "https://api.deepseek.com/v1"),
        (
            "deepseek",
            "https://api.deepseek.com/v1",
            "https://workspace-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        ),
    ],
)
def test_explicit_cloud_provider_must_match_both_known_endpoint_domains(
    provider: Literal["openai", "bailian", "deepseek"],
    cloud_base_url: str | None,
    cloud_text_base_url: str | None,
) -> None:
    with pytest.raises(ValidationError, match="域名不一致|属于不同服务商"):
        AccountDistillWorkflowParams(
            url="https://www.douyin.com/user/demo",
            cloud_credential_provider=provider,
            cloud_base_url=cloud_base_url,
            cloud_text_base_url=cloud_text_base_url,
        )


def test_legacy_cloud_api_key_is_masked_in_repr_and_validation_errors() -> None:
    secret = "sk-schema-plaintext-never-echo"
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        cloud_credential_provider="deepseek",
        cloud_text_base_url="https://api.deepseek.com/v1",
        cloud_api_key=cast(Any, secret),
    )

    assert params.cloud_api_key is not None
    assert params.cloud_api_key.get_secret_value() == secret
    assert secret not in repr(params)

    with pytest.raises(ValidationError) as exc_info:
        AccountDistillWorkflowParams(
            url="https://www.douyin.com/user/demo",
            cloud_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            cloud_text_base_url="https://api.deepseek.com/v1",
            cloud_api_key=cast(Any, secret),
        )
    rendered_errors = json.dumps(exc_info.value.errors(), ensure_ascii=False, default=str)
    assert secret not in rendered_errors


def test_account_distill_accepts_secret_free_deepseek_knowledge_synthesis() -> None:
    params = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        knowledge_analysis=cast(
            Any,
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "template": "content_strategy",
                "reasoning_effort": "high",
                "confirm_cloud_upload": True,
                "confirm_cost": True,
            },
        ),
    )

    assert params.knowledge_analysis is not None
    assert params.knowledge_analysis.provider is AnalysisProviderKind.DEEPSEEK
    assert params.knowledge_analysis.model is DeepSeekModel.V4_FLASH
    assert params.knowledge_analysis.reasoning_effort is ReasoningEffort.HIGH
    assert "api_key" not in params.model_dump(mode="json")["knowledge_analysis"]


def test_account_workflow_and_reparse_allow_full_collection_scope() -> None:
    workflow = AccountDistillWorkflowParams(
        url="https://www.douyin.com/user/demo",
        media_limit=20_000,
    )
    reparse = AccountMediaReparseParams(
        mode="selected",
        video_ids=["vid_demo"],
        limit=20_000,
    )

    assert workflow.media_limit == 20_000
    assert reparse.limit == 20_000
    assert reparse.refresh_media is True

    with pytest.raises(ValidationError):
        AccountDistillWorkflowParams(
            url="https://www.douyin.com/user/demo",
            media_limit=20_001,
        )
    with pytest.raises(ValidationError):
        AccountMediaReparseParams(limit=20_001)
