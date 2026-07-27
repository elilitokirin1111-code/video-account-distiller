from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from video_account_distiller.adapters.collaboration import HttpResponse
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.client import OpenKBClient
from video_account_distiller.knowledge.models import OpenKBTarget
from video_account_distiller.knowledge.service import resolve_openkb_target
from video_account_distiller.storage.project import ProjectLayout


class FakeExecutor:
    def __init__(self, responses: Iterable[HttpResponse]) -> None:
        self.responses = list(responses)
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
        return self.responses.pop(0)


def _response(payload: dict[str, object], status: int = 200) -> HttpResponse:
    return HttpResponse(status=status, body=json.dumps(payload).encode("utf-8"))


def test_openkb_client_initializes_and_uploads_multipart(tmp_path: Path) -> None:
    executor = FakeExecutor(
        [
            _response({"kb": "distiller-demo", "created": True, "message": "created"}),
            _response(
                {
                    "kb": "distiller-demo",
                    "files": [
                        {
                            "original_name": "account-demo.md",
                            "saved_path": "raw/account-demo.md",
                            "status": "added",
                        }
                    ],
                    "added_count": 1,
                    "skipped_count": 0,
                    "failed_count": 0,
                }
            ),
        ]
    )
    client = OpenKBClient(
        OpenKBTarget(base_url="http://127.0.0.1:7566", kb="distiller-demo"),
        token="secret-token",
        executor=executor,
        sleep=lambda _: None,
    )
    path = tmp_path / "account-demo.md"
    path.write_text("# Account\n", encoding="utf-8")

    initialized = client.init_kb()
    added = client.add_document(path, payload_hash="a" * 64)

    assert initialized.created is True
    assert added.added_count == 1
    upload = executor.calls[1]
    assert upload["headers"]["Authorization"] == "Bearer secret-token"
    assert upload["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="kb"\r\n\r\ndistiller-demo' in upload["body"]
    assert b'filename="account-demo.md"' in upload["body"]


def test_openkb_client_maps_auth_and_invalid_contract() -> None:
    target = OpenKBTarget(base_url="http://127.0.0.1:7566", kb="distiller-demo")
    auth_client = OpenKBClient(
        target,
        token="bad",
        executor=FakeExecutor([HttpResponse(401, b"{}")]),
        sleep=lambda _: None,
    )
    with pytest.raises(DistillerError) as auth_exc:
        auth_client.status()
    assert auth_exc.value.code is ErrorCode.ADAPTER_AUTH

    invalid_client = OpenKBClient(
        target,
        token=None,
        executor=FakeExecutor([_response({"unexpected": True})]),
        sleep=lambda _: None,
    )
    with pytest.raises(DistillerError) as contract_exc:
        invalid_client.status()
    assert contract_exc.value.code is ErrorCode.ADAPTER_RESPONSE


def test_openkb_target_rejects_insecure_remote_http(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(DistillerError) as insecure:
        resolve_openkb_target(project, base_url="http://openkb.example.com")
    assert insecure.value.code is ErrorCode.SCHEMA_INVALID

    monkeypatch.delenv("DISTILLER_OPENKB_API_TOKEN", raising=False)
    with pytest.raises(DistillerError) as missing_token:
        resolve_openkb_target(project, base_url="https://openkb.example.com")
    assert missing_token.value.code is ErrorCode.ADAPTER_AUTH

    target, token = resolve_openkb_target(
        project,
        base_url="https://openkb.example.com",
        require_remote_token=False,
    )
    assert target.base_url == "https://openkb.example.com"
    assert token is None
