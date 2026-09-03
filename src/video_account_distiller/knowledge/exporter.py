"""Deterministic, privacy-aware export of analysis artifacts for knowledge tools."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import (
    AnalysisContextService,
    render_account_learning_report,
)
from video_account_distiller.knowledge.models import (
    KnowledgeDocumentManifest,
    KnowledgeExportIndex,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

EXPORT_SCHEMA_VERSION = "1.1.0"
DEFAULT_MAX_EXPORT_BYTES = 1_000_000
ALLOWED_SOURCE_ROOTS = frozenset({"analyses", "knowledge-base", "reports"})
ACCOUNT_REDACT_FIELDS = ("handle", "display_name", "bio", "profile_url")


def _safe_source_path(value: str) -> str | None:
    normalized = value.replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        return None
    if not path.parts or path.parts[0] not in ALLOWED_SOURCE_ROOTS:
        return None
    return path.as_posix()


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _render_learning_document(
    *,
    payload: dict[str, Any],
    payload_hash: str,
    export_id: str,
    account_id: str,
    evidence_document_name: str,
) -> str:
    project = payload["project"]
    metadata = {
        "type": "distiller_account_learning_report",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "account_id": account_id,
        "project_id": project["project_id"],
        "payload_hash": payload_hash,
        "privacy_classification": "curated_analysis",
        "authoritative_source": "video-account-distiller",
        "contains_raw_comments": False,
        "evidence_document": evidence_document_name,
    }
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    model_artifact = payload.get("artifacts", {}).get("model_synthesis")
    model_payload = model_artifact.get("data") if isinstance(model_artifact, dict) else None
    if isinstance(model_payload, dict):
        try:
            report = render_account_learning_report(model_payload).rstrip()
        except (KeyError, TypeError, ValueError, ValidationError):
            report = ""
    else:
        report = ""
    if not report:
        report = "\n".join(
            [
                "# 账号运营学习报告",
                "",
                "## 一页结论",
                "",
                "当前已完成数据整理，但尚无可用的模型综合结果，不能把统计现象直接当作运营方法。",
                "",
                "## 下一步",
                "",
                "1. 运行账号内容策略综合，让模型从完整证据中提炼可模仿机制。",
                "2. 优先补齐降级或缺失的视频画面语义，再重新综合，避免只按标题和指标猜测。",
                "3. 将新打法先做成单变量实验，通过后再升级为知识库规则。",
                "",
                "## 阅读边界",
                "",
                "- 当前文件没有编造模仿建议；现有数据和统计明细已放入证据附件。",
            ]
        )
    return "\n".join(
        [
            "---",
            frontmatter,
            "---",
            "",
            report,
            "",
            "## 数据支撑",
            "",
            f"- [查看数据与证据附件](./{evidence_document_name})",
            "- 主报告用于人查看和学习；统计明细、结构化知识卡、反证及证据路径保留在附件中。",
            "",
            "## Evidence Backlinks",
            "",
            f"- [Evidence document](./{evidence_document_name})",
            "",
        ]
    )


def _render_evidence_document(
    *,
    payload: dict[str, Any],
    payload_hash: str,
    export_id: str,
    account_id: str,
    source_paths: list[str],
) -> str:
    project = payload["project"]
    metadata = {
        "type": "distiller_account_evidence",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "account_id": account_id,
        "project_id": project["project_id"],
        "payload_hash": payload_hash,
        "privacy_classification": "curated_analysis",
        "authoritative_source": "video-account-distiller",
        "contains_raw_comments": False,
        "sources": source_paths,
    }
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    lines = [
        "---",
        frontmatter,
        "---",
        "",
        f"# 数据与证据附件：{account_id}",
        "",
        ("> 本文件供证据追溯和机器处理；人查看请优先阅读同目录下的账号运营学习报告。"),
        "",
        "## Project",
        "",
        _json_block(project),
        "",
        "## Account Snapshot",
        "",
        _json_block(payload["account"]),
        "",
        "## Data Availability",
        "",
        _json_block(payload["data_availability"]),
        "",
        "## Observed Growth",
        "",
        _json_block(payload["growth"]),
    ]
    artifact_titles = {
        "account_health_report": "Account Health Report",
        "account_distillation": "Account Distillation",
        "comment_analysis": "Aggregated Comment Analysis",
        "benchmark_profile": "Benchmark Profile",
        "media_enrichment": "Media Enrichment",
        "video_analyses": "Bounded Video Analyses",
        "model_synthesis": "Model Synthesis and Structured Knowledge",
    }
    artifacts = payload["artifacts"]
    for key, title in artifact_titles.items():
        value = artifacts.get(key)
        if value in (None, [], {}):
            continue
        lines.extend(["", f"## {title}", "", _json_block(value)])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in payload["limitations"])
    lines.extend(["", "## Downstream Analysis Contract", ""])
    lines.extend(f"- {item}" for item in payload["analysis_contract"])
    lines.extend(["", "## Evidence Backlinks", ""])
    lines.extend(f"- `{item}`" for item in source_paths)
    lines.extend(
        [
            "",
            (
                "Downstream tools and models must cite these backlinks or embedded "
                "evidence identifiers for important claims."
            ),
            "",
        ]
    )
    return "\n".join(lines)


class KnowledgeExportService:
    """Build and persist a bounded account knowledge document."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    @property
    def root(self) -> Path:
        return self.project.root / "knowledge-outbox" / "local"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def _load_index(self) -> KnowledgeExportIndex:
        if not self.manifest_path.is_file():
            return KnowledgeExportIndex()
        try:
            return KnowledgeExportIndex.model_validate(read_json(self.manifest_path))
        except (OSError, ValueError, ValidationError) as exc:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Local knowledge export manifest is invalid",
                details={"path": self.project.relative(self.manifest_path)},
            ) from exc

    def export_account(
        self,
        *,
        account_id: str,
        max_video_analyses: int = 10,
        max_export_bytes: int = DEFAULT_MAX_EXPORT_BYTES,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if max_video_analyses < 1 or max_video_analyses > 1_000:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "max_video_analyses must be between 1 and 1000",
            )
        if max_export_bytes < 10_000 or max_export_bytes > 5_000_000:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "max_export_bytes must be between 10000 and 5000000",
            )

        context = AnalysisContextService(self.project).build(
            account_id=account_id,
            max_video_analyses=max_video_analyses,
            include_model_synthesis=True,
        )
        if context["account"] is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                "Account is not available in normalized data",
                details={"account_id": account_id},
            )

        payload = copy.deepcopy(context)
        payload.pop("generated_at", None)
        redacted_fields: list[str] = []
        config = load_config(self.project.config_path)
        if config.privacy.redact_usernames_in_reports:
            account = payload["account"]
            for field in ACCOUNT_REDACT_FIELDS:
                if account.get(field) is not None:
                    account[field] = None
                    redacted_fields.append(f"account.{field}")

        safe_sources = sorted(
            {
                safe
                for value in payload.get("source_paths", [])
                if isinstance(value, str) and (safe := _safe_source_path(value)) is not None
            }
        )
        payload["source_paths"] = safe_sources
        payload["privacy"] = {
            "contains_raw_comments": False,
            "redacted_fields": redacted_fields,
            "source_allowlist": sorted(ALLOWED_SOURCE_ROOTS),
        }
        payload_hash = sha256_json(payload)
        export_id = stable_id("kexp_", account_id, EXPORT_SCHEMA_VERSION, payload_hash)
        document_key = f"account:{account_id}"
        document_name = f"account-{stable_id('', account_id, length=20)}.md"
        evidence_document_name = document_name.removesuffix(".md") + ".evidence.md"
        document_path = self.root / "accounts" / document_name
        evidence_document_path = self.root / "accounts" / evidence_document_name
        document = _render_learning_document(
            payload=payload,
            payload_hash=payload_hash,
            export_id=export_id,
            account_id=account_id,
            evidence_document_name=evidence_document_name,
        )
        evidence_document = _render_evidence_document(
            payload=payload,
            payload_hash=payload_hash,
            export_id=export_id,
            account_id=account_id,
            source_paths=safe_sources,
        )
        byte_size = len(document.encode("utf-8"))
        evidence_byte_size = len(evidence_document.encode("utf-8"))
        total_byte_size = byte_size + evidence_byte_size
        if total_byte_size > max_export_bytes:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Curated local knowledge export exceeds the configured size limit",
                details={
                    "account_id": account_id,
                    "byte_size": total_byte_size,
                    "learning_report_bytes": byte_size,
                    "evidence_document_bytes": evidence_byte_size,
                    "max_export_bytes": max_export_bytes,
                    "suggestion": "Reduce max_video_analyses or export a narrower account period",
                },
            )

        now = datetime.now(UTC)
        manifest = KnowledgeDocumentManifest(
            schema_version=EXPORT_SCHEMA_VERSION,
            export_id=export_id,
            document_key=document_key,
            account_id=account_id,
            payload_hash=payload_hash,
            document_path=self.project.relative(document_path),
            evidence_document_path=self.project.relative(evidence_document_path),
            source_paths=safe_sources,
            redacted_fields=redacted_fields,
            byte_size=byte_size,
            evidence_byte_size=evidence_byte_size,
            generated_at=now,
        )
        index = self._load_index()
        previous = index.documents.get(document_key)
        already_exported = (
            previous is not None
            and previous.payload_hash == payload_hash
            and document_path.is_file()
            and document_path.read_text(encoding="utf-8") == document
            and evidence_document_path.is_file()
            and evidence_document_path.read_text(encoding="utf-8") == evidence_document
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_exported": already_exported,
            "manifest": manifest.model_dump(mode="json"),
            "document_path": self.project.relative(document_path),
            "evidence_document_path": self.project.relative(evidence_document_path),
            "manifest_path": self.project.relative(self.manifest_path),
        }
        if dry_run or already_exported:
            return result

        atomic_write_text(document_path, document)
        atomic_write_text(evidence_document_path, evidence_document)
        index.documents[document_key] = manifest
        atomic_write_json(self.manifest_path, index.model_dump(mode="json"))
        return result
