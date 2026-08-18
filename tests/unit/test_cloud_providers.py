from __future__ import annotations

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.providers import (
    CloudChatTextProvider,
    _normalize_https_base_url,
)
from video_account_distiller.insights.gpt_analysis import (
    BailianModel,
    DeepSeekModel,
    GptAnalysisOptions,
)
from video_account_distiller.media.providers import CloudVisionProvider


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("api.deepseek.com", "https://api.deepseek.com"),
        (
            "ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
            "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
        ),
        ("https://api.deepseek.com", "https://api.deepseek.com"),
        ("http://127.0.0.1:8081", "http://127.0.0.1:8081"),
        ("  ", ""),
        ("", ""),
    ],
)
def test_normalize_https_base_url_defaults_scheme(raw: str, expected: str) -> None:
    assert _normalize_https_base_url(raw) == expected


def test_cloud_text_provider_normalizes_scheme_less_maas_gateway() -> None:
    provider = CloudChatTextProvider(
        model="qwen-max-latest",
        base_url="ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
        api_key="sk-test",
    )
    assert provider.base_url == "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com"


def test_cloud_vision_provider_accepts_scheme_less_maas_gateway() -> None:
    provider = CloudVisionProvider(
        model="qwen-vl-max-latest",
        base_url="ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com",
        api_key="sk-test",
    )
    assert provider.base_url == "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com"


def test_cloud_vision_provider_accepts_any_https_origin_without_scheme() -> None:
    provider = CloudVisionProvider(
        model="qwen-vl-max-latest",
        base_url="openai-compatible.example.com",
        api_key="sk-test",
    )
    assert provider.base_url == "https://openai-compatible.example.com"


def test_cloud_vision_provider_rejects_plain_http_remote() -> None:
    with pytest.raises(DistillerError) as exc_info:
        CloudVisionProvider(
            model="qwen-vl-max-latest",
            base_url="http://api.example.com",
            api_key="sk-test",
        )
    assert exc_info.value.code is ErrorCode.SCHEMA_INVALID


def test_gpt_analysis_options_accept_qwen_models_for_bailian() -> None:
    options = GptAnalysisOptions(
        provider="bailian",
        model=BailianModel.QWEN_MAX_LATEST,
    )
    assert options.model == "qwen-max-latest"

    chat = GptAnalysisOptions(
        provider="deepseek",
        model=DeepSeekModel.CHAT,
    )
    assert chat.model == "deepseek-chat"


def test_gpt_analysis_options_infers_bailian_from_qwen_model() -> None:
    options = GptAnalysisOptions.model_validate(
        {"model": "qwen-plus-latest", "template": "content_strategy"}
    )
    assert options.provider.value == "bailian"
