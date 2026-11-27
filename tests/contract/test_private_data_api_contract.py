from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from video_account_distiller.api.app import create_app
from video_account_distiller.models import (
    AuthorizationGrant,
    AuthorizedExportManifest,
    ConnectorKind,
    Platform,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file

pytestmark = pytest.mark.enable_socket


def _json(response: Any) -> dict[str, Any]:
    payload: Any = response.json()
    assert isinstance(payload, dict)
    return payload


def test_authorized_wide_profile_upload_and_source_filtered_browser(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "creator-audience.csv"
    data_path.write_text(
        "account_id,snapshot_at,导出版本,女性粉丝占比,男性粉丝占比,样本数\n"
        "creator,2026-07-29T08:00:00Z,douyin-creator-profile/2026-07,62%,38,100\n",
        encoding="utf-8-sig",
    )
    manifest = AuthorizedExportManifest(
        entity="audience_profiles",
        platform=Platform.DOUYIN,
        data_file=data_path.name,
        data_sha256=sha256_file(data_path),
        exported_at=datetime(2026, 7, 29, tzinfo=UTC),
        authorization=AuthorizationGrant(
            grant_id="grant-api-private",
            connector=ConnectorKind.AUTHORIZED_EXPORT,
            confirmed_by="account-owner",
            confirmed_at=datetime(2026, 7, 29, tzinfo=UTC),
            scopes=["read"],
            source_reference="creator center export",
        ),
    )
    manifest_bytes = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
    ).encode("utf-8")
    encoded = quote(project.root.as_posix(), safe="")

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        invalid_manifest = manifest.model_copy(update={"data_sha256": "0" * 64})
        rejected = client.post(
            f"/api/projects/{encoded}/import/authorized-export",
            files={
                "manifest": (
                    "manifest.json",
                    json.dumps(invalid_manifest.model_dump(mode="json")).encode("utf-8"),
                    "application/json",
                ),
                "data_file": (data_path.name, data_path.read_bytes(), "text/csv"),
            },
        )
        assert rejected.status_code == 409
        assert _json(rejected)["error"]["code"] == "E_RAW_INTEGRITY"

        imported = client.post(
            f"/api/projects/{encoded}/import/authorized-export",
            files={
                "manifest": ("manifest.json", manifest_bytes, "application/json"),
                "data_file": (data_path.name, data_path.read_bytes(), "text/csv"),
            },
        )
        assert imported.status_code == 200
        imported_payload = _json(imported)
        assert imported_payload["ok"] is True
        assert imported_payload["receipt"]["data_source_tier"] == "authorized_private"
        assert imported_payload["quality"]["stats"] == {
            "input_rows": 1,
            "expanded_rows": 2,
            "accepted_rows": 2,
            "rejected_rows": 0,
            "duplicate_rows": 0,
        }

        normalized = client.post(f"/api/projects/{encoded}/normalize")
        assert normalized.status_code == 200

        private_rows = client.get(
            f"/api/projects/{encoded}/data",
            params={
                "table": "audience_profiles",
                "source_tier": "authorized_private",
            },
        )
        assert private_rows.status_code == 200, private_rows.text
        rows_payload = _json(private_rows)["data"]
        assert rows_payload["total"] == 2
        assert {row["data_source_tier"] for row in rows_payload["rows"]} == {"authorized_private"}
        assert {
            (row["dimension"], row["bucket"], row["share"]) for row in rows_payload["rows"]
        } == {
            ("gender", "female", 0.62),
            ("gender", "male", 0.38),
        }

        public_rows = client.get(
            f"/api/projects/{encoded}/data",
            params={"table": "audience_profiles", "source_tier": "public"},
        )
        assert public_rows.status_code == 200
        assert _json(public_rows)["data"]["total"] == 0

        history = client.get(
            f"/api/projects/{encoded}/imports",
            params={"source_tier": "authorized_private"},
        )
        assert history.status_code == 200
        history_payload = _json(history)["data"]
        assert history_payload["count"] == 1
        assert history_payload["receipts"][0]["authorization_grant_id"] == "grant-api-private"
