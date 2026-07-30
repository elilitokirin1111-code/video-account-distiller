from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.collection.drift import TikHubDriftDetector
from video_account_distiller.collection.providers import (
    COMMENTS_PATH,
    POSTS_PATHS,
    PROFILE_PATH,
    RESOLVE_PATH,
)
from video_account_distiller.models import ProviderRawPage


def _page(endpoint: str, payload: dict[str, object]) -> ProviderRawPage:
    return ProviderRawPage(
        endpoint=endpoint,
        fetched_at=datetime.now(UTC),
        payload=payload,
    )


def test_documented_tikhub_fixtures_pass_drift_contract(fixtures_dir: Path) -> None:
    phase8 = fixtures_dir / "phase8"
    fixture_pages = [
        (RESOLVE_PATH, "resolve.json"),
        (PROFILE_PATH, "profile.json"),
        (POSTS_PATHS["web"], "posts-page-1.json"),
        (COMMENTS_PATH, "comments-video-1.json"),
    ]
    pages = [
        _page(endpoint, json.loads((phase8 / filename).read_text(encoding="utf-8")))
        for endpoint, filename in fixture_pages
    ]

    report = TikHubDriftDetector().evaluate(pages)

    assert report.ok is True
    assert report.status == "pass"
    assert report.issues == []
    assert len(report.schema_fingerprint) == 64
    assert report.endpoints[POSTS_PATHS["web"]] == 1


def test_tikhub_drift_reports_mapping_breaks_without_serializing_values() -> None:
    secret_value = "never-copy-provider-values"
    pages = [
        _page(RESOLVE_PATH, {"code": 200, "data": {"renamed_id": secret_value}}),
        _page(PROFILE_PATH, {"code": 200, "data": {"renamed_name": secret_value}}),
        _page(
            POSTS_PATHS["web"],
            {"code": 200, "data": {"renamed_items": [{"renamed_id": secret_value}]}},
        ),
    ]

    report = TikHubDriftDetector().evaluate(pages)
    serialized = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)

    assert report.ok is False
    assert report.status == "fail"
    assert {
        "resolve_account_id_missing",
        "profile_name_missing",
        "posts_list_missing",
    }.issubset({issue.code for issue in report.issues})
    assert secret_value not in serialized


def test_tikhub_drift_allows_additive_fields_and_warns_on_optional_counts() -> None:
    pages = [
        _page(RESOLVE_PATH, {"data": {"sec_uid": "account", "new_field": {"x": 1}}}),
        _page(PROFILE_PATH, {"data": {"user": {"nickname": "hotel", "new": True}}}),
        _page(
            POSTS_PATHS["app-v3"],
            {
                "data": {
                    "items": [
                        {
                            "id": "video-1",
                            "statistics": {"play_count": 1},
                            "new_provider_field": "allowed",
                        }
                    ]
                }
            },
        ),
    ]

    report = TikHubDriftDetector().evaluate(pages)

    assert report.ok is True
    assert report.status == "warn"
    assert [issue.code for issue in report.issues] == ["profile_followers_missing"]
