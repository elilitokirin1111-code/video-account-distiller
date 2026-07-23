"""One-command account collection, normalization, reporting, and distillation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from video_account_distiller.collection.providers import AccountCollectionProvider
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.errors import DistillerError, ErrorCode
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
    ) -> dict[str, Any]:
        """Collect one homepage and create account-health and distillation artifacts."""

        if dry_run:
            page_size = 18 if request.provider == CollectionProviderKind.MEDIACRAWLER else 20
            collection_count = (
                min(max(request.count * 3, request.count), 100)
                if (
                    request.provider == CollectionProviderKind.MEDIACRAWLER
                    and request.sort.value == "popular"
                )
                else request.count
            )
            page_count = (collection_count + page_size - 1) // page_size
            comment_calls = (
                min(request.count, request.comment_video_limit)
                if request.comments_per_video > 0
                else 0
            )
            detail_calls = (
                collection_count if request.provider == CollectionProviderKind.MEDIACRAWLER else 0
            )
            would_write = [
                "raw/account-collections/",
                "staging/accounts/",
                "staging/videos/",
                "staging/metrics/",
                "normalized/*.parquet",
                "reports/accounts/",
            ]
            if comment_calls:
                would_write.extend(
                    [
                        "staging/comments/",
                        "analyses/comments/",
                    ]
                )
            return {
                "ok": True,
                "dry_run": True,
                "request": request.model_dump(mode="json"),
                "provider_calls": {
                    "resolve_profile_url": 1,
                    "account_profile": 1,
                    "homepage_post_pages_max": page_count,
                    "video_detail_calls_max": detail_calls,
                    "comment_video_pages_max": comment_calls,
                    "total_max": page_count + detail_calls + comment_calls + 2,
                },
                "billing": {
                    "chargeable_calls_max": (
                        0
                        if request.provider == CollectionProviderKind.MEDIACRAWLER
                        else page_count + comment_calls + 2
                    ),
                    "unit_price": (
                        "none; local non-commercial research runtime"
                        if request.provider == CollectionProviderKind.MEDIACRAWLER
                        else "check the provider marketplace for each endpoint"
                    ),
                    "currency": (
                        None
                        if request.provider == CollectionProviderKind.MEDIACRAWLER
                        else "provider_account_currency"
                    ),
                },
                "runtime": (
                    {
                        "browser": "visible Chrome with a dedicated persistent profile",
                        "login": "manual when required",
                        "first_run": "uv prepares the pinned MediaCrawler environment",
                    }
                    if request.provider == CollectionProviderKind.MEDIACRAWLER
                    else None
                ),
                "would_write": would_write,
            }
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
            CommentAnalysisService(self.project).analyze(account_id=account_id)
            if batch.comments
            else None
        )
        distillation = AccountDistillationService(self.project).distill(account_id=account_id)
        return {
            "ok": True,
            "dry_run": False,
            "request": request.model_dump(mode="json"),
            "account": {
                "account_id": account_id,
                "platform_account_id": batch.platform_account_id,
                "display_name": batch.account.display_name,
                "handle": batch.account.handle,
                "profile_url": batch.profile_url,
            },
            "collection": {
                "fingerprint": fingerprint,
                "fetched_at": batch.fetched_at.isoformat(),
                "videos": len(batch.videos),
                "metrics": len(batch.metrics),
                "comments": len(batch.comments),
                "comment_videos": len({item.video_id for item in batch.comments}),
                "raw_artifact": self.project.relative(raw_path),
                "warnings": batch.warnings,
            },
            "imports": imports,
            "normalization": normalization,
            "metrics": metrics,
            "report": report,
            "comment_analysis": comment_analysis,
            "distillation": distillation,
        }
