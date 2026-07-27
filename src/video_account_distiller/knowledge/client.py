"""Dependency-light OpenKB REST client with injectable HTTP execution."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urljoin

from pydantic import BaseModel, ValidationError

from video_account_distiller.adapters.collaboration import (
    HttpExecutor,
    HttpResponse,
    UrllibHttpExecutor,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.models import (
    OpenKBAddResponse,
    OpenKBInitResponse,
    OpenKBQueryResponse,
    OpenKBRemoveResponse,
    OpenKBStatusResponse,
    OpenKBTarget,
)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def _retry_delay(response: HttpResponse, attempt: int) -> float:
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), 60.0)
        except ValueError:
            pass
    return min(0.5 * float(2**attempt), 60.0)


def _multipart_document(*, kb: str, path: Path, boundary: str) -> bytes:
    content = path.read_bytes()
    fields = (
        ("kb", kb.encode("utf-8")),
        ("stream", b"false"),
    )
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
            "Content-Type: text/markdown; charset=utf-8\r\n\r\n"
        ).encode()
    )
    body.extend(content)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body)


class OpenKBClient:
    """Validated client for the OpenKB endpoints used by Distiller."""

    def __init__(
        self,
        target: OpenKBTarget,
        *,
        token: str | None,
        executor: HttpExecutor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.target = target
        self._token = token
        self.executor = executor or UrllibHttpExecutor()
        self.sleep = sleep

    @property
    def token_configured(self) -> bool:
        return self._token is not None

    def _url(self, path: str) -> str:
        return urljoin(f"{self.target.base_url.rstrip('/')}/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "video-account-distiller/1.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _request(
        self,
        *,
        method: str,
        path: str,
        model: type[ResponseT],
        json_payload: dict[str, Any] | None = None,
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ResponseT:
        if json_payload is not None:
            body = json.dumps(json_payload, ensure_ascii=False, default=str).encode("utf-8")
        headers = self._headers()
        if json_payload is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if extra_headers:
            headers.update(extra_headers)

        response: HttpResponse | None = None
        for attempt in range(self.target.max_retries + 1):
            response = self.executor.send(
                method=method,
                url=self._url(path),
                headers=headers,
                body=body,
                timeout=self.target.timeout_seconds,
            )
            retryable = response.status == 429 or response.status >= 500
            if retryable and attempt < self.target.max_retries:
                self.sleep(_retry_delay(response, attempt))
                continue
            break
        assert response is not None
        if response.status in {401, 403}:
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "OpenKB rejected the configured bearer token",
                details={"http_status": response.status, "token_env": self.target.token_env},
            )
        if response.status == 429:
            raise DistillerError(
                ErrorCode.RATE_LIMIT,
                "OpenKB remained rate limited after bounded retries",
                details={"attempts": self.target.max_retries + 1},
            )
        if response.status < 200 or response.status >= 300:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "OpenKB returned an unexpected response",
                details={"http_status": response.status, "endpoint": path},
            )
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "OpenKB response is not valid UTF-8 JSON",
                details={"endpoint": path},
            ) from exc
        try:
            return model.model_validate(decoded)
        except ValidationError as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "OpenKB response does not match the expected contract",
                details={"endpoint": path, "response_model": model.__name__},
            ) from exc

    def init_kb(self) -> OpenKBInitResponse:
        return self._request(
            method="POST",
            path="/api/v1/init",
            model=OpenKBInitResponse,
            json_payload={"kb": self.target.kb},
        )

    def add_document(self, path: Path, *, payload_hash: str) -> OpenKBAddResponse:
        boundary = f"distiller-{payload_hash[:24]}"
        body = _multipart_document(kb=self.target.kb, path=path, boundary=boundary)
        return self._request(
            method="POST",
            path="/api/v1/add",
            model=OpenKBAddResponse,
            body=body,
            extra_headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )

    def remove_document(self, identifier: str) -> OpenKBRemoveResponse | None:
        try:
            return self._request(
                method="POST",
                path="/api/v1/remove",
                model=OpenKBRemoveResponse,
                json_payload={
                    "kb": self.target.kb,
                    "identifier": identifier,
                    "keep_raw": False,
                    "keep_empty": False,
                    "dry_run": False,
                    "stream": False,
                },
            )
        except DistillerError as exc:
            if exc.code is ErrorCode.ADAPTER_RESPONSE and exc.details.get("http_status") == 404:
                return None
            raise

    def status(self) -> OpenKBStatusResponse:
        return self._request(
            method="POST",
            path="/api/v1/status",
            model=OpenKBStatusResponse,
            json_payload={"kb": self.target.kb},
        )

    def query(self, question: str, *, save: bool = False) -> OpenKBQueryResponse:
        return self._request(
            method="POST",
            path="/api/v1/query",
            model=OpenKBQueryResponse,
            json_payload={
                "kb": self.target.kb,
                "question": question,
                "stream": False,
                "save": save,
            },
        )
