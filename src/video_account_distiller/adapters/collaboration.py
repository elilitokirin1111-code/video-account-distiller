"""Authorized Feishu Bitable and Google Sheets adapters with injectable HTTP."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models.collaboration import (
    AdapterReadResult,
    AdapterWriteResult,
    AuthorizationGrant,
    ConnectorConfig,
    ConnectorKind,
    FeishuBitableConfig,
    GoogleSheetsConfig,
    RetryPolicy,
)


class HttpResponse:
    """Small dependency-free HTTP response used by real and fake executors."""

    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}


class HttpExecutor(Protocol):
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> HttpResponse: ...


class UrllibHttpExecutor:
    """Official-API HTTP executor; no browser, login automation, or scraping."""

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return HttpResponse(
                    status=int(response.status),
                    body=response.read(),
                    headers={str(key): str(value) for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            return HttpResponse(
                status=exc.code,
                body=exc.read(),
                headers={str(key): str(value) for key, value in exc.headers.items()},
            )
        except URLError as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Adapter request could not reach the official API",
                details={"reason": str(exc.reason)},
            ) from exc


def _credential(token_env: str) -> str:
    token = os.environ.get(token_env)
    if not token:
        raise DistillerError(
            ErrorCode.ADAPTER_AUTH,
            "Adapter credential is not available",
            details={"token_env": token_env},
        )
    return token


def _retry_after(response: HttpResponse, attempt: int, policy: RetryPolicy) -> float:
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw:
        try:
            return min(float(raw), 60.0)
        except ValueError:
            pass
    delay = policy.base_seconds * float(2**attempt)
    return min(delay, 60.0)


def _request_json(
    executor: HttpExecutor,
    *,
    method: str,
    url: str,
    token: str,
    policy: RetryPolicy,
    payload: dict[str, Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8") if payload else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "video-account-distiller/0.7",
    }
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
                "Official API rejected the adapter credential or permission scope",
                details={"http_status": response.status},
            )
        retryable = response.status == 429 or response.status >= 500
        if retryable and attempt < policy.max_retries:
            sleep(_retry_after(response, attempt, policy))
            continue
        if response.status == 429:
            raise DistillerError(
                ErrorCode.RATE_LIMIT,
                "Official API rate limit remained active after bounded retries",
                details={"attempts": attempt + 1},
            )
        if response.status < 200 or response.status >= 300:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Official API returned an unexpected response",
                details={"http_status": response.status},
            )
        try:
            decoded = json.loads(response.body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Official API response is not valid UTF-8 JSON",
            ) from exc
        if not isinstance(decoded, dict):
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Official API JSON root must be an object",
            )
        return {str(key): value for key, value in decoded.items()}
    raise AssertionError("unreachable retry loop")


def _feishu_data(payload: dict[str, Any]) -> dict[str, Any]:
    code = payload.get("code", 0)
    if code == 0 and isinstance(payload.get("data"), dict):
        return {str(key): value for key, value in payload["data"].items()}
    message = str(payload.get("msg", "unknown Feishu API error"))
    auth_markers = ("permission", "forbidden", "unauthorized", "token", "权限", "授权")
    error_code = (
        ErrorCode.ADAPTER_AUTH
        if any(item in message.casefold() for item in auth_markers)
        else ErrorCode.ADAPTER_RESPONSE
    )
    raise DistillerError(
        error_code,
        "Feishu Bitable API rejected the request",
        details={"provider_code": code, "provider_message": message},
    )


class CollaborationAdapter(Protocol):
    @property
    def connector_kind(self) -> ConnectorKind: ...

    @property
    def connector_id(self) -> str: ...

    @property
    def authorization(self) -> AuthorizationGrant: ...

    def read_records(self) -> AdapterReadResult: ...

    def append_records(self, records: list[dict[str, Any]]) -> AdapterWriteResult: ...


class FeishuBitableAdapter:
    """Read and append Bitable rows through the documented Open API."""

    def __init__(
        self,
        config: FeishuBitableConfig,
        *,
        executor: HttpExecutor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.executor = executor or UrllibHttpExecutor()
        self.sleep = sleep

    @property
    def connector_kind(self) -> ConnectorKind:
        return ConnectorKind.FEISHU_BITABLE

    @property
    def connector_id(self) -> str:
        return self.config.connector_id

    @property
    def authorization(self) -> AuthorizationGrant:
        return self.config.authorization

    @property
    def _records_url(self) -> str:
        app = quote(self.config.app_token, safe="")
        table = quote(self.config.table_id, safe="")
        return f"{self.config.api_base}/open-apis/bitable/v1/apps/{app}/tables/{table}/records"

    def read_records(self) -> AdapterReadResult:
        self.config.authorization.require("read")
        token = _credential(self.config.token_env)
        records: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            query: dict[str, str | int] = {"page_size": self.config.page_size}
            if page_token:
                query["page_token"] = page_token
            payload = _request_json(
                self.executor,
                method="GET",
                url=f"{self._records_url}?{urlencode(query)}",
                token=token,
                policy=self.config.retry,
                sleep=self.sleep,
            )
            pages.append(payload)
            data = _feishu_data(payload)
            items = data.get("items", [])
            if not isinstance(items, list):
                raise DistillerError(ErrorCode.ADAPTER_RESPONSE, "Feishu items must be an array")
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("fields"), dict):
                    raise DistillerError(
                        ErrorCode.ADAPTER_RESPONSE,
                        "Feishu record must contain an object fields property",
                    )
                row = {str(key): value for key, value in item["fields"].items()}
                record_id = item.get("record_id") or item.get("id")
                if record_id is not None:
                    row["_record_id"] = str(record_id)
                records.append(row)
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")
            if not page_token:
                raise DistillerError(
                    ErrorCode.ADAPTER_RESPONSE,
                    "Feishu response says has_more without a page_token",
                )
        return AdapterReadResult(
            connector=ConnectorKind.FEISHU_BITABLE,
            connector_id=self.config.connector_id,
            source_reference=f"bitable:{self.config.app_token}/{self.config.table_id}",
            fetched_at=datetime.now(UTC),
            records=records,
            raw_pages=pages,
        )

    def append_records(self, records: list[dict[str, Any]]) -> AdapterWriteResult:
        self.config.authorization.require("write")
        token = _credential(self.config.token_env)
        response_ids: list[str] = []
        accepted = 0
        for start in range(0, len(records), 500):
            chunk = records[start : start + 500]
            payload = _request_json(
                self.executor,
                method="POST",
                url=f"{self._records_url}/batch_create",
                token=token,
                policy=self.config.retry,
                payload={"records": [{"fields": row} for row in chunk]},
                sleep=self.sleep,
            )
            data = _feishu_data(payload)
            created = data.get("records", [])
            if not isinstance(created, list):
                raise DistillerError(
                    ErrorCode.ADAPTER_RESPONSE, "Feishu created records must be an array"
                )
            accepted += len(created)
            response_ids.extend(
                str(item.get("record_id") or item.get("id"))
                for item in created
                if isinstance(item, dict) and (item.get("record_id") or item.get("id"))
            )
        return AdapterWriteResult(
            connector=ConnectorKind.FEISHU_BITABLE,
            connector_id=self.config.connector_id,
            target_reference=f"bitable:{self.config.app_token}/{self.config.table_id}",
            written_at=datetime.now(UTC),
            requested_rows=len(records),
            accepted_rows=accepted,
            response_ids=response_ids,
        )


class GoogleSheetsAdapter:
    """Read and append tabular values through Google Sheets API v4."""

    def __init__(
        self,
        config: GoogleSheetsConfig,
        *,
        executor: HttpExecutor | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.executor = executor or UrllibHttpExecutor()
        self.sleep = sleep

    @property
    def connector_kind(self) -> ConnectorKind:
        return ConnectorKind.GOOGLE_SHEETS

    @property
    def connector_id(self) -> str:
        return self.config.connector_id

    @property
    def authorization(self) -> AuthorizationGrant:
        return self.config.authorization

    @property
    def _values_url(self) -> str:
        spreadsheet = quote(self.config.spreadsheet_id, safe="")
        range_value = quote(self.config.range, safe="!:$'(),")
        return f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet}/values/{range_value}"

    def read_records(self) -> AdapterReadResult:
        self.config.authorization.require("read")
        payload = _request_json(
            self.executor,
            method="GET",
            url=f"{self._values_url}?majorDimension=ROWS",
            token=_credential(self.config.token_env),
            policy=self.config.retry,
            sleep=self.sleep,
        )
        values = payload.get("values", [])
        if not isinstance(values, list) or any(not isinstance(row, list) for row in values):
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE, "Google Sheets values must be an array of rows"
            )
        records: list[dict[str, Any]] = []
        if values:
            headers = [str(value).strip() for value in values[0]]
            if any(not header for header in headers) or len(headers) != len(set(headers)):
                raise DistillerError(
                    ErrorCode.ADAPTER_RESPONSE,
                    "Google Sheets header row must be unique and non-empty",
                )
            for row in values[1:]:
                records.append(
                    {
                        header: row[index] if index < len(row) else None
                        for index, header in enumerate(headers)
                    }
                )
        return AdapterReadResult(
            connector=ConnectorKind.GOOGLE_SHEETS,
            connector_id=self.config.connector_id,
            source_reference=f"sheets:{self.config.spreadsheet_id}/{self.config.range}",
            fetched_at=datetime.now(UTC),
            records=records,
            raw_pages=[payload],
        )

    def append_records(self, records: list[dict[str, Any]]) -> AdapterWriteResult:
        self.config.authorization.require("write")
        columns = self.config.columns or sorted({str(key) for row in records for key in row})
        if records and not columns:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "No exportable Google Sheets columns")
        rows = [[row.get(column) for column in columns] for row in records]
        payload = _request_json(
            self.executor,
            method="POST",
            url=(
                f"{self._values_url}:append?"
                + urlencode({"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"})
            ),
            token=_credential(self.config.token_env),
            policy=self.config.retry,
            payload={"majorDimension": "ROWS", "values": rows},
            sleep=self.sleep,
        )
        updates = payload.get("updates", {})
        accepted = len(records)
        if isinstance(updates, dict) and isinstance(updates.get("updatedRows"), int):
            accepted = min(int(updates["updatedRows"]), len(records))
        return AdapterWriteResult(
            connector=ConnectorKind.GOOGLE_SHEETS,
            connector_id=self.config.connector_id,
            target_reference=f"sheets:{self.config.spreadsheet_id}/{self.config.range}",
            written_at=datetime.now(UTC),
            requested_rows=len(records),
            accepted_rows=accepted,
        )


def build_collaboration_adapter(
    config: ConnectorConfig, *, executor: HttpExecutor | None = None
) -> CollaborationAdapter:
    """Build one official collaboration adapter from a validated config."""

    if isinstance(config, FeishuBitableConfig):
        return FeishuBitableAdapter(config, executor=executor)
    return GoogleSheetsAdapter(config, executor=executor)
