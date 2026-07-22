from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.ingestion import ImportService
from video_account_distiller.metrics import MetricsService
from video_account_distiller.models import Platform
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.transcripts import TranscriptImportService
from video_account_distiller.utils.ids import stable_id

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def project(tmp_path: Path) -> ProjectLayout:
    layout, _ = ProjectLayout.initialize(tmp_path / "project", project_name="test-project")
    return layout


@pytest.fixture
def normalized_project(project: ProjectLayout, fixtures_dir: Path) -> ProjectLayout:
    service = ImportService(project)
    normal = fixtures_dir / "normal"
    service.import_file(entity="accounts", source=normal / "accounts.csv", platform=Platform.DOUYIN)
    service.import_file(entity="videos", source=normal / "videos.csv", platform=Platform.DOUYIN)
    service.import_file(entity="metrics", source=normal / "metrics.csv", platform=Platform.DOUYIN)
    service.import_file(
        entity="comments", source=normal / "comments.json", platform=Platform.DOUYIN
    )
    NormalizationService(project).normalize()
    return project


@pytest.fixture
def phase2_project(project: ProjectLayout, fixtures_dir: Path) -> ProjectLayout:
    service = ImportService(project)
    phase2 = fixtures_dir / "phase2"
    service.import_file(entity="accounts", source=phase2 / "accounts.csv", platform=Platform.DOUYIN)
    service.import_file(entity="videos", source=phase2 / "videos.csv", platform=Platform.DOUYIN)
    service.import_file(entity="metrics", source=phase2 / "metrics.csv", platform=Platform.DOUYIN)
    NormalizationService(project).normalize()
    MetricsService(project).calculate(account_id=stable_id("acc_", "douyin", "phase2-hotel"))
    return project


@pytest.fixture
def phase3_project(phase2_project: ProjectLayout, fixtures_dir: Path) -> ProjectLayout:
    video_id = stable_id("vid_", "douyin", "p2-01")
    TranscriptImportService(phase2_project).import_file(
        video_id=video_id,
        source=fixtures_dir / "phase3" / "hotel-video.srt",
        language="zh-CN",
    )
    NormalizationService(phase2_project).normalize()
    return phase2_project
