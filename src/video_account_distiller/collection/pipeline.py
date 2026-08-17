"""One-command account collection, normalization, reporting, and distillation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from video_account_distiller.collection.drift import TikHubDriftDetector
from video_account_distiller.collection.planning import (
    CollectionProfile,
    build_collection_plan,
    collection_coverage,
    enforce_collection_budget,
)
from video_account_distiller.collection.providers import AccountCollectionProvider
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features import TextModelProvider
from video_account_distiller.ingestion import ImportService
from video_account_distiller.ingestion.importer import EntityName
from video_account_distiller.metrics import MetricsService
from video_account_distiller.models import (
    AccountCollectionRequest,
    CollectionProviderKind,
    ImportReceipt,
    Platform,
)
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.quality import QualityReport
from video_account_distiller.reports import ReportService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json


def _write_immutable_json(path: Path, payload: object) -> None:
    if path.is_file():
        if sha256_json(read_json(path)) != sha256_json(payload):
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                f"Immutable account collection artifact changed: {path}",
            )
        return
    atomic_write_json(path, payload)


def _quality_payload(
    receipt: ImportReceipt | None,
    report: QualityReport,
    already_imported: bool,
) -> dict[str, Any]:
    receipt_payload = receipt.model_dump(mode="json") if receipt is not None else None
    return {
        "already_imported": already_imported,
        "receipt": receipt_payload,
        "quality": report.as_dict(),
    }


class AccountCollectionService:
    """Orchestrate an authorized provider through the existing offline kernel."""

    def __init__(
        self,
        project: ProjectLayout,
        provider: AccountCollectionProvider,
    ) -> None:
        self.project = project
        self.provider = provider

    def analyze_url(
        self,
        *,
        request: AccountCollectionRequest,
        confirm_provider_cost: bool = False,
        dry_run: bool = False,
        collection_profile: CollectionProfile = CollectionProfile.STANDARD,
        max_provider_calls: int | None = None,
        text_provider: TextModelProvider | None = None,
    ) -> dict[str, Any]:
        """Collect one homepage and create account-health and distillation artifacts."""

        plan = build_collection_plan(
            request,
            profile=collection_profile,
            max_provider_calls=max_provider_calls,
        )
        if dry_run:
            return {"ok": True, "dry_run": True, **plan}
        enforce_collection_budget(plan)
        if request.provider == CollectionProviderKind.TIKHUB and not confirm_provider_cost:
            raise DistillerError(
                ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED,
                "Paid provider calls require explicit cost confirmation",
                details={"next": "pass --confirm-provider-cost after reviewing --dry-run"},
            )
        batch = self.provider.collect(request)
        if batch.provider != request.provider or batch.profile_url != request.profile_url:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Provider batch does not match the requested account collection scope",
            )
        if not batch.videos:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Provider returned no usable public videos for this account",
            )
        drift_report = (
            TikHubDriftDetector().evaluate(batch.raw_pages)
            if batch.provider == CollectionProviderKind.TIKHUB
            else None
        )
        collection_warnings = list(batch.warnings)
        if drift_report is not None and drift_report.status == "fail":
            collection_warnings.append("tikhub_response_contract_drift")
        elif drift_report is not None and drift_report.status == "warn":
            collection_warnings.append("tikhub_response_contract_warning")
        batch_payload = batch.model_dump(mode="json")
        fingerprint = sha256_json(batch_payload)
        batch_dir = (
            self.project.root / "raw" / "account-collections" / batch.provider.value / fingerprint
        )
        raw_path = batch_dir / "provider-batch.json"
        account_path = batch_dir / "accounts.json"
        videos_path = batch_dir / "videos.json"
        metrics_path = batch_dir / "metrics.json"
        comments_path = batch_dir / "comments.json"
        drift_path = batch_dir / "drift-report.json"
        account_rows = [batch.account.model_dump(mode="json")]
        video_rows = [item.model_dump(mode="json") for item in batch.videos]
        metric_rows = [item.model_dump(mode="json") for item in batch.metrics]
        comment_rows = [item.model_dump(mode="json") for item in batch.comments]
        _write_immutable_json(raw_path, batch_payload)
        _write_immutable_json(account_path, account_rows)
        _write_immutable_json(videos_path, video_rows)
        _write_immutable_json(metrics_path, metric_rows)
        if comment_rows:
            _write_immutable_json(comments_path, comment_rows)
        if drift_report is not None:
            _write_immutable_json(drift_path, drift_report.model_dump(mode="json"))

        importer = ImportService(self.project)
        imports: dict[str, Any] = {}
        sources: list[tuple[EntityName, Path]] = [
            ("accounts", account_path),
            ("videos", videos_path),
            ("metrics", metrics_path),
        ]
        if comment_rows:
            sources.append(("comments", comments_path))
        for entity, source in sources:
            receipt, quality, already_imported = importer.import_file(
                entity=entity,
                source=source,
                platform=Platform.DOUYIN,
            )
            imports[entity] = _quality_payload(receipt, quality, already_imported)
            if quality.error_count:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    f"Collected {entity} failed strict import validation",
                    details={
                        "errors": quality.error_count,
                        "quality": quality.as_dict(),
                    },
                )

        account_id = stable_id("acc_", Platform.DOUYIN.value, batch.platform_account_id)
        normalization = NormalizationService(self.project).normalize()
        metrics = MetricsService(self.project).calculate(account_id=account_id)
        report = ReportService(self.project).generate_account_health(account_id=account_id)
        comment_analysis = (
            CommentAnalysisService(self.project).analyze(
                account_id=account_id,
                provider=text_provider,
            )
            if batch.comments
            else None
        )
        distillation = AccountDistillationService(self.project).distill(account_id=account_id)
        return {
            "ok": True,
            "dry_run": False,
            "collection_profile": collection_profile.value,
            "request": request.model_dump(mode="json"),
            "account": {
                "account_id": account_id,
                "platform_account_id": batch.platform_account_id,
                "display_name": batch.account.display_name,
                "handle": batch.account.handle,
                "profile_url": batch.profile_url,
                "bio": batch.account.bio,
                "verified": batch.account.verified,
                "follower_count_current": batch.account.follower_count_current,
                "following_count_current": batch.account.following_count_current,
                "total_likes_current": batch.account.total_likes_current,
                "video_count_current": batch.account.video_count_current,
                "snapshot_at": batch.account.snapshot_at.isoformat(),
            },
            "collection": {
                "fingerprint": fingerprint,
                "fetched_at": batch.fetched_at.isoformat(),
                "videos": len(batch.videos),
                "metrics": len(batch.metrics),
                "comments": len(batch.comments),
                "comment_videos": len({item.video_id for item in batch.comments}),
                "raw_artifact": self.project.relative(raw_path),
                "drift_artifact": (
                    self.project.relative(drift_path) if drift_report is not None else None
                ),
                "drift": (
                    drift_report.model_dump(mode="json") if drift_report is not None else None
                ),
                "warnings": collection_warnings,
            },
            "coverage": collection_coverage(
                request,
                batch,
                profile=collection_profile,
            ),
            "imports": imports,
            "normalization": normalization,
            "metrics": metrics,
            "report": report,
            "comment_analysis": comment_analysis,
            "distillation": distillation,
        }
