"""One-way Distiller-to-WeKnora knowledge base synchronization."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.obsidian import (
    HUMAN_DIR_NAME,
    ObsidianVaultExporter,
)
from video_account_distiller.models import (
    AccountVideoKnowledgeManifest,
    SingleVideoDistillation,
    SingleVideoKnowledgeDistillation,
    Video,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.filenames import (
    readable_document_stem,
    unique_document_stem,
)
from video_account_distiller.utils.io import read_json

DEFAULT_WEKNORA_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_WEKNORA_KB_NAME = "视频账号蒸馏"


def _video_document_name(
    title: str | None,
    *,
    document_label: str,
    used_stems: set[str] | None = None,
) -> str:
    """Build a title-first display name while keeping IDs out of the visible filename."""

    fallback = "未命名视频"
    stem = (
        unique_document_stem(title, fallback, used_stems)
        if used_stems is not None
        else readable_document_stem(title, fallback)
    )
    return f"{stem}｜{document_label}.md"


def _creative_video_title(distillation: SingleVideoDistillation) -> str | None:
    if distillation.executive_summary is not None:
        title = distillation.executive_summary.one_sentence.strip()
        if title:
            return title
    title = distillation.topic.topic_statement.strip()
    return title or None


def _api_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.lower().endswith("/api/v1"):
        return normalized
    return normalized + "/api/v1"


def _wait_for_duplicate_clear(
    api: str,
    headers: dict[str, str],
    kb_id: str,
    knowledge_id: str,
    *,
    timeout_seconds: float = 60.0,
    sleep: Any = time.sleep,
) -> bool:
    """Poll the knowledge list until an asynchronously-deleted document is gone.

    WeKnora's DELETE is a background task ("Delete task submitted"), so an
    immediate re-upload of the same file name races the deletion and fails
    with HTTP 409 ``duplicate_file``. Wait for the old record to disappear
    from the listing before retrying the upload.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{api}/knowledge-bases/{kb_id}/knowledge",
                headers=headers,
                params={"page": 1, "page_size": 100},
                timeout=30,
            )
        except requests.RequestException:
            sleep(2.0)
            continue
        if not response.ok:
            sleep(2.0)
            continue
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(items, list) and not any(
            str(item.get("id") or "") == knowledge_id for item in items if isinstance(item, dict)
        ):
            return True
        sleep(2.0)
    return False


def _knowledge_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            return {}
    return metadata if isinstance(metadata, dict) else {}


def _find_knowledge_item(
    api: str,
    headers: dict[str, str],
    kb_id: str,
    knowledge_id: str,
) -> dict[str, Any] | None:
    """Look up one knowledge item without trusting a 409 response's ownership claim."""

    page = 1
    while True:
        try:
            response = requests.get(
                f"{api}/knowledge-bases/{kb_id}/knowledge",
                headers=headers,
                params={"page": page, "page_size": 100},
                timeout=30,
            )
        except requests.RequestException:
            return None
        if not response.ok:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "") == knowledge_id:
                return item
        total = int(payload.get("total") or page * 100) if isinstance(payload, dict) else 0
        if page * 100 >= total or len(items) < 100:
            return None
        page += 1


def _is_owned_duplicate(
    item: dict[str, Any],
    *,
    account_id: str,
    metadata_extra: dict[str, Any] | None,
) -> bool:
    """Only authorize replacement of the same Distiller-owned logical document."""

    metadata = _knowledge_metadata(item)
    if item.get("channel") != "distiller" or metadata.get("source") != "video-account-distiller":
        return False

    expected = metadata_extra or {}
    expected_video_id = str(expected.get("video_id") or "").strip()
    actual_video_id = str(metadata.get("video_id") or "").strip()
    allowed_account_ids = {account_id}
    if expected_video_id:
        allowed_account_ids.add(f"video:{expected_video_id}")
    if str(metadata.get("account_id") or "").strip() not in allowed_account_ids:
        return False
    if expected_video_id != actual_video_id:
        return False

    expected_type = str(expected.get("document_type") or "").strip()
    actual_type = str(metadata.get("document_type") or "").strip()
    if expected_type == actual_type:
        return True
    return not actual_type and expected_type in {"account_operational", "creative_learning"}


def _upload_markdown(
    api: str,
    headers: dict[str, str],
    kb_id: str,
    path: Path,
    relative_name: str,
    account_id: str,
    uploaded: list[str],
    errors: list[str],
    upload_name: str | None = None,
    metadata_extra: dict[str, Any] | None = None,
    content: bytes | None = None,
) -> bool:
    """Upload one markdown report, retrying after an async-delete race.

    WeKnora deletes documents asynchronously; if an old document with the
    same ``fileName`` was just deleted, the immediate re-upload can still
    collide with the not-yet-removed record and return HTTP 409
    ``duplicate_file``. In that case, verify that the colliding record is the
    same account's Distiller-owned logical document before deleting it, wait
    for it to disappear, and retry once.
    """
    display_name = upload_name or path.name
    metadata = {
        "source": "video-account-distiller",
        "account_id": account_id,
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    metadata_json = json.dumps(metadata, ensure_ascii=False)

    def _attempt() -> requests.Response:
        body = content if content is not None else path.read_bytes()
        return requests.post(
            f"{api}/knowledge-bases/{kb_id}/knowledge/file",
            headers=headers,
            files={"file": (display_name, body, "text/markdown")},
            data={
                "fileName": relative_name,
                "metadata": metadata_json,
                "channel": "distiller",
            },
            timeout=180,
        )

    try:
        response = _attempt()
    except requests.RequestException as exc:
        errors.append(f"{path.name}: {exc}")
        return False
    if response.status_code in {200, 201, 202}:
        uploaded.append(relative_name)
        return True
    if response.status_code == 409:
        try:
            duplicate = response.json()
        except ValueError:
            duplicate = {}
        duplicate_data = duplicate.get("data") if isinstance(duplicate, dict) else None
        knowledge_id = (
            str(duplicate_data.get("id") or "").strip() if isinstance(duplicate_data, dict) else ""
        )
        duplicate_item = (
            _find_knowledge_item(api, headers, kb_id, knowledge_id) if knowledge_id else None
        )
        if duplicate_item is not None and _is_owned_duplicate(
            duplicate_item,
            account_id=account_id,
            metadata_extra=metadata_extra,
        ):
            try:
                delete_response = requests.delete(
                    f"{api}/knowledge/{knowledge_id}",
                    headers=headers,
                    timeout=60,
                )
                if delete_response.ok:
                    if not _wait_for_duplicate_clear(api, headers, kb_id, knowledge_id):
                        errors.append(f"{path.name}: 等待旧的同名文档删除超时，请稍后重试")
                        return False
                else:
                    errors.append(
                        f"{path.name}: 删除当前账号的旧同名文档失败，"
                        f"HTTP {delete_response.status_code}"
                    )
                    return False
            except requests.RequestException:
                errors.append(f"{path.name}: 删除当前账号的旧同名文档失败，请稍后重试")
                return False
        else:
            errors.append(
                f"{path.name}: WeKnora 已存在同名文档，但无法确认其属于当前账号的"
                " Distiller 文档；为避免误删，已保留原文档并取消上传"
            )
            return False
        try:
            retry = _attempt()
        except requests.RequestException as exc:
            errors.append(f"{path.name}: {exc}")
            return False
        if retry.status_code in {200, 201, 202}:
            uploaded.append(relative_name)
            return True
        errors.append(f"{path.name}: HTTP {retry.status_code} {retry.text[:200]}")
        return False
    errors.append(f"{path.name}: HTTP {response.status_code} {response.text[:200]}")
    return False


class WeKnoraSyncService:
    """Export the human-readable analysis reports and upload them to WeKnora."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def _video_titles(self, account_id: str) -> dict[str, str]:
        """Load human titles once; stable video IDs remain metadata and storage keys."""

        return {
            video.video_id: video.title.strip()
            for video in read_models(self.project.normalized_dir / "videos.parquet", Video)
            if video.account_id == account_id and video.title and video.title.strip()
        }

    def _video_document_names(
        self,
        account_id: str,
        *,
        document_label: str,
        fallback_titles: dict[str, str | None],
    ) -> dict[str, tuple[str, str]]:
        """Assign title-first names deterministically across an account's videos.

        Sorting by the stable backend ID makes duplicate-title suffixes identical
        whether documents are uploaded one at a time or as an account batch. The
        ID itself remains metadata/folder state and is never added to the basename.
        """

        titles = self._video_titles(account_id)
        for video_id, fallback_title in fallback_titles.items():
            if video_id in titles:
                continue
            normalized = (fallback_title or "").strip()
            titles[video_id] = normalized or "未命名视频"

        used_stems: set[str] = set()
        names: dict[str, tuple[str, str]] = {}
        for video_id in sorted(titles):
            title = titles[video_id]
            names[video_id] = (
                title,
                _video_document_name(
                    title,
                    document_label=document_label,
                    used_stems=used_stems,
                ),
            )
        return names

    def list_knowledge_bases(
        self,
        *,
        base_url: str = DEFAULT_WEKNORA_BASE_URL,
        api_key: str,
    ) -> list[dict[str, str]]:
        if not base_url.strip():
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "WeKnora base URL is required")
        if not api_key.strip():
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "WeKnora API Key is required",
                details={"next": "在 WeKnora API 集成页面获取 API Key"},
            )
        api = _api_url(base_url)
        headers = {"X-API-Key": api_key.strip()}
        response = requests.get(
            f"{api}/knowledge-bases",
            headers=headers,
            timeout=30,
        )
        if response.status_code == 401:
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "WeKnora API Key rejected (401)",
            )
        if response.status_code == 502:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "WeKnora gateway returned HTTP 502; for local Docker use the direct backend "
                "address http://127.0.0.1:8080",
            )
        if not response.ok:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                f"WeKnora knowledge-base list failed: HTTP {response.status_code}",
            )
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "WeKnora knowledge-base list returned an invalid response",
            )
        knowledge_bases: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            kb_id = str(item.get("id") or "").strip()
            kb_name = str(item.get("name") or "").strip()
            if kb_id and kb_name:
                knowledge_bases.append(
                    {
                        "id": kb_id,
                        "name": kb_name,
                        "type": str(item.get("type") or ""),
                    }
                )
        return sorted(knowledge_bases, key=lambda item: (item["name"], item["id"]))

    def sync_account(
        self,
        *,
        account_id: str,
        base_url: str = DEFAULT_WEKNORA_BASE_URL,
        api_key: str,
        kb_id: str,
        max_video_analyses: int = 10,
    ) -> dict[str, Any]:
        selected_kb_id = kb_id.strip()
        if not selected_kb_id:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora knowledge base ID is required",
            )
        knowledge_bases = self.list_knowledge_bases(base_url=base_url, api_key=api_key)
        target = next(
            (item for item in knowledge_bases if item["id"] == selected_kb_id),
            None,
        )
        if target is None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora target knowledge base was not found or is not visible to this API Key",
                details={
                    "kb_id": selected_kb_id,
                    "next": "重新读取该 API Key 可访问的知识库并选择目标库。",
                },
            )
        kb_name = target["name"]
        headers = {"X-API-Key": api_key.strip()}
        api = _api_url(base_url)
        replaced: list[str] = []
        errors: list[str] = []
        creative_candidates: list[tuple[SingleVideoDistillation, Path]] = []
        for video_root in sorted((self.project.root / "analyses" / "videos").glob("*")):
            if not video_root.is_dir():
                continue
            selected = self._latest_video_distillation(video_root.name)
            if selected is None or selected[0].account_id != account_id:
                continue
            report_path = selected[1].parent / "report.md"
            if report_path.is_file():
                creative_candidates.append((selected[0], report_path))
        creative_names = self._video_document_names(
            account_id,
            document_label="创作拆解",
            fallback_titles={
                item.video_id: _creative_video_title(item) for item, _path in creative_candidates
            },
        )
        creative_documents: list[tuple[SingleVideoDistillation, Path]] = []
        skipped: list[dict[str, str]] = []
        for distillation, report_path in creative_candidates:
            video_title, _upload_name = creative_names[distillation.video_id]
            if distillation.status != "complete":
                skipped.append(
                    {
                        "video_id": distillation.video_id,
                        "title": video_title,
                        "reason": "最新创作拆解处于降级状态；请先修复模型配置并重新运行深度蒸馏",
                    }
                )
                continue
            creative_documents.append((distillation, report_path))
        creative_video_ids = {item.video_id for item, _path in creative_documents}

        prepared_account_documents: list[tuple[Path, str, bytes]] = []
        with tempfile.TemporaryDirectory(prefix="distiller-weknora-") as temporary:
            vault = Path(temporary)
            export = ObsidianVaultExporter(self.project).export_account(
                account_id=account_id,
                vault_path=str(vault),
                max_video_analyses=max_video_analyses,
                # The Obsidian bundle includes per-video analysis detail and
                # pattern notes; a full account distillation routinely exceeds
                # the 1 MB default, so allow the documented 5 MB ceiling.
                max_export_bytes=5_000_000,
            )
            human_dir = vault / export["account_folder"] / HUMAN_DIR_NAME
            human_paths = sorted(human_dir.glob("*.md"))
            if not human_paths:
                raise DistillerError(
                    ErrorCode.REPORT_GENERATION,
                    "账号知识导出没有生成可同步文档；已保留 WeKnora 中的现有内容。",
                    details={"account_id": account_id},
                )
            for path in human_paths:
                relative_name = (
                    f"{export['account_folder']}/{HUMAN_DIR_NAME}/{path.name}"
                ).replace("\\", "/")
                prepared_account_documents.append(
                    (Path(path.name), relative_name, path.read_bytes())
                )

        existing: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = requests.get(
                    f"{api}/knowledge-bases/{selected_kb_id}/knowledge",
                    headers=headers,
                    params={"page": page, "page_size": 100},
                    timeout=30,
                )
            except requests.RequestException as exc:
                errors.append(f"读取现有知识失败: {exc}")
                break
            if not response.ok:
                errors.append(
                    f"读取现有知识失败: HTTP {response.status_code} {response.text[:200]}"
                )
                break
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                errors.append("读取现有知识失败: WeKnora 返回格式无效")
                break
            existing.extend(item for item in items if isinstance(item, dict))
            total = int(payload.get("total") or len(existing))
            if len(existing) >= total or len(items) < 100:
                break
            page += 1

        owned_existing: list[dict[str, Any]] = []
        for item in existing:
            metadata = item.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            video_id = str(metadata.get("video_id") or "").strip()
            document_type = str(metadata.get("document_type") or "").strip()
            metadata_account_id = str(metadata.get("account_id") or "").strip()
            owned = (
                item.get("channel") == "distiller"
                and metadata.get("source") == "video-account-distiller"
            )
            account_operational = (
                metadata_account_id == account_id
                and not video_id
                and document_type in {"", "account_operational"}
            )
            creative_learning = (
                video_id in creative_video_ids
                and document_type in {"", "creative_learning"}
                and metadata_account_id in {account_id, f"video:{video_id}"}
            )
            if owned and (account_operational or creative_learning):
                owned_existing.append(item)

        if not errors:
            for item in owned_existing:
                knowledge_id = str(item.get("id") or "").strip()
                if not knowledge_id:
                    continue
                try:
                    response = requests.delete(
                        f"{api}/knowledge/{knowledge_id}",
                        headers=headers,
                        timeout=60,
                    )
                    if response.ok:
                        replaced.append(
                            str(item.get("file_name") or item.get("title") or knowledge_id)
                        )
                    else:
                        errors.append(
                            f"删除旧知识 {knowledge_id} 失败: HTTP {response.status_code} "
                            f"{response.text[:200]}"
                        )
                except requests.RequestException as exc:
                    errors.append(f"删除旧知识 {knowledge_id} 失败: {exc}")

        uploaded: list[str] = []
        if not errors:
            for path, relative_name, content in prepared_account_documents:
                _upload_markdown(
                    api,
                    headers,
                    selected_kb_id,
                    path,
                    relative_name,
                    account_id,
                    uploaded,
                    errors,
                    metadata_extra={
                        "document_type": "account_operational",
                        "sync_scope": "account",
                    },
                    content=content,
                )
        if not errors:
            for distillation, report_path in creative_documents:
                video_title, upload_name = creative_names[distillation.video_id]
                relative_name = (
                    f"accounts/{account_id}/videos/{distillation.video_id}/{upload_name}"
                )
                _upload_markdown(
                    api,
                    headers,
                    selected_kb_id,
                    report_path,
                    relative_name,
                    account_id,
                    uploaded,
                    errors,
                    upload_name=upload_name,
                    metadata_extra={
                        "video_id": distillation.video_id,
                        "video_title": video_title or "未命名视频",
                        "distillation_id": distillation.distillation_id,
                        "document_type": "creative_learning",
                        "distillation_mode": "creative_learning",
                        "sync_scope": "account",
                        "status": distillation.status,
                    },
                )

        error_code: str | None = None
        message: str | None = None
        scope_rejected = any(": HTTP 403" in error and '"code":1002' in error for error in errors)
        if scope_rejected:
            error_code = "API_KEY_SCOPE_NOT_ALLOWED"
            message = (
                "WeKnora API Key 无权向此知识库上传文件。请在 WeKnora 的 API Key 设置中，"
                "为目标知识库授予文档上传/编辑权限后重试。"
            )
        elif errors:
            message = "WeKnora 未能完成全部文件上传。"

        return {
            "ok": not errors,
            "kb_id": selected_kb_id,
            "kb_name": kb_name,
            "replaced": replaced,
            "uploaded": uploaded,
            "creative_reports": len(creative_candidates),
            "uploaded_creative_reports": len(creative_documents),
            "degraded_creative_reports": sum(
                item.status == "degraded" for item, _path in creative_candidates
            ),
            "skipped": skipped,
            "errors": errors,
            "error_code": error_code,
            "message": message,
        }

    def _latest_video_distillation(
        self, video_id: str
    ) -> tuple[SingleVideoDistillation, Path] | None:
        selected: tuple[SingleVideoDistillation, Path] | None = None
        for path in sorted(
            (self.project.root / "analyses" / "videos" / video_id).glob("svd_*/distillation.json")
        ):
            try:
                value = SingleVideoDistillation.model_validate(read_json(path))
            except (OSError, ValueError):
                continue
            if value.video_id != video_id:
                continue
            if selected is None or (value.generated_at, value.distillation_id) > (
                selected[0].generated_at,
                selected[0].distillation_id,
            ):
                selected = (value, path)
        return selected

    def sync_video_distillation(
        self,
        *,
        video_id: str,
        base_url: str = DEFAULT_WEKNORA_BASE_URL,
        api_key: str,
        kb_id: str,
    ) -> dict[str, Any]:
        """Upload one video's deep distillation (选材/表现/拍摄/可复制清单) to WeKnora.

        This covers the single-video workflow: deep-distill one interesting video
        (optionally with a cloud deep model) and push the reference card into the
        knowledge base without requiring any account-level artifacts.
        """
        selected_kb_id = kb_id.strip()
        if not selected_kb_id:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora knowledge base ID is required",
            )
        selected = self._latest_video_distillation(video_id)
        if selected is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No single-video deep distillation found: {video_id}",
                details={"next": "run distiller analyze video --deep before WeKnora sync"},
            )
        distillation, distillation_path = selected
        if distillation.status != "complete":
            raise DistillerError(
                ErrorCode.MODEL_UNAVAILABLE,
                "当前单视频创作拆解处于降级状态，不能同步到 WeKnora。"
                "请先修复模型配置并重新运行深度蒸馏，确认产物完整后再同步。",
                details={
                    "video_id": video_id,
                    "distillation_id": distillation.distillation_id,
                    "status": distillation.status,
                    "next": "修复模型连接后重新运行单视频深度蒸馏",
                },
            )
        video_title, upload_name = self._video_document_names(
            distillation.account_id,
            document_label="创作拆解",
            fallback_titles={video_id: _creative_video_title(distillation)},
        )[video_id]
        report_path = distillation_path.parent / "report.md"
        if not report_path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"Single-video deep distillation report is missing: {report_path}",
            )
        knowledge_bases = self.list_knowledge_bases(base_url=base_url, api_key=api_key)
        target = next(
            (item for item in knowledge_bases if item["id"] == selected_kb_id),
            None,
        )
        if target is None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora target knowledge base was not found or is not visible to this API Key",
                details={
                    "kb_id": selected_kb_id,
                    "next": "重新读取该 API Key 可访问的知识库并选择目标库。",
                },
            )
        kb_name = target["name"]
        headers = {"X-API-Key": api_key.strip()}
        api = _api_url(base_url)
        replaced: list[str] = []
        errors: list[str] = []

        existing: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = requests.get(
                    f"{api}/knowledge-bases/{selected_kb_id}/knowledge",
                    headers=headers,
                    params={"page": page, "page_size": 100},
                    timeout=30,
                )
            except requests.RequestException as exc:
                errors.append(f"读取现有知识失败: {exc}")
                break
            if not response.ok:
                errors.append(
                    f"读取现有知识失败: HTTP {response.status_code} {response.text[:200]}"
                )
                break
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                errors.append("读取现有知识失败: WeKnora 返回格式无效")
                break
            existing.extend(item for item in items if isinstance(item, dict))
            total = int(payload.get("total") or len(existing))
            if len(existing) >= total or len(items) < 100:
                break
            page += 1

        owned_existing: list[dict[str, Any]] = []
        for item in existing:
            metadata = item.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            if (
                item.get("channel") == "distiller"
                and metadata.get("source") == "video-account-distiller"
                and metadata.get("video_id") == video_id
                and metadata.get("document_type", "creative_learning") == "creative_learning"
            ):
                owned_existing.append(item)

        if not errors:
            for item in owned_existing:
                knowledge_id = str(item.get("id") or "").strip()
                if not knowledge_id:
                    continue
                try:
                    response = requests.delete(
                        f"{api}/knowledge/{knowledge_id}",
                        headers=headers,
                        timeout=60,
                    )
                    if response.ok:
                        replaced.append(
                            str(item.get("file_name") or item.get("title") or knowledge_id)
                        )
                    else:
                        errors.append(
                            f"删除旧知识 {knowledge_id} 失败: HTTP {response.status_code} "
                            f"{response.text[:200]}"
                        )
                except requests.RequestException as exc:
                    errors.append(f"删除旧知识 {knowledge_id} 失败: {exc}")

        report_text = report_path.read_text(encoding="utf-8")
        document = (
            "---\n"
            f"source: video-account-distiller\n"
            f"video_id: {video_id}\n"
            f"distillation_id: {distillation.distillation_id}\n"
            f"document_type: creative_learning\n"
            f"distillation_mode: creative_learning\n"
            f"status: {distillation.status}\n"
            f"title: {json.dumps(video_title or '未命名视频', ensure_ascii=False)}\n"
            f"type: single-video-distillation\n"
            "---\n\n"
            f"{report_text}"
        )
        relative_name = f"videos/{video_id}/{upload_name}"
        uploaded: list[str] = []
        if not errors:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                encoding="utf-8",
                delete=False,
            ) as handle:
                handle.write(document)
                temp_path = Path(handle.name)
            try:
                _upload_markdown(
                    api,
                    headers,
                    selected_kb_id,
                    temp_path,
                    relative_name,
                    distillation.account_id,
                    uploaded,
                    errors,
                    upload_name=upload_name,
                    metadata_extra={
                        "video_id": video_id,
                        "video_title": video_title or "未命名视频",
                        "distillation_id": distillation.distillation_id,
                        "document_type": "creative_learning",
                        "distillation_mode": "creative_learning",
                        "sync_scope": "video",
                    },
                )
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        error_code: str | None = None
        message: str | None = None
        scope_rejected = any(": HTTP 403" in error and '"code":1002' in error for error in errors)
        if scope_rejected:
            error_code = "API_KEY_SCOPE_NOT_ALLOWED"
            message = (
                "WeKnora API Key 无权向此知识库上传文件。请在 WeKnora 的 API Key 设置中，"
                "为目标知识库授予文档上传/编辑权限后重试。"
            )
        elif errors:
            message = "WeKnora 未能完成单视频蒸馏文档上传。"

        return {
            "ok": not errors,
            "kb_id": selected_kb_id,
            "kb_name": kb_name,
            "video_id": video_id,
            "distillation_id": distillation.distillation_id,
            "status": distillation.status,
            "replaced": replaced,
            "uploaded": uploaded,
            "errors": errors,
            "error_code": error_code,
            "message": message,
        }

    def _latest_video_knowledge(
        self,
        video_id: str,
    ) -> tuple[SingleVideoKnowledgeDistillation, Path] | None:
        selected: tuple[SingleVideoKnowledgeDistillation, Path] | None = None
        root = self.project.root / "analyses" / "videos" / video_id / "knowledge"
        for path in sorted(root.glob("svk_*/knowledge.json")):
            try:
                value = SingleVideoKnowledgeDistillation.model_validate(read_json(path))
            except (OSError, ValueError):
                continue
            if value.video_id != video_id:
                continue
            if selected is None or (value.generated_at, value.knowledge_id) > (
                selected[0].generated_at,
                selected[0].knowledge_id,
            ):
                selected = (value, path)
        return selected

    def sync_video_knowledge(
        self,
        *,
        video_id: str,
        base_url: str = DEFAULT_WEKNORA_BASE_URL,
        api_key: str,
        kb_id: str,
    ) -> dict[str, Any]:
        """Upload one knowledge-mode artifact without replacing creative-learning docs."""
        selected_kb_id = kb_id.strip()
        if not selected_kb_id:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora knowledge base ID is required",
            )
        selected = self._latest_video_knowledge(video_id)
        if selected is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No single-video knowledge extraction found: {video_id}",
                details={"next": "run knowledge-mode single-video distillation first"},
            )
        knowledge, knowledge_path = selected
        if knowledge.status != "complete":
            raise DistillerError(
                ErrorCode.MODEL_UNAVAILABLE,
                "当前单视频知识提炼处于降级状态，不能同步到 WeKnora。"
                "请先修复模型配置并重新运行知识提炼，确认产物完整后再同步。",
                details={
                    "video_id": video_id,
                    "knowledge_id": knowledge.knowledge_id,
                    "status": knowledge.status,
                    "next": "修复模型连接后重新运行单视频知识提炼",
                },
            )
        video_title, upload_name = self._video_document_names(
            knowledge.account_id,
            document_label="知识提炼",
            fallback_titles={video_id: knowledge.knowledge.knowledge_title},
        )[video_id]
        report_path = knowledge_path.parent / "knowledge.md"
        if not report_path.is_file():
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"Single-video knowledge report is missing: {report_path}",
            )
        knowledge_bases = self.list_knowledge_bases(base_url=base_url, api_key=api_key)
        target = next((item for item in knowledge_bases if item["id"] == selected_kb_id), None)
        if target is None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora target knowledge base was not found or is not visible to this API Key",
                details={"kb_id": selected_kb_id},
            )
        headers = {"X-API-Key": api_key.strip()}
        api = _api_url(base_url)
        errors: list[str] = []
        replaced: list[str] = []
        existing: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = requests.get(
                    f"{api}/knowledge-bases/{selected_kb_id}/knowledge",
                    headers=headers,
                    params={"page": page, "page_size": 100},
                    timeout=30,
                )
            except requests.RequestException as exc:
                errors.append(f"读取现有知识失败: {exc}")
                break
            if not response.ok:
                errors.append(
                    f"读取现有知识失败: HTTP {response.status_code} {response.text[:200]}"
                )
                break
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                errors.append("读取现有知识失败: WeKnora 返回格式无效")
                break
            existing.extend(item for item in items if isinstance(item, dict))
            total = int(payload.get("total") or len(existing))
            if len(existing) >= total or len(items) < 100:
                break
            page += 1

        for item in existing:
            metadata = item.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            if not (
                item.get("channel") == "distiller"
                and metadata.get("source") == "video-account-distiller"
                and metadata.get("video_id") == video_id
                and metadata.get("document_type") == "video_knowledge"
            ):
                continue
            knowledge_record_id = str(item.get("id") or "").strip()
            if not knowledge_record_id:
                continue
            try:
                response = requests.delete(
                    f"{api}/knowledge/{knowledge_record_id}",
                    headers=headers,
                    timeout=60,
                )
                if response.ok:
                    replaced.append(
                        str(item.get("file_name") or item.get("title") or knowledge_record_id)
                    )
                else:
                    errors.append(
                        f"删除旧知识 {knowledge_record_id} 失败: HTTP "
                        f"{response.status_code} {response.text[:200]}"
                    )
            except requests.RequestException as exc:
                errors.append(f"删除旧知识 {knowledge_record_id} 失败: {exc}")

        document = (
            "---\n"
            "source: video-account-distiller\n"
            f"video_id: {video_id}\n"
            f"knowledge_id: {knowledge.knowledge_id}\n"
            "document_type: video_knowledge\n"
            "distillation_mode: knowledge\n"
            f"status: {knowledge.status}\n"
            f"title: {json.dumps(video_title or '未命名视频', ensure_ascii=False)}\n"
            "---\n\n"
            f"{report_path.read_text(encoding='utf-8')}"
        )
        relative_name = f"videos/{video_id}/{upload_name}"
        uploaded: list[str] = []
        if not errors:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                encoding="utf-8",
                delete=False,
            ) as handle:
                handle.write(document)
                temp_path = Path(handle.name)
            try:
                _upload_markdown(
                    api,
                    headers,
                    selected_kb_id,
                    temp_path,
                    relative_name,
                    knowledge.account_id,
                    uploaded,
                    errors,
                    upload_name=upload_name,
                    metadata_extra={
                        "video_id": video_id,
                        "video_title": video_title or "未命名视频",
                        "document_type": "video_knowledge",
                        "knowledge_id": knowledge.knowledge_id,
                        "distillation_mode": "knowledge",
                        "sync_scope": "video",
                    },
                )
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        scope_rejected = any(": HTTP 403" in error and '"code":1002' in error for error in errors)
        return {
            "ok": not errors,
            "kb_id": selected_kb_id,
            "kb_name": target["name"],
            "video_id": video_id,
            "knowledge_id": knowledge.knowledge_id,
            "status": knowledge.status,
            "replaced": replaced,
            "uploaded": uploaded,
            "errors": errors,
            "error_code": "API_KEY_SCOPE_NOT_ALLOWED" if scope_rejected else None,
            "message": "WeKnora 未能完成单视频知识文档上传。" if errors else None,
        }

    def sync_account_video_knowledge(
        self,
        *,
        account_id: str,
        base_url: str = DEFAULT_WEKNORA_BASE_URL,
        api_key: str,
        kb_id: str,
    ) -> dict[str, Any]:
        """Upload the latest account batch while preserving one document per video."""

        selected: AccountVideoKnowledgeManifest | None = None
        root = self.project.root / "knowledge" / "accounts" / account_id / "video-knowledge"
        for path in sorted(root.glob("avk_*/manifest.json")):
            try:
                candidate = AccountVideoKnowledgeManifest.model_validate(read_json(path))
            except (OSError, ValueError):
                continue
            if candidate.account_id != account_id:
                continue
            if selected is None or (candidate.generated_at, candidate.manifest_id) > (
                selected.generated_at,
                selected.manifest_id,
            ):
                selected = candidate
        if selected is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No account video-knowledge bundle found: {account_id}",
                details={"next": "run account video knowledge distillation first"},
            )
        if not selected.documents and not selected.skipped:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"Account video-knowledge bundle contains no documents: {account_id}",
                details={"manifest_id": selected.manifest_id},
            )
        skipped: list[dict[str, str]] = [
            {
                "video_id": item.video_id,
                "title": item.title or "未命名视频",
                "reason": "批量知识蒸馏未生成完整文档；请补齐前置分析或修复模型配置后重新运行",
            }
            for item in selected.skipped
        ]
        skipped_video_ids = {item["video_id"] for item in skipped}
        complete_documents = []
        for document in selected.documents:
            if document.status == "complete":
                complete_documents.append(document)
                continue
            if document.video_id not in skipped_video_ids:
                skipped.append(
                    {
                        "video_id": document.video_id,
                        "title": document.title or "未命名视频",
                        "reason": "最新知识提炼处于降级状态；请先修复模型配置并重新运行知识提炼",
                    }
                )
                skipped_video_ids.add(document.video_id)
        missing_documents = [
            document.document_path
            for document in complete_documents
            if not (self.project.root / document.document_path).is_file()
        ]
        if missing_documents:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                "Account video-knowledge bundle is incomplete",
                details={
                    "manifest_id": selected.manifest_id,
                    "missing_documents": missing_documents,
                },
            )

        selected_kb_id = kb_id.strip()
        if not selected_kb_id:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora knowledge base ID is required",
            )
        knowledge_bases = self.list_knowledge_bases(base_url=base_url, api_key=api_key)
        target = next((item for item in knowledge_bases if item["id"] == selected_kb_id), None)
        if target is None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora target knowledge base was not found or is not visible to this API Key",
                details={"kb_id": selected_kb_id},
            )

        if not complete_documents:
            return {
                "ok": True,
                "kb_id": selected_kb_id,
                "kb_name": target["name"],
                "account_id": account_id,
                "manifest_id": selected.manifest_id,
                "document_type": "video_knowledge",
                "uploaded": [],
                "replaced": [],
                "skipped": skipped,
                "errors": [],
                "error_code": None,
                "message": None,
            }

        api = _api_url(base_url)
        headers = {"X-API-Key": api_key.strip()}
        uploaded: list[str] = []
        replaced: list[str] = []
        errors: list[str] = []
        existing: list[dict[str, Any]] = []
        page = 1
        while True:
            try:
                response = requests.get(
                    f"{api}/knowledge-bases/{selected_kb_id}/knowledge",
                    headers=headers,
                    params={"page": page, "page_size": 100},
                    timeout=30,
                )
            except requests.RequestException as exc:
                errors.append(f"读取现有知识失败: {exc}")
                break
            if not response.ok:
                errors.append(
                    f"读取现有知识失败: HTTP {response.status_code} {response.text[:200]}"
                )
                break
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                errors.append("读取现有知识失败: WeKnora 返回格式无效")
                break
            existing.extend(item for item in items if isinstance(item, dict))
            total = int(payload.get("total") or len(existing))
            if len(existing) >= total or len(items) < 100:
                break
            page += 1

        selected_video_ids = {document.video_id for document in complete_documents}
        for item in existing:
            metadata = item.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            owned = (
                item.get("channel") == "distiller"
                and metadata.get("source") == "video-account-distiller"
            )
            metadata_account_id = str(metadata.get("account_id") or "").strip()
            metadata_video_id = str(metadata.get("video_id") or "").strip()
            old_video_knowledge = (
                metadata.get("document_type") == "video_knowledge"
                and metadata_video_id in selected_video_ids
                and metadata_account_id in {account_id, f"video:{metadata_video_id}"}
            )
            if not owned or not old_video_knowledge:
                continue
            knowledge_record_id = str(item.get("id") or "").strip()
            if not knowledge_record_id:
                continue
            try:
                response = requests.delete(
                    f"{api}/knowledge/{knowledge_record_id}",
                    headers=headers,
                    timeout=60,
                )
                if response.ok:
                    replaced.append(
                        str(item.get("file_name") or item.get("title") or knowledge_record_id)
                    )
                else:
                    errors.append(
                        f"删除旧知识 {knowledge_record_id} 失败: HTTP "
                        f"{response.status_code} {response.text[:200]}"
                    )
            except requests.RequestException as exc:
                errors.append(f"删除旧知识 {knowledge_record_id} 失败: {exc}")

        if not errors:
            knowledge_names = self._video_document_names(
                account_id,
                document_label="知识提炼",
                fallback_titles={
                    document.video_id: document.title for document in complete_documents
                },
            )
            for document in complete_documents:
                document_path = self.project.root / document.document_path
                video_title, upload_name = knowledge_names[document.video_id]
                relative_name = f"accounts/{account_id}/videos/{document.video_id}/{upload_name}"
                _upload_markdown(
                    api,
                    headers,
                    selected_kb_id,
                    document_path,
                    relative_name,
                    account_id,
                    uploaded,
                    errors,
                    upload_name=upload_name,
                    metadata_extra={
                        "video_id": document.video_id,
                        "video_title": video_title,
                        "document_type": "video_knowledge",
                        "knowledge_id": document.knowledge_id,
                        "manifest_id": selected.manifest_id,
                        "distillation_mode": "knowledge",
                        "sync_scope": "account",
                    },
                )

        scope_rejected = any(": HTTP 403" in error and '"code":1002' in error for error in errors)
        return {
            "ok": not errors,
            "kb_id": selected_kb_id,
            "kb_name": target["name"],
            "account_id": account_id,
            "manifest_id": selected.manifest_id,
            "document_type": "video_knowledge",
            "uploaded": uploaded,
            "replaced": replaced,
            "skipped": skipped,
            "errors": errors,
            "error_code": "API_KEY_SCOPE_NOT_ALLOWED" if scope_rejected else None,
            "message": "WeKnora 未能完成全部逐视频知识文档上传。" if errors else None,
        }
