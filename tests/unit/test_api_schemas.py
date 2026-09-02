"""API schema regression tests for the self-service distillation workflow."""

from __future__ import annotations

from typing import Any, Literal, cast

import pytest
from pydantic import ValidationError

from video_account_distiller.api.schemas import (
    AccountDistillWorkflowParams,
    AccountMediaReparseParams,
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
