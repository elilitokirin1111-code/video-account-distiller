"""Shared HTTP utilities for authorized API adapters and providers.

Centralises the credential, retry-after, and bounded-retry JSON-request
patterns used by both the collaboration adapters and the Phase 8 account
collection providers.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from video_account_distiller.errors import DistillerError, ErrorCode

if TYPE_CHECKING:
    from video_account_distiller.adapters.collaboration import HttpExecutor, HttpResponse
    from video_account_distiller.models.collaboration import RetryPolicy


def read_env_credential(env_var: str, label: str | None = None) -> str:
    """Read an API token from an environment variable.

    Raises ``DistillerError(ADAPTER_AUTH)`` when the variable is unset or empty.
    The *label* is used in error messages when the caller wants a friendlier
    name than the raw env-var.
    """
    token = os.environ.get(env_var)
    if not token:
        raise DistillerError(
            ErrorCode.ADAPTER_AUTH,
            f"{label or env_var} credential is not available",
            details={"token_env": env_var},
        )
    return token


def compute_retry_after(response: HttpResponse, attempt: int, policy: RetryPolicy) -> float:
    """Compute a back-off delay (seconds, capped at 60.0).

    Respects a ``Retry-After`` header when present; otherwise uses exponential
    back-off from *policy.base_seconds*.
    """
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), 60.0)
        except ValueError:
            pass
    return min(policy.base_seconds * float(2**attempt), 60.0)


def request_json(
    executor: HttpExecutor,
    *,
    method: str,
    url: str,
    token: str,
    policy: RetryPolicy,
    payload: dict[str, Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make a bounded-retry HTTP request, returning the parsed JSON object.

    The caller owns auth — *token* is sent as a Bearer credential.  Optional
    *extra_headers* are merged into the request headers (caller-side values
    take precedence over defaults).

    Raises ``DistillerError`` for auth failures (401/403), rate-limit
    exhaustion (429), or unexpected HTTP / JSON responses.
    """
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8") if payload else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "video-account-distiller/1.0",
    }
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if extra_headers:
        headers.update(extra_headers)

    for attempt in range(policy.max_retries + 1):
        response = executor.send(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout=policy.timeout_seconds,
        )
        if response.status in {401, 403}:
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "API rejected the credential or permission scope",
                details={"http_status": response.status},
            )
        retryable = response.status == 429 or response.status >= 500
        if retryable and attempt < policy.max_retries:
            sleep(compute_retry_after(response, attempt, policy))
            continue
        if response.status == 429:
            raise DistillerError(
                ErrorCode.RATE_LIMIT,
                "API rate limit remained active after bounded retries",
                details={"attempts": attempt + 1},
            )
        if response.status < 200 or response.status >= 300:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "API returned an unexpected response",
                details={"http_status": response.status},
            )
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "API response is not valid UTF-8 JSON",
            ) from exc
        if not isinstance(decoded, dict):
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "API JSON root must be an object",
            )
        return {str(key): value for key, value in decoded.items()}
    raise AssertionError("unreachable retry loop")
