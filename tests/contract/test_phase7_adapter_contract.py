from __future__ import annotations

import json
from collections.abc import Iterable

import pytest

from video_account_distiller.adapters import (
    FeishuBitableAdapter,
    GoogleSheetsAdapter,
    HttpResponse,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AuthorizationGrant,
    ConnectorKind,
    FeishuBitableConfig,
    GoogleSheetsConfig,
    RetryPolicy,
)


class FakeHttpExecutor:
    def __init__(self, responses: Iterable[HttpResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

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
            {"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout}
        )
        return self.responses.pop(0)


def _response(payload: dict[str, object], status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload).encode("utf-8"))


def _grant(connector: ConnectorKind) -> AuthorizationGrant:
    source_reference = {
        ConnectorKind.FEISHU_BITABLE: "bitable:app-token/table-id",
        ConnectorKind.GOOGLE_SHEETS: "sheets:sheet-id/Sheet1!A:C",
        ConnectorKind.AUTHORIZED_EXPORT: "offline contract fixture",
    }[connector]
    return AuthorizationGrant.model_validate(
        {
            "grant_id": f"grant-{connector.value}",
            "connector": connector,
            "confirmed_by": "owner",
            "confirmed_at": "2026-07-20T00:00:00Z",
            "scopes": ["read", "write"],
            "source_reference": source_reference,
        }
    )


def test_feishu_contract_paginates_and_maps_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_TEST_TOKEN", "secret-not-logged")
    executor = FakeHttpExecutor(
        [
            _response(
                {
                    "code": 0,
                    "data": {
                        "has_more": True,
                        "page_token": "next",
                        "items": [{"record_id": "rec-1", "fields": {"name": "A"}}],
                    },
                }
            ),
            _response(
                {
                    "code": 0,
                    "data": {
                        "has_more": False,
                        "items": [{"record_id": "rec-2", "fields": {"name": "B"}}],
                    },
                }
            ),
        ]
    )
    adapter = FeishuBitableAdapter(
        FeishuBitableConfig(
            connector_id="feishu-hotel",
            app_token="app-token",
            table_id="table-id",
            token_env="FEISHU_TEST_TOKEN",
            authorization=_grant(ConnectorKind.FEISHU_BITABLE),
        ),
        executor=executor,
        sleep=lambda _: None,
    )

    result = adapter.read_records()

    assert [row["_record_id"] for row in result.records] == ["rec-1", "rec-2"]
    assert len(result.raw_pages) == 2
    assert "page_token=next" in str(executor.calls[1]["url"])
    assert all("secret-not-logged" not in str(call["url"]) for call in executor.calls)


def test_feishu_contract_maps_permission_and_rate_limit_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_TEST_TOKEN", "secret")
    config = FeishuBitableConfig(
        connector_id="feishu-hotel",
        app_token="app-token",
        table_id="table-id",
        token_env="FEISHU_TEST_TOKEN",
        authorization=_grant(ConnectorKind.FEISHU_BITABLE),
        retry=RetryPolicy(max_retries=1, base_seconds=0),
    )
    denied = FeishuBitableAdapter(
        config, executor=FakeHttpExecutor([HttpResponse(403, b"{}")]), sleep=lambda _: None
    )
    with pytest.raises(DistillerError) as permission:
        denied.read_records()
    assert permission.value.code == ErrorCode.ADAPTER_AUTH

    limited = FeishuBitableAdapter(
        config,
        executor=FakeHttpExecutor([HttpResponse(429, b"{}"), HttpResponse(429, b"{}")]),
        sleep=lambda _: None,
    )
    with pytest.raises(DistillerError) as rate_limit:
        limited.read_records()
    assert rate_limit.value.code == ErrorCode.RATE_LIMIT


def test_adapter_requires_environment_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEISHU_TEST_TOKEN", raising=False)
    adapter = FeishuBitableAdapter(
        FeishuBitableConfig(
            connector_id="feishu-hotel",
            app_token="app-token",
            table_id="table-id",
            token_env="FEISHU_TEST_TOKEN",
            authorization=_grant(ConnectorKind.FEISHU_BITABLE),
        ),
        executor=FakeHttpExecutor([]),
    )

    with pytest.raises(DistillerError) as missing:
        adapter.read_records()
    assert missing.value.code == ErrorCode.ADAPTER_AUTH
    assert missing.value.details == {"token_env": "FEISHU_TEST_TOKEN"}


def test_google_sheets_contract_reads_headers_and_appends_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_TEST_TOKEN", "secret")
    executor = FakeHttpExecutor(
        [
            _response({"range": "Sheet1!A:C", "values": [["id", "name"], ["1", "Hotel"]]}),
            _response({"updates": {"updatedRows": 1}}),
        ]
    )
    adapter = GoogleSheetsAdapter(
        GoogleSheetsConfig(
            connector_id="google-hotel",
            spreadsheet_id="sheet-id",
            range="Sheet1!A:C",
            token_env="GOOGLE_TEST_TOKEN",
            columns=["id", "name"],
            authorization=_grant(ConnectorKind.GOOGLE_SHEETS),
        ),
        executor=executor,
        sleep=lambda _: None,
    )

    read = adapter.read_records()
    written = adapter.append_records([{"id": "2", "name": "Inn"}])

    assert read.records == [{"id": "1", "name": "Hotel"}]
    assert written.accepted_rows == 1
    assert executor.calls[1]["method"] == "POST"
    raw_body = executor.calls[1]["body"]
    assert isinstance(raw_body, bytes)
    body = json.loads(raw_body.decode("utf-8"))
    assert body["values"] == [["2", "Inn"]]
