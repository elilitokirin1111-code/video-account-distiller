"""API schema regression tests for the self-service distillation workflow."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_account_distiller.api.schemas import AccountDistillWorkflowParams


@pytest.mark.parametrize(
    "vision_provider",
    ["ollama", "llamacpp", "cloud", None],
)
def test_account_distill_accepts_current_vision_providers(
    vision_provider: str | None,
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
            vision_provider="sdxl",
        )
