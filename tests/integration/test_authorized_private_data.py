from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.collaboration import CollaborationService
from video_account_distiller.models import (
    AudienceProfileSegment,
    AuthorizationGrant,
    AuthorizedExportManifest,
    ConnectorKind,
    MetricSnapshot,
    Platform,
)
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.io import atomic_write_json
from video_account_distiller.validation import validate_project


def _manifest(source: Path, *, entity: str) -> AuthorizedExportManifest:
    return AuthorizedExportManifest.model_validate(
        {
            "entity": entity,
            "platform": Platform.DOUYIN,
            "data_file": str(source),
            "data_sha256": sha256_file(source),
            "exported_at": datetime(2026, 7, 29, tzinfo=UTC),
            "authorization": AuthorizationGrant(
                grant_id="grant-private-data",
                connector=ConnectorKind.AUTHORIZED_EXPORT,
                confirmed_by="account-owner",
                confirmed_at=datetime(2026, 7, 29, tzinfo=UTC),
                scopes=["read"],
                source_reference="creator center export",
            ),
        }
    )


def _write_manifest(tmp_path: Path, source: Path, *, entity: str) -> Path:
    path = tmp_path / f"{entity}-manifest.json"
    atomic_write_json(path, _manifest(source, entity=entity).model_dump(mode="json"))
    return path


def test_authorized_creator_exports_preserve_provenance_and_unknowns(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    metrics = tmp_path / "creator-metrics.csv"
    metrics.write_text(
        "video_id,snapshot_at,展现量,平均播放时长,完播率,主页访问量,"
        "新增粉丝,点击量,线索数,成交金额\n"
        "private-video,2026-07-29T08:00:00Z,12000,18.5,62%,320,41,88,7,1999.5\n",
        encoding="utf-8-sig",
    )
    audience = tmp_path / "creator-audience.csv"
    audience.write_text(
        "account_id,snapshot_at,画像维度,人群分组,占比,样本数,导出版本\n"
        "private-account,2026-07-29T08:00:00Z,gender,female,62%,100,"
        "douyin-creator-profile/2026-07\n",
        encoding="utf-8-sig",
    )
    service = CollaborationService(project)
    metric_result = service.import_authorized_export(
        manifest_path=_write_manifest(tmp_path, metrics, entity="metrics")
    )
    audience_result = service.import_authorized_export(
        manifest_path=_write_manifest(
            tmp_path,
            audience,
            entity="audience_profiles",
        )
    )

    assert metric_result["receipt"]["data_source_tier"] == "authorized_private"
    assert metric_result["receipt"]["authorization_grant_id"] == "grant-private-data"
    assert audience_result["receipt"]["data_source_tier"] == "authorized_private"

    normalized = NormalizationService(project).normalize()
    assert normalized["counts"]["audience_profiles"] == 1

    metric = read_models(
        project.normalized_dir / "metric_snapshots.parquet",
        MetricSnapshot,
    )[0]
    assert metric.impressions == 12000
    assert metric.avg_watch_time_seconds == 18.5
    assert metric.completion_rate == 0.62
    assert metric.profile_visits == 320
    assert metric.follows_gained == 41
    assert metric.clicks == 88
    assert metric.leads == 7
    assert metric.revenue == 1999.5
    assert metric.orders is None

    segment = read_models(
        project.normalized_dir / "audience_profiles.parquet",
        AudienceProfileSegment,
    )[0]
    assert segment.dimension == "gender"
    assert segment.bucket == "female"
    assert segment.share == 0.62
    assert segment.audience_count is None

    with DuckDBStore(project.normalized_dir) as store:
        assert store.count("audience_profiles") == 1
    assert validate_project(project, persist=False).error_count == 0
