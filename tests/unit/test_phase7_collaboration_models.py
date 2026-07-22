from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AuthorizationGrant,
    ConnectorKind,
    FeishuBitableConfig,
    TeamConfig,
    TeamMember,
    TeamRole,
)


def _grant(
    connector: ConnectorKind = ConnectorKind.FEISHU_BITABLE,
    *,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> AuthorizationGrant:
    source_reference = {
        ConnectorKind.FEISHU_BITABLE: "bitable:app/table",
        ConnectorKind.GOOGLE_SHEETS: "sheets:sheet-id/Sheet1!A:C",
        ConnectorKind.AUTHORIZED_EXPORT: "team approval",
    }[connector]
    return AuthorizationGrant.model_validate(
        {
            "grant_id": "grant-1",
            "connector": connector,
            "confirmed_by": "owner-1",
            "confirmed_at": "2026-07-20T00:00:00Z",
            "scopes": scopes or ["read", "write"],
            "source_reference": source_reference,
            "expires_at": expires_at,
        }
    )


def test_authorization_requires_scope_and_active_expiry() -> None:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    _grant(scopes=["read"], expires_at=now + timedelta(days=1)).require("read", now=now)

    with pytest.raises(DistillerError) as missing_scope:
        _grant(scopes=["read"]).require("write", now=now)
    assert missing_scope.value.code == ErrorCode.ADAPTER_AUTH

    with pytest.raises(DistillerError) as expired:
        _grant(expires_at=now - timedelta(seconds=1)).require("read", now=now)
    assert expired.value.code == ErrorCode.ADAPTER_AUTH

    with pytest.raises(ValidationError):
        AuthorizationGrant.model_validate(
            {
                "grant_id": "naive-time",
                "connector": "authorized-export",
                "confirmed_by": "owner-1",
                "confirmed_at": "2026-07-20T00:00:00",
                "scopes": ["read"],
                "source_reference": "offline export",
            }
        )


def test_connector_grant_and_team_references_are_strict() -> None:
    with pytest.raises(ValidationError):
        FeishuBitableConfig(
            connector_id="hotel-table",
            app_token="app",
            table_id="table",
            authorization=_grant(ConnectorKind.GOOGLE_SHEETS),
        )

    with pytest.raises(ValidationError):
        FeishuBitableConfig(
            connector_id="hotel-table",
            app_token="different-app",
            table_id="table",
            authorization=_grant(),
        )

    with pytest.raises(ValidationError):
        TeamConfig(
            team_id="team-1",
            name="hotel team",
            members=[
                TeamMember(
                    member_id="viewer",
                    role=TeamRole.VIEWER,
                    connector_ids=["missing"],
                )
            ],
            created_at=datetime.now(UTC),
        )
