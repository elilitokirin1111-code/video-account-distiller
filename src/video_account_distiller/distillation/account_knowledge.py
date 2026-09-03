"""Account-wide orchestration for one-document-per-video knowledge extraction."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from video_account_distiller.distillation.knowledge import SingleVideoKnowledgeService
from video_account_distiller.distillation.video import _latest_text_analysis
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AccountVideoKnowledgeDocument,
    AccountVideoKnowledgeManifest,
    AccountVideoKnowledgeSkip,
    SingleVideoKnowledgeDistillation,
    Video,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

ACCOUNT_VIDEO_KNOWLEDGE_VERSION = "1.1.0"
MAX_DOCUMENT_STEM_LENGTH = 80
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _title_document_stem(value: str | None, fallback: str) -> str:
    """Create a readable cross-platform filename from the original video title."""

    cleaned = re.sub(r'[\x00-\x1f\\/:*?"<>|]', "", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_视频"
    cleaned = cleaned[:MAX_DOCUMENT_STEM_LENGTH].rstrip(" .")
    return cleaned or fallback


def _unique_document_stem(
    value: str | None,
    fallback: str,
    used: set[str],
) -> str:
    base = _title_document_stem(value, fallback)
    stem = base
    suffix_index = 2
    while stem.casefold() in used:
        suffix = f"（{suffix_index}）"
        stem = f"{base[: MAX_DOCUMENT_STEM_LENGTH - len(suffix)]}{suffix}".rstrip(" .")
        suffix_index += 1
    used.add(stem.casefold())
    return stem


def _document_file_name(document_path: str) -> str:
    return document_path.replace("\\", "/").rsplit("/", 1)[-1]


def _frontmatter(artifact: SingleVideoKnowledgeDistillation, title: str | None) -> str:
    title_value = json.dumps(title or artifact.knowledge.knowledge_title, ensure_ascii=False)
    return (
        "---\n"
        "source: video-account-distiller\n"
        f"account_id: {artifact.account_id}\n"
        f"video_id: {artifact.video_id}\n"
        f"knowledge_id: {artifact.knowledge_id}\n"
        "document_type: video_knowledge\n"
        "distillation_mode: knowledge\n"
        f"status: {artifact.status}\n"
        f"title: {title_value}\n"
        "---\n\n"
    )


def _render_index(manifest: AccountVideoKnowledgeManifest) -> str:
    lines = [
        f"# 账号逐视频知识导入包：{manifest.account_id}",
        "",
        "> documents/ 中每个 Markdown 只对应一条视频，可直接按文件批量导入知识库。",
        "",
        f"- 成功文档：{manifest.completed_count}",
        f"- 降级文档：{manifest.degraded_count}",
        f"- 跳过视频：{manifest.skipped_count}",
        "",
        "## 文档清单",
        "",
        "| video_id | knowledge_id | 状态 | 文档 |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{item.video_id}` | `{item.knowledge_id}` | {item.status} | "
        f"[{item.title or item.video_id}]"
        f"(documents/{quote(_document_file_name(item.document_path))}) |"
        for item in manifest.documents
    )
    if manifest.skipped:
        lines.extend(["", "## 跳过清单", ""])
        lines.extend(
            f"- `{item.video_id}` {item.title or ''}：{item.reason}".rstrip()
            for item in manifest.skipped
        )
    if manifest.warnings:
        lines.extend(["", "## 批次告警", ""])
        lines.extend(f"- {warning}" for warning in manifest.warnings)
    return "\n".join(lines).rstrip() + "\n"


class AccountVideoKnowledgeService:
    """Extract every eligible video's knowledge and assemble an import-ready folder."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def distill(
        self,
        *,
        account_id: str,
        limit: int | None = None,
        video_ids: Sequence[str] | None = None,
        provider: Literal["ollama", "llamacpp", "cloud", "none"] | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_attempts: int | None = None,
        strict_model: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        videos = sorted(
            (
                video
                for video in read_models(self.project.normalized_dir / "videos.parquet", Video)
                if video.account_id == account_id
            ),
            key=lambda item: item.video_id,
        )
        if not videos:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No normalized videos found for account: {account_id}",
            )
        requested_video_ids: list[str] | None = None
        missing_video_ids: list[str] = []
        if video_ids is None:
            selected = videos[:limit] if limit is not None else videos
        else:
            requested_video_ids = list(dict.fromkeys(item for item in video_ids if item))
            if limit is not None:
                requested_video_ids = requested_video_ids[:limit]
            videos_by_id = {video.video_id: video for video in videos}
            selected = [
                videos_by_id[video_id]
                for video_id in requested_video_ids
                if video_id in videos_by_id
            ]
            missing_video_ids = [
                video_id for video_id in requested_video_ids if video_id not in videos_by_id
            ]
        eligible: list[Video] = []
        skipped = [
            AccountVideoKnowledgeSkip(
                video_id=video_id,
                reason="本次媒体增强选择的视频不属于该账号或缺少标准化记录",
            )
            for video_id in missing_video_ids
        ]
        for video in selected:
            if _latest_text_analysis(self.project, video.video_id) is None:
                skipped.append(
                    AccountVideoKnowledgeSkip(
                        video_id=video.video_id,
                        title=video.title,
                        reason="缺少单视频文字盲分析；请先完成字幕转写与视频分析",
                    )
                )
            else:
                eligible.append(video)

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "account_id": account_id,
                "requested_count": (
                    len(requested_video_ids) if requested_video_ids is not None else len(selected)
                ),
                "eligible_count": len(eligible),
                "skipped": [item.model_dump(mode="json") for item in skipped],
                "plan": {
                    "document_shape": "one_markdown_per_video",
                    "provider": provider or "none",
                    "model": model,
                    "external_fact_check": False,
                },
            }

        generated: list[tuple[Video, SingleVideoKnowledgeDistillation, str]] = []
        batch_warnings: list[str] = []
        service = SingleVideoKnowledgeService(self.project)
        for video in eligible:
            try:
                result = service.distill(
                    video_id=video.video_id,
                    deep_provider=provider,
                    deep_model=model,
                    deep_base_url=base_url,
                    deep_api_key=api_key,
                    max_attempts=max_attempts,
                    strict_model=strict_model,
                )
                artifact = SingleVideoKnowledgeDistillation.model_validate(result["knowledge"])
                source_path = next(
                    path for path in result["outputs"] if str(path).endswith("knowledge.md")
                )
                generated.append((video, artifact, str(source_path)))
            except (DistillerError, OSError, ValueError, StopIteration) as exc:
                if strict_model:
                    raise
                skipped.append(
                    AccountVideoKnowledgeSkip(
                        video_id=video.video_id,
                        title=video.title,
                        reason=str(exc),
                    )
                )
                batch_warnings.append(f"video_knowledge_failed:{video.video_id}")

        seed = {
            "account_id": account_id,
            "version": ACCOUNT_VIDEO_KNOWLEDGE_VERSION,
            "video_knowledge_ids": [artifact.knowledge_id for _, artifact, _ in generated],
            "skipped_video_ids": [item.video_id for item in skipped],
        }
        manifest_id = stable_id("avk_", sha256_json(seed))
        output_dir = (
            self.project.root
            / "knowledge"
            / "accounts"
            / account_id
            / "video-knowledge"
            / manifest_id
        )
        manifest_path = output_dir / "manifest.json"
        index_path = output_dir / "README.md"
        document_paths: dict[str, Path] = {}
        used_document_stems: set[str] = set()
        for video, artifact, _ in generated:
            title = video.title or artifact.knowledge.knowledge_title
            stem = _unique_document_stem(title, video.video_id, used_document_stems)
            document_paths[video.video_id] = output_dir / "documents" / f"{stem}.md"
        relative_outputs = [
            self.project.relative(manifest_path),
            self.project.relative(index_path),
            *(self.project.relative(path) for path in document_paths.values()),
        ]
        if manifest_path.is_file():
            cached = AccountVideoKnowledgeManifest.model_validate(read_json(manifest_path))
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "manifest": cached.model_dump(mode="json"),
                "outputs": relative_outputs,
            }

        input_hashes = sorted({video.raw_hash for video in selected})
        run = self.project.begin_run("distill account video knowledge", input_hashes=input_hashes)
        generated_at = datetime.now(UTC)
        documents = [
            AccountVideoKnowledgeDocument(
                video_id=video.video_id,
                title=video.title or artifact.knowledge.knowledge_title,
                knowledge_id=artifact.knowledge_id,
                status=artifact.status,
                source_path=source_path,
                document_path=self.project.relative(document_paths[video.video_id]),
                warnings=artifact.warnings,
            )
            for video, artifact, source_path in generated
        ]
        completed_count = sum(item.status == "complete" for item in documents)
        degraded_count = sum(item.status == "degraded" for item in documents)
        status: Literal["complete", "degraded"] = (
            "complete" if documents and not skipped and degraded_count == 0 else "degraded"
        )
        manifest = AccountVideoKnowledgeManifest(
            manifest_id=manifest_id,
            manifest_version=ACCOUNT_VIDEO_KNOWLEDGE_VERSION,
            account_id=account_id,
            generated_at=generated_at,
            run_id=run.run_id,
            status=status,
            requested_count=(
                len(requested_video_ids) if requested_video_ids is not None else len(selected)
            ),
            eligible_count=len(eligible),
            completed_count=completed_count,
            degraded_count=degraded_count,
            skipped_count=len(skipped),
            documents=documents,
            skipped=skipped,
            warnings=list(dict.fromkeys(batch_warnings)),
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        for video, artifact, source_path in generated:
            source = self.project.root / source_path
            atomic_write_text(
                document_paths[video.video_id],
                _frontmatter(artifact, video.title) + source.read_text(encoding="utf-8"),
            )
        atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
        atomic_write_text(index_path, _render_index(manifest))
        self.project.finish_run(
            run,
            success=True,
            processed_counts={
                "requested_videos": (
                    len(requested_video_ids) if requested_video_ids is not None else len(selected)
                ),
                "knowledge_documents": len(documents),
                "skipped_videos": len(skipped),
            },
            output_files=relative_outputs,
            warnings=manifest.warnings,
        )
        return {
            "ok": True,
            "dry_run": False,
            "already_generated": False,
            "manifest": manifest.model_dump(mode="json"),
            "outputs": relative_outputs,
        }
