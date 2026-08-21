from __future__ import annotations

import json
from pathlib import Path
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
        # Knowledge listing: report no distiller-owned docs (nothing to delete),
        # and after the duplicate-record delete the old id is gone.
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
                ],
                "total": 2,
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


def _write_svd_fixture(project: ProjectLayout, video_id: str) -> None:
    from datetime import UTC, datetime

    from video_account_distiller.models import SingleVideoDistillation

    payload = {
        "distillation_id": "svd_test",
        "analysis_version": "1.0.0",
        "video_id": video_id,
        "account_id": "acc_test",
        "generated_at": "2026-01-01T00:00:00Z",
        "run_id": "run_test",
        "status": "degraded",
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
        "warnings": ["deep_model_unavailable_deterministic_fallback"],
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


def test_weknora_sync_video_distillation_replaces_owned_video_documents(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_svd_fixture(project, "vid_local")
    deleted: list[str] = []
    uploaded_payloads: list[dict[str, Any]] = []

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
    assert upload["data"]["fileName"] == "videos/vid_local/single-video-distillation.md"
    metadata = json.loads(upload["data"]["metadata"])
    assert metadata["video_id"] == "vid_local"
    assert upload["data"]["channel"] == "distiller"
    file_tuple = upload["files"]["file"]
    file_content = file_tuple[1].read() if hasattr(file_tuple[1], "read") else file_tuple[1]
    assert file_content.startswith(b"---")
    assert "单视频深度蒸馏" in file_content.decode("utf-8")


def _write_video_knowledge_fixture(project: ProjectLayout, video_id: str) -> None:
    from video_account_distiller.models import SingleVideoKnowledgeDistillation
    from video_account_distiller.utils.io import atomic_write_json, atomic_write_text

    payload = {
        "knowledge_id": "svk_test",
        "analysis_version": "1.0.0",
        "video_id": video_id,
        "account_id": "acc_test",
        "generated_at": "2026-01-01T00:00:00Z",
        "run_id": "run_test",
        "status": "degraded",
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

    monkeypatch.setattr(requests, "get", _get)
    monkeypatch.setattr(
        requests,
        "delete",
        lambda url, *args, **kwargs: deleted.append(url) or _Response(200, {"success": True}, ""),
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: uploads.append(kwargs) or _Response(201, {"success": True}, ""),
    )

    result = WeKnoraSyncService(project).sync_video_knowledge(
        video_id="vid_knowledge",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert deleted == ["http://localhost:8080/api/v1/knowledge/old-knowledge"]
    metadata = json.loads(uploads[0]["data"]["metadata"])
    assert metadata["document_type"] == "video_knowledge"
    assert metadata["distillation_mode"] == "knowledge"
    assert metadata["knowledge_id"] == "svk_test"


def test_weknora_account_video_knowledge_syncs_manifest_documents_individually(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from video_account_distiller.models import AccountVideoKnowledgeManifest
    from video_account_distiller.utils.io import atomic_write_json

    manifest = AccountVideoKnowledgeManifest.model_validate(
        {
            "manifest_id": "avk_test",
            "manifest_version": "1.0.0",
            "account_id": "acc_test",
            "generated_at": "2026-01-01T00:00:00Z",
            "run_id": "run_test",
            "status": "degraded",
            "requested_count": 1,
            "eligible_count": 1,
            "completed_count": 0,
            "degraded_count": 1,
            "skipped_count": 0,
            "documents": [
                {
                    "video_id": "vid_knowledge",
                    "title": "三个常见问题",
                    "knowledge_id": "svk_test",
                    "status": "degraded",
                    "source_path": "analyses/videos/vid_knowledge/knowledge/svk_test/knowledge.md",
                    "document_path": (
                        "knowledge/accounts/acc_test/video-knowledge/avk_test/"
                        "documents/vid_knowledge.md"
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
        / "avk_test"
        / "manifest.json"
    )
    atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
    calls: list[str] = []
    service = WeKnoraSyncService(project)

    def _sync(**kwargs: Any) -> dict[str, Any]:
        calls.append(str(kwargs["video_id"]))
        return {
            "ok": True,
            "kb_name": "target",
            "uploaded": [f"videos/{kwargs['video_id']}/video-knowledge.md"],
            "replaced": [],
            "errors": [],
        }

    monkeypatch.setattr(service, "sync_video_knowledge", _sync)
    result = service.sync_account_video_knowledge(
        account_id="acc_test",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is True
    assert result["document_type"] == "video_knowledge"
    assert result["manifest_id"] == "avk_test"
    assert calls == ["vid_knowledge"]
    assert result["uploaded"] == ["videos/vid_knowledge/video-knowledge.md"]
