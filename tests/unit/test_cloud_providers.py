from __future__ import annotations

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.providers import (
    CloudChatTextProvider,
    _chat_completions_url,
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


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        (
            "ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "https://ws-e8t5qxy8pxu50zz0.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        (
            "https://api.deepseek.com",
            "https://api.deepseek.com/v1/chat/completions",
        ),
        (
            "http://127.0.0.1:8082",
            "http://127.0.0.1:8082/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url_avoids_duplicate_v1_path(
    base_url: str,
    expected: str,
) -> None:
    assert _chat_completions_url(base_url) == expected


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
        model=BailianModel.QWEN_MAX,
    )
    assert options.model == "qwen-max"

    chat = GptAnalysisOptions(
        provider="deepseek",
        model=DeepSeekModel.CHAT,
    )
    assert chat.model == "deepseek-chat"


def test_gpt_analysis_options_infers_bailian_from_qwen_model() -> None:
    options = GptAnalysisOptions.model_validate(
        {"model": "qwen-plus", "template": "content_strategy"}
    )
    assert options.provider.value == "bailian"


class _StubResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body


def test_auth_failure_message_maps_insufficient_quota() -> None:
    from video_account_distiller.common.http_utils import _auth_failure_message

    message = _auth_failure_message(
        _StubResponse(
            403,
            b'{"error":{"code":"insufficient_quota","message":"Free quota exhausted."}}',
        ),
        status=403,
    )
    assert "额度不足" in message
    assert "insufficient_quota" in message


def test_auth_failure_message_maps_invalid_api_key() -> None:
    from video_account_distiller.common.http_utils import _auth_failure_message

    message = _auth_failure_message(
        _StubResponse(401, b'{"error":{"code":"invalid_api_key","message":"bad key"}}'),
        status=401,
    )
    assert "API Key 无效" in message


def test_auth_failure_message_falls_back_to_generic() -> None:
    from video_account_distiller.common.http_utils import _auth_failure_message

    message = _auth_failure_message(_StubResponse(403, b"nope"), status=403)
    assert message == "API rejected the credential or permission scope"
