"""Tests for the shared ``common.http_utils`` module."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from video_account_distiller.common.http_utils import (
    compute_retry_after,
    read_env_credential,
    request_json,
)
from video_account_distiller.errors import DistillerError, ErrorCode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http_response(
    status: int = 200,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Build a small collaboration.HttpResponse stand-in for testing."""
    import json as _json

    from video_account_distiller.adapters.collaboration import HttpResponse

    return HttpResponse(
        status=status,
        body=(_json.dumps(body or {"ok": True}, ensure_ascii=False).encode("utf-8")),
        headers=headers or {},
    )


def _retry_policy(
    max_retries: int = 2, base_seconds: float = 0.1, timeout_seconds: int = 10
) -> Any:
    from video_account_distiller.models.collaboration import RetryPolicy

    return RetryPolicy(
        max_retries=max_retries,
        base_seconds=base_seconds,
        timeout_seconds=timeout_seconds,
    )


class _FakeExecutor:
    """Executor that replays a preset list of responses."""

    def __init__(self, *responses: Any) -> None:
        self._calls: list[dict[str, Any]] = []
        self._iter: Iterator[Any] = iter(responses)

    def send(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs)
        try:
            return next(self._iter)
        except StopIteration:
            return _http_response(200)


# ---------------------------------------------------------------------------
# read_env_credential
# ---------------------------------------------------------------------------


def test_credential_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_ENV_VAR", raising=False)
    with pytest.raises(DistillerError) as exc:
        read_env_credential("MISSING_ENV_VAR")
    assert exc.value.code == ErrorCode.ADAPTER_AUTH
    assert "MISSING_ENV_VAR" in str(exc.value.details)


def test_credential_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMPTY_TOKEN", "")
    with pytest.raises(DistillerError):
        read_env_credential("EMPTY_TOKEN")


def test_credential_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_TOKEN", "abc123")
    assert read_env_credential("MY_TOKEN") == "abc123"


# ---------------------------------------------------------------------------
# compute_retry_after
# ---------------------------------------------------------------------------


def test_retry_after_header() -> None:
    resp = _http_response(headers={"Retry-After": "12"})
    delay = compute_retry_after(resp, 0, _retry_policy())
    assert delay == 12.0


def test_retry_after_header_capped() -> None:
    resp = _http_response(headers={"Retry-After": "999"})
    delay = compute_retry_after(resp, 0, _retry_policy())
    assert delay == 60.0


def test_retry_after_exponential() -> None:
    resp = _http_response()
    delay = compute_retry_after(resp, 2, _retry_policy(base_seconds=0.5))
    assert delay == 2.0  # 0.5 * 2^2


def test_retry_after_exponential_capped() -> None:
    resp = _http_response()
    delay = compute_retry_after(resp, 20, _retry_policy(base_seconds=10))
    assert delay == 60.0


# ---------------------------------------------------------------------------
# request_json
# ---------------------------------------------------------------------------


def test_request_json_success() -> None:
    executor = _FakeExecutor(_http_response(200, {"data": "hello"}))
    result = request_json(
        executor,
        method="GET",
        url="https://api.example.com/v1",
        token="t",
        policy=_retry_policy(),
    )
    assert result == {"data": "hello"}


def test_request_json_auth_failure() -> None:
    executor = _FakeExecutor(_http_response(401))
    with pytest.raises(DistillerError) as exc:
        request_json(
            executor,
            method="GET",
            url="https://api.example.com/v1",
            token="t",
            policy=_retry_policy(),
        )
    assert exc.value.code == ErrorCode.ADAPTER_AUTH


def test_request_json_retries_then_succeeds() -> None:
    executor = _FakeExecutor(
        _http_response(500),
        _http_response(200, {"ok": True}),
    )
    slept: list[float] = []
    result = request_json(
        executor,
        method="GET",
        url="https://api.example.com/v1",
        token="t",
        policy=_retry_policy(max_retries=1, base_seconds=0.01),
        sleep=slept.append,
    )
    assert result == {"ok": True}
    assert len(slept) == 1


def test_request_json_rate_limit_exhausted() -> None:
    executor = _FakeExecutor(_http_response(429), _http_response(429))
    with pytest.raises(DistillerError) as exc:
        request_json(
            executor,
            method="GET",
            url="https://api.example.com/v1",
            token="t",
            policy=_retry_policy(max_retries=1),
            sleep=lambda _: None,
        )
    assert exc.value.code == ErrorCode.RATE_LIMIT


def test_request_json_bad_status() -> None:
    executor = _FakeExecutor(_http_response(404))
    with pytest.raises(DistillerError) as exc:
        request_json(
            executor,
            method="GET",
            url="https://api.example.com/v1",
            token="t",
            policy=_retry_policy(),
        )
    assert exc.value.code == ErrorCode.ADAPTER_RESPONSE


def test_request_json_bad_status_redacts_upstream_credential_echoes() -> None:
    bearer_secret = "request-bearer-secret-value"
    api_key_secret = "upstream-api-key-secret-value"
    header_secret = "custom-header-secret-value"
    executor = _FakeExecutor(
        _http_response(
            400,
            {
                "error": {
                    "message": (
                        f"Authorization: Bearer {bearer_secret}; "
                        f"api_key={api_key_secret}; echoed={header_secret}"
                    )
                }
            },
        )
    )

    with pytest.raises(DistillerError) as exc:
        request_json(
            executor,
            method="POST",
            url="https://api.example.com/v1",
            token=bearer_secret,
            extra_headers={"X-API-Key": header_secret},
            policy=_retry_policy(),
        )

    details = str(exc.value.details)
    assert "[REDACTED]" in details
    assert bearer_secret not in details
    assert api_key_secret not in details
    assert header_secret not in details


def test_request_json_non_json_body() -> None:
    from video_account_distiller.adapters.collaboration import HttpResponse

    executor = _FakeExecutor(HttpResponse(200, b"not json"))
    with pytest.raises(DistillerError) as exc:
        request_json(
            executor,
            method="GET",
            url="https://api.example.com/v1",
            token="t",
            policy=_retry_policy(),
        )
    assert exc.value.code == ErrorCode.ADAPTER_RESPONSE
