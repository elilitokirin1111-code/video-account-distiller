from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import video_account_distiller.distillation.account_knowledge as account_knowledge_module
from video_account_distiller.distillation.account_knowledge import AccountVideoKnowledgeService
from video_account_distiller.models import Platform, Video
from video_account_distiller.storage.parquet import write_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.filenames import (
    MAX_DOCUMENT_STEM_LENGTH,
    readable_document_stem,
    unique_document_stem,
)
from video_account_distiller.utils.io import atomic_write_text


def test_title_document_stem_keeps_readable_title_and_removes_unsafe_characters() -> None:
    stem = readable_document_stem('家装/投放：怎么选？* "完整指南"', "vid_fallback")

    assert stem == "家装投放：怎么选？ 完整指南"
    assert "/" not in stem
    assert "*" not in stem
    assert '"' not in stem


def test_title_document_stem_handles_duplicates_reserved_names_and_length() -> None:
    used: set[str] = set()

    first = unique_document_stem("同名视频", "vid_1", used)
    second = unique_document_stem("同名视频", "vid_2", used)
    reserved = unique_document_stem("CON", "vid_3", used)
    long_name = unique_document_stem("标题" * 100, "vid_4", used)

    assert first == "同名视频"
    assert second == "同名视频（2）"
    assert reserved == "CON_视频"
    assert len(long_name) == MAX_DOCUMENT_STEM_LENGTH


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("CON.txt", "CON_视频.txt"),
        ("COM1.backup", "COM1_视频.backup"),
        ("NUL.anything", "NUL_视频.anything"),
        ("CONIN$", "CONIN$_视频"),
        ("CONOUT$.log", "CONOUT$_视频.log"),
    ],
)
def test_title_document_stem_handles_windows_device_names_with_extensions(
    title: str,
    expected: str,
) -> None:
    assert readable_document_stem(title, "未命名视频") == expected


class _StableKnowledgeService:
    """Return one stable artifact so only the normalized title changes."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def distill(self, *, video_id: str, **_: Any) -> dict[str, Any]:
        source = (
            self.project.root
            / "analyses"
            / "videos"
            / video_id
            / "knowledge"
            / "svk_stable"
            / "knowledge.md"
        )
        atomic_write_text(source, "# 固定知识内容\n")
        return {
            "knowledge": {
                "knowledge_id": "svk_stable",
                "analysis_version": "1.0.0",
                "video_id": video_id,
                "account_id": "acc_title_cache",
                "generated_at": "2026-09-03T00:00:00Z",
                "run_id": "run_stable",
                "status": "complete",
                "knowledge": {
                    "knowledge_title": "固定知识标题",
                    "content_summary": "固定的视频知识摘要。",
                },
                "evidence_path": "evidence.json",
                "warnings_path": "warnings.json",
            },
            "outputs": [self.project.relative(source)],
        }


class _BlankTitleKnowledgeService(_StableKnowledgeService):
    def distill(self, *, video_id: str, **kwargs: Any) -> dict[str, Any]:
        result = super().distill(video_id=video_id, **kwargs)
        result["knowledge"]["knowledge"]["knowledge_title"] = "   "
        return result


class _ChangingKnowledgeService(_StableKnowledgeService):
    revision = 0

    def distill(self, *, video_id: str, **kwargs: Any) -> dict[str, Any]:
        result = super().distill(video_id=video_id, **kwargs)
        result["knowledge"]["status"] = "degraded" if self.revision == 0 else "complete"
        result["knowledge"]["generated_at"] = (
            "2026-09-03T00:00:00Z" if self.revision == 0 else "2026-09-03T00:01:00Z"
        )
        return result


def _video_with_title(title: str | None) -> Video:
    return Video(
        record_id="rec_title_cache",
        source_platform=Platform.DOUYIN,
        source_type="test",
        source_record_id="source_title_cache",
        run_id="run_title_cache",
        raw_hash="0" * 64,
        video_id="vid_title_cache",
        account_id="acc_title_cache",
        platform=Platform.DOUYIN,
        platform_video_id="platform_title_cache",
        title=title,
    )


def test_empty_source_and_knowledge_titles_use_human_fallback(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_models(project.normalized_dir / "videos.parquet", [_video_with_title(None)])
    monkeypatch.setattr(
        account_knowledge_module,
        "_latest_text_analysis",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        account_knowledge_module,
        "SingleVideoKnowledgeService",
        _BlankTitleKnowledgeService,
    )

    result = AccountVideoKnowledgeService(project).distill(
        account_id="acc_title_cache",
        provider="none",
    )
    document = result["manifest"]["documents"][0]

    assert document["title"] == "未命名视频"
    assert Path(document["document_path"]).name == "未命名视频.md"
    assert document["video_id"] == "vid_title_cache"


def test_title_change_invalidates_manifest_and_cached_outputs_follow_manifest(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    videos_path = project.normalized_dir / "videos.parquet"
    monkeypatch.setattr(
        account_knowledge_module,
        "_latest_text_analysis",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        account_knowledge_module,
        "SingleVideoKnowledgeService",
        _StableKnowledgeService,
    )
    service = AccountVideoKnowledgeService(project)

    write_models(videos_path, [_video_with_title("旧标题")])
    first = service.distill(account_id="acc_title_cache", provider="none")
    first_manifest = first["manifest"]
    assert Path(first_manifest["documents"][0]["document_path"]).name == "旧标题.md"

    write_models(videos_path, [_video_with_title("修正后的标题")])
    second = service.distill(account_id="acc_title_cache", provider="none")
    second_manifest = second["manifest"]
    second_document_path = second_manifest["documents"][0]["document_path"]

    assert second["already_generated"] is False
    assert second_manifest["manifest_id"] != first_manifest["manifest_id"]
    assert Path(second_document_path).name == "修正后的标题.md"
    assert (project.root / second_document_path).is_file()

    cached = service.distill(account_id="acc_title_cache", provider="none")
    manifest_root = Path(second_document_path).parent.parent
    assert cached["already_generated"] is True
    assert cached["manifest"]["manifest_id"] == second_manifest["manifest_id"]
    assert cached["outputs"] == [
        (manifest_root / "manifest.json").as_posix(),
        (manifest_root / "README.md").as_posix(),
        second_document_path,
    ]


def test_child_knowledge_refresh_invalidates_cached_account_manifest(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_models(
        project.normalized_dir / "videos.parquet",
        [_video_with_title("状态刷新")],
    )
    monkeypatch.setattr(
        account_knowledge_module,
        "_latest_text_analysis",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        account_knowledge_module,
        "SingleVideoKnowledgeService",
        _ChangingKnowledgeService,
    )
    service = AccountVideoKnowledgeService(project)

    _ChangingKnowledgeService.revision = 0
    first = service.distill(account_id="acc_title_cache", provider="none")
    assert first["manifest"]["status"] == "degraded"

    _ChangingKnowledgeService.revision = 1
    second = service.distill(account_id="acc_title_cache", provider="none")

    assert second["already_generated"] is False
    assert second["manifest"]["status"] == "complete"
    assert second["manifest"]["manifest_id"] != first["manifest"]["manifest_id"]
