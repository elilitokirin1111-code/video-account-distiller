from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.obsidian import HUMAN_DIR_NAME
from video_account_distiller.knowledge.weknora import WeKnoraSyncService, _api_url
from video_account_distiller.storage.project import ProjectLayout


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._payload


class _Export:
    def __init__(self, _: ProjectLayout) -> None:
        pass

    def export_account(
        self,
        *,
        account_id: str,
        vault_path: str,
        max_video_analyses: int,
        max_export_bytes: int = 5_000_000,
    ) -> dict[str, str]:
        report_dir = Path(vault_path) / "account" / HUMAN_DIR_NAME
        report_dir.mkdir(parents=True)
        (report_dir / "report.md").write_text("# report", encoding="utf-8")
        return {"account_folder": "account"}


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost", "http://localhost/api/v1"),
        ("http://localhost/", "http://localhost/api/v1"),
        ("http://localhost/api/v1", "http://localhost/api/v1"),
        ("http://localhost/api/v1/", "http://localhost/api/v1"),
    ],
)
def test_weknora_api_url_accepts_root_or_full_api_url(
    base_url: str,
    expected: str,
) -> None:
    assert _api_url(base_url) == expected


def test_weknora_gateway_error_points_to_direct_backend(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(502, {}, "Bad Gateway"),
    )

    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).list_knowledge_bases(
            base_url="http://localhost/api/v1",
            api_key="sk-test",
        )

    assert exc_info.value.code is ErrorCode.ADAPTER_RESPONSE
    assert "127.0.0.1:8080" in exc_info.value.message


def test_weknora_scope_rejection_has_actionable_error(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    post_urls: list[str] = []

    def _reject_upload(url: str, *args: Any, **kwargs: Any) -> _Response:
        post_urls.append(url)
        return _Response(
            403,
            {},
            '{"error":{"code":1002,"message":"scope denied"},"success":false}',
        )

    monkeypatch.setattr("video_account_distiller.knowledge.weknora.ObsidianVaultExporter", _Export)
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(
            200,
            {
                "data": [
                    {"id": "kb-old", "name": "target"},
                    {"id": "kb-1", "name": "target"},
                ]
            },
            "",
        ),
    )
    monkeypatch.setattr(requests, "post", _reject_upload)

    result = WeKnoraSyncService(project).sync_account(
        account_id="account-id",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is False
    assert result["kb_id"] == "kb-1"
    assert result["error_code"] == "API_KEY_SCOPE_NOT_ALLOWED"
    assert "API Key" in str(result["message"])
    assert post_urls
    assert all("/knowledge-bases/kb-1/" in url for url in post_urls)


def test_weknora_upload_retries_after_async_delete_duplicate(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 409 duplicate_file right after an async delete must delete and retry."""
    deleted: list[str] = []
    upload_attempts: list[int] = []

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        if upload_attempts and not deleted:
            return _Response(
                200,
                {
                    "data": [
                        {
                            "id": "stale-doc",
                            "file_name": "report.md",
                            "channel": "distiller",
                            "metadata": {
                                "source": "video-account-distiller",
                                "account_id": "account-id",
                                "document_type": "account_operational",
                            },
                        }
                    ],
                    "total": 1,
                },
                "",
            )
        return _Response(
            200,
            {"data": [], "total": 0},
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(url: str, *args: Any, **kwargs: Any) -> _Response:
        upload_attempts.append(len(upload_attempts) + 1)
        if upload_attempts[-1] == 1:
            return _Response(
                409,
                {
                    "error": {"code": 1000, "message": "duplicate_file"},
                    "data": {"id": "stale-doc"},
                },
                "",
            )
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)
    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora._wait_for_duplicate_clear",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.ObsidianVaultExporter",
        _Export,
    )

    result = WeKnoraSyncService(project).sync_account(
        account_id="account-id",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["uploaded"]
    assert deleted == ["http://localhost:8080/api/v1/knowledge/stale-doc"]
    assert upload_attempts == [1, 2]


@pytest.mark.parametrize(
    "duplicate",
    [
        {
            "id": "manual-doc",
            "file_name": "report.md",
            "channel": "web",
            "metadata": {
                "source": "video-account-distiller",
                "account_id": "account-id",
                "document_type": "account_operational",
            },
        },
        {
            "id": "other-account-doc",
            "file_name": "report.md",
            "channel": "distiller",
            "metadata": {
                "source": "video-account-distiller",
                "account_id": "another-account",
                "document_type": "account_operational",
            },
        },
        {
            "id": "other-document-type",
            "file_name": "report.md",
            "channel": "distiller",
            "metadata": {
                "source": "video-account-distiller",
                "account_id": "account-id",
                "video_id": "vid_manual",
                "document_type": "creative_learning",
            },
        },
    ],
    ids=["manual-channel", "other-account", "other-document-type"],
)
def test_weknora_duplicate_conflict_never_deletes_unowned_document(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
    duplicate: dict[str, Any],
) -> None:
    deleted: list[str] = []
    upload_attempts: list[int] = []

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        if upload_attempts:
            return _Response(200, {"data": [duplicate], "total": 1}, "")
        return _Response(200, {"data": [], "total": 0}, "")

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(*args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        upload_attempts.append(len(upload_attempts) + 1)
        return _Response(
            409,
            {
                "error": {"code": 1000, "message": "duplicate_file"},
                "data": {"id": duplicate["id"]},
            },
            "",
        )

    monkeypatch.setattr("video_account_distiller.knowledge.weknora.ObsidianVaultExporter", _Export)
    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_account(
        account_id="account-id",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is False
    assert deleted == []
    assert upload_attempts == [1]
    assert any("为避免误删" in error for error in result["errors"])


def test_weknora_account_export_finishes_before_remote_documents_are_touched(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingExport:
        def __init__(self, _: ProjectLayout) -> None:
            pass

        def export_account(self, **kwargs: Any) -> dict[str, str]:
            del kwargs
            raise RuntimeError("local export failed")

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        pytest.fail("本地导出完成前不得读取或删除远端文档")

    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.ObsidianVaultExporter",
        _FailingExport,
    )
    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(
        requests,
        "delete",
        lambda *args, **kwargs: pytest.fail("本地导出失败后不得删除远端文档"),
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: pytest.fail("本地导出失败后不得上传文档"),
    )

    with pytest.raises(RuntimeError, match="local export failed"):
        WeKnoraSyncService(project).sync_account(
            account_id="account-id",
            base_url="http://localhost:8080",
            api_key="sk-test",
            kb_id="kb-1",
        )


def test_weknora_sync_replaces_only_distiller_owned_account_documents(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[str] = []
    uploaded: list[str] = []

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        return _Response(
            200,
            {
                "data": [
                    {
                        "id": "old-owned",
                        "file_name": "report.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "account-id",
                        },
                    },
                    {
                        "id": "manual-doc",
                        "file_name": "keep.md",
                        "channel": "web",
                        "metadata": {},
                    },
                    {
                        "id": "keep-video-knowledge",
                        "file_name": "知识提炼.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "account-id",
                            "video_id": "vid_keep",
                            "document_type": "video_knowledge",
                        },
                    },
                ],
                "total": 3,
            },
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(url: str, *args: Any, **kwargs: Any) -> _Response:
        uploaded.append(url)
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr("video_account_distiller.knowledge.weknora.ObsidianVaultExporter", _Export)
    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_account(
        account_id="account-id",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["replaced"] == ["report.md"]
    assert deleted == ["http://localhost:8080/api/v1/knowledge/old-owned"]
    assert len(uploaded) == 1


def test_weknora_account_operational_sync_includes_every_latest_creative_report(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_svd_fixture(project, "vid_creative")
    uploads: list[dict[str, Any]] = []
    deleted: list[str] = []
    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.read_models",
        lambda *args, **kwargs: [
            SimpleNamespace(
                video_id="vid_creative",
                account_id="acc_test",
                title="宴会/菜：当天现做？",
            )
        ],
    )

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        return _Response(
            200,
            {
                "data": [
                    {
                        "id": "old-account-creative",
                        "file_name": "vid_creative-creative-report.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                            "video_id": "vid_creative",
                            "document_type": "creative_learning",
                        },
                    },
                    {
                        "id": "old-single-creative",
                        "file_name": "single-video-distillation.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "video:vid_creative",
                            "video_id": "vid_creative",
                            "document_type": "creative_learning",
                        },
                    },
                    {
                        "id": "keep-video-knowledge",
                        "file_name": "酒店知识提炼.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                            "video_id": "vid_creative",
                            "document_type": "video_knowledge",
                        },
                    },
                ],
                "total": 3,
            },
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(url: str, *args: Any, **kwargs: Any) -> _Response:
        uploads.append(kwargs)
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr("video_account_distiller.knowledge.weknora.ObsidianVaultExporter", _Export)
    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_account(
        account_id="acc_test",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["creative_reports"] == 1
    assert result["uploaded_creative_reports"] == 1
    assert result["degraded_creative_reports"] == 0
    assert result["skipped"] == []
    assert deleted == [
        "http://localhost:8080/api/v1/knowledge/old-account-creative",
        "http://localhost:8080/api/v1/knowledge/old-single-creative",
    ]
    assert len(uploads) == 2
    account_report = next(item for item in uploads if item["files"]["file"][0] == "report.md")
    account_metadata = json.loads(account_report["data"]["metadata"])
    assert account_metadata["document_type"] == "account_operational"
    assert account_metadata["sync_scope"] == "account"
    creative = next(
        item
        for item in uploads
        if item["data"]["fileName"].endswith("/宴会菜：当天现做？｜创作拆解.md")
    )
    assert creative["files"]["file"][0] == "宴会菜：当天现做？｜创作拆解.md"
    metadata = json.loads(creative["data"]["metadata"])
    assert metadata["video_id"] == "vid_creative"
    assert metadata["video_title"] == "宴会/菜：当天现做？"
    assert metadata["document_type"] == "creative_learning"
    assert metadata["sync_scope"] == "account"


def test_weknora_account_sync_skips_degraded_creative_and_preserves_existing(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_svd_fixture(project, "vid_degraded", status="degraded")
    deleted: list[str] = []
    uploads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.read_models",
        lambda *args, **kwargs: [
            SimpleNamespace(
                video_id="vid_degraded",
                account_id="acc_test",
                title="模型失败时生成的旧报告",
            )
        ],
    )

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        return _Response(
            200,
            {
                "data": [
                    {
                        "id": "keep-complete-creative",
                        "file_name": "模型失败时生成的旧报告｜创作拆解.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                            "video_id": "vid_degraded",
                            "document_type": "creative_learning",
                        },
                    }
                ],
                "total": 1,
            },
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(*args: Any, **kwargs: Any) -> _Response:
        del args
        uploads.append(kwargs)
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr("video_account_distiller.knowledge.weknora.ObsidianVaultExporter", _Export)
    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_account(
        account_id="acc_test",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["creative_reports"] == 1
    assert result["uploaded_creative_reports"] == 0
    assert result["degraded_creative_reports"] == 1
    assert result["skipped"] == [
        {
            "video_id": "vid_degraded",
            "title": "模型失败时生成的旧报告",
            "reason": "最新创作拆解处于降级状态；请先修复模型配置并重新运行深度蒸馏",
        }
    ]
    assert deleted == []
    assert len(uploads) == 1
    assert uploads[0]["files"]["file"][0] == "report.md"


def test_weknora_requires_an_existing_visible_knowledge_base(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    post_calls: list[object] = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(
            200,
            {"data": [{"id": "kb-other", "name": "other"}]},
            "",
        ),
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: post_calls.append(args),
    )

    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).sync_account(
            account_id="account-id",
            base_url="http://localhost:8080",
            api_key="sk-test",
            kb_id="kb-missing",
        )

    assert exc_info.value.code is ErrorCode.SCHEMA_INVALID
    assert "not found" in exc_info.value.message
    assert post_calls == []


def _write_svd_fixture(
    project: ProjectLayout,
    video_id: str,
    *,
    status: str = "complete",
) -> None:
    from datetime import UTC, datetime

    from video_account_distiller.models import SingleVideoDistillation

    payload = {
        "distillation_id": "svd_test",
        "analysis_version": "1.0.0",
        "video_id": video_id,
        "account_id": "acc_test",
        "generated_at": "2026-01-01T00:00:00Z",
        "run_id": "run_test",
        "status": status,
        "text_analysis_id": "vta_test",
        "media_analysis_id": None,
        "craft_summary": {
            "analyzed_shots": 0,
            "ocr_observation_count": 0,
        },
        "topic": {
            "topic_statement": "一条选题拆解",
            "topic_angle": "痛点切入",
            "target_audience": ["前台"],
            "information_increment": "流程话术",
            "memory_point": "三步法",
            "topic_formula": "痛点+流程",
            "selection_notes": [],
        },
        "expression": {
            "opening_form": "口播提问开场",
            "subtitle_style": "大字标题",
            "packaging_features": [],
            "audio_expression": "口播",
            "editing_style": "快剪",
            "expression_notes": [],
        },
        "craft": {
            "shot_scale_profile": "特写",
            "camera_profile": "手持",
            "composition_profile": "居中",
            "lighting_profile": "自然光",
            "opening_technique": "特写开场",
            "pacing": "快节奏剪辑",
            "craft_notes": [],
        },
        "copy_checklist": {
            "topic": ["痛点切入"],
            "structure": ["三段式"],
            "craft": ["手持"],
            "expression": ["大字幕"],
            "avoid": [],
        },
        "deep_trace": None,
        "unknowns": [],
        "evidence_index_path": "analyses/videos/x/svd_test/evidence-index.json",
        "warnings_path": "analyses/videos/x/svd_test/warnings.json",
        "warnings": (
            [] if status == "complete" else ["deep_model_unavailable_deterministic_fallback"]
        ),
    }
    model = SingleVideoDistillation.model_validate(payload)
    directory = project.root / "analyses" / "videos" / video_id / "svd_test"
    directory.mkdir(parents=True)
    from video_account_distiller.utils.io import atomic_write_json, atomic_write_text

    atomic_write_json(directory / "distillation.json", model.model_dump(mode="json"))
    atomic_write_text(directory / "report.md", "# 单视频深度蒸馏\n\n选材拆解内容\n")
    atomic_write_json(directory / "evidence-index.json", {"artifact_id": "svd_test"})
    atomic_write_json(directory / "warnings.json", model.warnings)
    del datetime, UTC


def test_weknora_sync_video_distillation_requires_existing_svd(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(200, {"data": [{"id": "kb-1", "name": "t"}]}, ""),
    )
    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).sync_video_distillation(
            video_id="vid_missing",
            base_url="http://localhost:8080",
            api_key="sk-test",
            kb_id="kb-1",
        )
    assert exc_info.value.code is ErrorCode.INPUT_MISSING
    assert "--deep" in str(exc_info.value.details)


def test_weknora_sync_video_distillation_refuses_degraded_before_network(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_svd_fixture(project, "vid_degraded", status="degraded")
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: pytest.fail("降级产物不应访问 WeKnora"),
    )

    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).sync_video_distillation(
            video_id="vid_degraded",
            base_url="http://localhost:8080",
            api_key="sk-test",
            kb_id="kb-1",
        )

    assert exc_info.value.code is ErrorCode.MODEL_UNAVAILABLE
    assert "降级状态" in exc_info.value.message
    assert "重新运行深度蒸馏" in exc_info.value.message
    assert "重新运行" in str(exc_info.value.details["next"])


def test_weknora_sync_video_distillation_replaces_owned_video_documents(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_svd_fixture(project, "vid_local")
    deleted: list[str] = []
    uploaded_payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.read_models",
        lambda *args, **kwargs: [
            SimpleNamespace(
                video_id="vid_alpha",
                account_id="acc_test",
                title="前台：如何应对客诉？",
            ),
            SimpleNamespace(
                video_id="vid_local",
                account_id="acc_test",
                title="前台：如何应对客诉？",
            ),
        ],
    )

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        return _Response(
            200,
            {
                "data": [
                    {
                        "id": "old-video",
                        "file_name": "old.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "video_id": "vid_local",
                        },
                    },
                    {
                        "id": "other-video",
                        "file_name": "other.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "video_id": "vid_other",
                        },
                    },
                    {
                        "id": "manual",
                        "file_name": "keep.md",
                        "channel": "web",
                        "metadata": {},
                    },
                ],
                "total": 3,
            },
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(url: str, *args: Any, **kwargs: Any) -> _Response:
        uploaded_payloads.append(kwargs)
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_video_distillation(
        video_id="vid_local",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["replaced"] == ["old.md"]
    assert deleted == ["http://localhost:8080/api/v1/knowledge/old-video"]
    assert len(uploaded_payloads) == 1
    upload = uploaded_payloads[0]
    assert upload["data"]["fileName"] == "videos/vid_local/前台：如何应对客诉？（2）｜创作拆解.md"
    assert upload["files"]["file"][0] == "前台：如何应对客诉？（2）｜创作拆解.md"
    metadata = json.loads(upload["data"]["metadata"])
    assert metadata["video_id"] == "vid_local"
    assert metadata["video_title"] == "前台：如何应对客诉？"
    assert metadata["account_id"] == "acc_test"
    assert metadata["sync_scope"] == "video"
    assert upload["data"]["channel"] == "distiller"
    file_tuple = upload["files"]["file"]
    file_content = file_tuple[1].read() if hasattr(file_tuple[1], "read") else file_tuple[1]
    assert file_content.startswith(b"---")
    assert "单视频深度蒸馏" in file_content.decode("utf-8")


def _write_video_knowledge_fixture(
    project: ProjectLayout,
    video_id: str,
    *,
    status: str = "complete",
) -> None:
    from video_account_distiller.models import SingleVideoKnowledgeDistillation
    from video_account_distiller.utils.io import atomic_write_json, atomic_write_text

    payload = {
        "knowledge_id": "svk_test",
        "analysis_version": "1.0.0",
        "video_id": video_id,
        "account_id": "acc_test",
        "generated_at": "2026-01-01T00:00:00Z",
        "run_id": "run_test",
        "status": status,
        "knowledge": {
            "knowledge_title": "三个常见问题",
            "content_summary": "视频整理了三个问题。",
            "core_conclusions": ["先确认需求"],
            "knowledge_items": [],
            "limitations": ["未做外部事实核验"],
            "expression_note": {"summary": "清单式表达"},
        },
        "evidence_path": "analyses/videos/x/knowledge/svk_test/evidence.json",
        "warnings_path": "analyses/videos/x/knowledge/svk_test/warnings.json",
        "warnings": ["external_fact_check_not_performed"],
    }
    model = SingleVideoKnowledgeDistillation.model_validate(payload)
    directory = project.root / "analyses" / "videos" / video_id / "knowledge" / "svk_test"
    directory.mkdir(parents=True)
    atomic_write_json(directory / "knowledge.json", model.model_dump(mode="json"))
    atomic_write_text(directory / "knowledge.md", "# 三个常见问题\n")


def test_weknora_video_knowledge_does_not_delete_creative_document(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_video_knowledge_fixture(project, "vid_knowledge")
    deleted: list[str] = []
    uploads: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "video_account_distiller.knowledge.weknora.read_models",
        lambda *args, **kwargs: [
            SimpleNamespace(
                video_id="vid_knowledge",
                account_id="acc_test",
                title="酒店宴会菜的三个问题",
            )
        ],
    )

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        return _Response(
            200,
            {
                "data": [
                    {
                        "id": "old-knowledge",
                        "file_name": "video-knowledge.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "video_id": "vid_knowledge",
                            "document_type": "video_knowledge",
                        },
                    },
                    {
                        "id": "keep-creative",
                        "file_name": "single-video-distillation.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "video_id": "vid_knowledge",
                            "document_type": "creative_learning",
                        },
                    },
                ],
                "total": 2,
            },
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(*args: Any, **kwargs: Any) -> _Response:
        del args
        uploads.append(kwargs)
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_video_knowledge(
        video_id="vid_knowledge",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert deleted == ["http://localhost:8080/api/v1/knowledge/old-knowledge"]
    assert (
        uploads[0]["data"]["fileName"] == "videos/vid_knowledge/酒店宴会菜的三个问题｜知识提炼.md"
    )
    assert uploads[0]["files"]["file"][0] == "酒店宴会菜的三个问题｜知识提炼.md"
    metadata = json.loads(uploads[0]["data"]["metadata"])
    assert metadata["document_type"] == "video_knowledge"
    assert metadata["distillation_mode"] == "knowledge"
    assert metadata["knowledge_id"] == "svk_test"
    assert metadata["video_title"] == "酒店宴会菜的三个问题"
    assert metadata["account_id"] == "acc_test"
    assert metadata["sync_scope"] == "video"


def test_weknora_sync_video_knowledge_refuses_degraded_before_network(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_video_knowledge_fixture(project, "vid_degraded", status="degraded")
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: pytest.fail("降级产物不应访问 WeKnora"),
    )

    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).sync_video_knowledge(
            video_id="vid_degraded",
            base_url="http://localhost:8080",
            api_key="sk-test",
            kb_id="kb-1",
        )

    assert exc_info.value.code is ErrorCode.MODEL_UNAVAILABLE
    assert "降级状态" in exc_info.value.message
    assert "重新运行知识提炼" in exc_info.value.message
    assert "重新运行" in str(exc_info.value.details["next"])


def test_weknora_account_video_knowledge_syncs_subset_without_deleting_other_videos(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from video_account_distiller.models import AccountVideoKnowledgeManifest
    from video_account_distiller.utils.io import atomic_write_json, atomic_write_text

    manifest = AccountVideoKnowledgeManifest.model_validate(
        {
            "manifest_id": "avk_test",
            "manifest_version": "1.0.0",
            "account_id": "acc_test",
            "generated_at": "2026-01-01T00:00:00Z",
            "run_id": "run_test",
            "status": "degraded",
            "requested_count": 2,
            "eligible_count": 2,
            "completed_count": 1,
            "degraded_count": 1,
            "skipped_count": 0,
            "documents": [
                {
                    "video_id": "vid_knowledge",
                    "title": "三个常见问题",
                    "knowledge_id": "svk_test",
                    "status": "complete",
                    "source_path": "analyses/videos/vid_knowledge/knowledge/svk_test/knowledge.md",
                    "document_path": (
                        "knowledge/accounts/acc_test/video-knowledge/avk_test/"
                        "documents/三个常见问题.md"
                    ),
                },
                {
                    "video_id": "vid_degraded",
                    "title": "降级知识",
                    "knowledge_id": "svk_degraded",
                    "status": "degraded",
                    "source_path": "analyses/videos/vid_degraded/knowledge/svk/knowledge.md",
                    "document_path": (
                        "knowledge/accounts/acc_test/video-knowledge/avk_test/documents/降级知识.md"
                    ),
                },
            ],
        }
    )
    manifest_path = (
        project.root
        / "knowledge"
        / "accounts"
        / "acc_test"
        / "video-knowledge"
        / "avk_test"
        / "manifest.json"
    )
    atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
    document_path = project.root / manifest.documents[0].document_path
    atomic_write_text(document_path, "# 三个常见问题\n\n这是本次账号知识清单中的文档。\n")
    atomic_write_text(project.root / manifest.documents[1].document_path, "# 降级知识\n")
    deleted: list[str] = []
    uploads: list[dict[str, Any]] = []

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        if url.endswith("/knowledge-bases"):
            return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")
        return _Response(
            200,
            {
                "data": [
                    {
                        "id": "old-account-report",
                        "file_name": "账号运营报告.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                        },
                    },
                    {
                        "id": "old-video-knowledge",
                        "file_name": "video-knowledge.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                            "video_id": "vid_knowledge",
                            "document_type": "video_knowledge",
                        },
                    },
                    {
                        "id": "old-stale-video-knowledge",
                        "file_name": "stale-video-knowledge.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                            "video_id": "vid_not_in_latest_manifest",
                            "document_type": "video_knowledge",
                        },
                    },
                    {
                        "id": "keep-degraded-video-knowledge",
                        "file_name": "降级知识｜知识提炼.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_test",
                            "video_id": "vid_degraded",
                            "document_type": "video_knowledge",
                        },
                    },
                    {
                        "id": "keep-other-account-same-video",
                        "file_name": "另一个账号的知识提炼.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "acc_other",
                            "video_id": "vid_knowledge",
                            "document_type": "video_knowledge",
                        },
                    },
                    {
                        "id": "keep-creative-video",
                        "file_name": "single-video-distillation.md",
                        "channel": "distiller",
                        "metadata": {
                            "source": "video-account-distiller",
                            "account_id": "video:vid_knowledge",
                            "video_id": "vid_knowledge",
                            "document_type": "creative_learning",
                        },
                    },
                ],
                "total": 6,
            },
            "",
        )

    def _delete(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        deleted.append(url)
        return _Response(200, {"success": True}, "")

    def _post(*args: Any, **kwargs: Any) -> _Response:
        del args
        uploads.append(kwargs)
        return _Response(201, {"success": True}, "")

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(requests, "delete", _delete)
    monkeypatch.setattr(requests, "post", _post)

    result = WeKnoraSyncService(project).sync_account_video_knowledge(
        account_id="acc_test",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["document_type"] == "video_knowledge"
    assert result["manifest_id"] == "avk_test"
    assert deleted == [
        "http://localhost:8080/api/v1/knowledge/old-video-knowledge",
    ]
    assert all("old-stale-video-knowledge" not in url for url in deleted)
    assert all("keep-other-account-same-video" not in url for url in deleted)
    assert result["uploaded"] == [
        "accounts/acc_test/videos/vid_knowledge/三个常见问题｜知识提炼.md"
    ]
    assert result["skipped"] == [
        {
            "video_id": "vid_degraded",
            "title": "降级知识",
            "reason": "最新知识提炼处于降级状态；请先修复模型配置并重新运行知识提炼",
        }
    ]
    assert len(uploads) == 1
    upload = uploads[0]
    assert (
        upload["data"]["fileName"]
        == "accounts/acc_test/videos/vid_knowledge/三个常见问题｜知识提炼.md"
    )
    assert upload["files"]["file"][0] == "三个常见问题｜知识提炼.md"
    metadata = json.loads(upload["data"]["metadata"])
    assert metadata["account_id"] == "acc_test"
    assert metadata["video_id"] == "vid_knowledge"
    assert metadata["video_title"] == "三个常见问题"
    assert metadata["document_type"] == "video_knowledge"
    assert metadata["manifest_id"] == "avk_test"
    assert metadata["sync_scope"] == "account"
    file_tuple = upload["files"]["file"]
    file_content = file_tuple[1].read() if hasattr(file_tuple[1], "read") else file_tuple[1]
    assert "这是本次账号知识清单中的文档" in file_content.decode("utf-8")


def test_weknora_account_video_knowledge_skips_all_degraded_without_deleting(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from video_account_distiller.models import AccountVideoKnowledgeManifest
    from video_account_distiller.utils.io import atomic_write_json, atomic_write_text

    manifest = AccountVideoKnowledgeManifest.model_validate(
        {
            "manifest_id": "avk_degraded",
            "manifest_version": "1.0.0",
            "account_id": "acc_test",
            "generated_at": "2026-01-02T00:00:00Z",
            "run_id": "run_test",
            "status": "degraded",
            "requested_count": 1,
            "eligible_count": 1,
            "completed_count": 0,
            "degraded_count": 1,
            "skipped_count": 0,
            "documents": [
                {
                    "video_id": "vid_degraded",
                    "title": "残缺知识",
                    "knowledge_id": "svk_degraded",
                    "status": "degraded",
                    "source_path": "analyses/videos/vid_degraded/knowledge/svk/knowledge.md",
                    "document_path": (
                        "knowledge/accounts/acc_test/video-knowledge/avk_degraded/"
                        "documents/vid_degraded.md"
                    ),
                }
            ],
        }
    )
    manifest_path = (
        project.root
        / "knowledge"
        / "accounts"
        / "acc_test"
        / "video-knowledge"
        / "avk_degraded"
        / "manifest.json"
    )
    atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
    atomic_write_text(project.root / manifest.documents[0].document_path, "# 残缺知识\n")
    get_urls: list[str] = []

    def _get(url: str, *args: Any, **kwargs: Any) -> _Response:
        del args, kwargs
        get_urls.append(url)
        return _Response(200, {"data": [{"id": "kb-1", "name": "target"}]}, "")

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(
        requests,
        "delete",
        lambda *args, **kwargs: pytest.fail("没有完整新文档时不得删除旧文档"),
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: pytest.fail("降级文档不得上传"),
    )

    result = WeKnoraSyncService(project).sync_account_video_knowledge(
        account_id="acc_test",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["uploaded"] == []
    assert result["replaced"] == []
    assert result["skipped"] == [
        {
            "video_id": "vid_degraded",
            "title": "残缺知识",
            "reason": "最新知识提炼处于降级状态；请先修复模型配置并重新运行知识提炼",
        }
    ]
    assert get_urls == ["http://localhost:8080/api/v1/knowledge-bases"]
