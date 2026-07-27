"""Assemble a privacy-aware, model-ready account analysis context."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from video_account_distiller.growth import AccountGrowthService
from video_account_distiller.models import Account, Comment, MetricSnapshot, Video
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import read_json

PRIVATE_METRIC_FIELDS = (
    "impressions",
    "follows_gained",
    "profile_visits",
    "avg_watch_time_seconds",
    "completion_rate",
    "three_second_view_rate",
    "five_second_view_rate",
    "clicks",
    "leads",
    "orders",
    "revenue",
    "promotion_spend",
)


def _latest_artifact(
    project: ProjectLayout,
    pattern: str,
) -> tuple[dict[str, Any] | None, str | None]:
    candidates: list[tuple[str, str, dict[str, Any], Path]] = []
    for path in project.root.glob(pattern):
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        candidates.append(
            (
                str(payload.get("generated_at") or ""),
                str(path),
                payload,
                path,
            )
        )
    if not candidates:
        return None, None
    _, _, payload, path = max(candidates, key=lambda item: (item[0], item[1]))
    return payload, project.relative(path)


def _latest_video_analyses(
    project: ProjectLayout,
    *,
    account_id: str,
    max_items: int,
) -> list[dict[str, Any]]:
    selected: dict[str, tuple[str, str, dict[str, Any], Path]] = {}
    for path in project.root.glob("analyses/videos/*/*/analysis.json"):
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or payload.get("account_id") != account_id:
            continue
        video_id = str(payload.get("video_id") or "")
        if not video_id:
            continue
        candidate = (
            str(payload.get("generated_at") or ""),
            str(path),
            payload,
            path,
        )
        current = selected.get(video_id)
        if current is None or candidate[:2] > current[:2]:
            selected[video_id] = candidate
    ordered = sorted(selected.values(), key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {"path": project.relative(path), "data": payload}
        for _, _, payload, path in ordered[:max_items]
    ]


def _comment_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Exclude per-comment text while retaining aggregate needs and caveats."""
    keys = (
        "analysis_id",
        "account_id",
        "generated_at",
        "status",
        "comment_count",
        "video_count",
        "need_clusters",
        "warnings",
    )
    return {key: payload.get(key) for key in keys}


def _media_summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "enrichment_id",
        "account_id",
        "generated_at",
        "source_provider",
        "selection_policy",
        "requested_limit",
        "selected_count",
        "completed_count",
        "degraded_count",
        "failed_count",
        "videos",
        "distillation_id",
        "warnings",
    )
    return {key: payload.get(key) for key in keys}


class AnalysisContextService:
    """Provide one bounded endpoint/CLI payload suitable for GPT analysis."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def build(self, *, account_id: str, max_video_analyses: int = 10) -> dict[str, Any]:
        accounts = [
            item
            for item in read_models(self.project.normalized_dir / "accounts.parquet", Account)
            if item.account_id == account_id
        ]
        account = max(accounts, key=lambda item: item.snapshot_at) if accounts else None
        videos = [
            item
            for item in read_models(self.project.normalized_dir / "videos.parquet", Video)
            if item.account_id == account_id
        ]
        video_ids = {item.video_id for item in videos}
        metrics = [
            item
            for item in read_models(
                self.project.normalized_dir / "metric_snapshots.parquet",
                MetricSnapshot,
            )
            if item.video_id in video_ids
        ]
        comments = [
            item
            for item in read_models(self.project.normalized_dir / "comments.parquet", Comment)
            if item.video_id in video_ids
        ]
        private_metric_availability = {
            field: any(getattr(item, field) is not None for item in metrics)
            for field in PRIVATE_METRIC_FIELDS
        }

        report, report_path = _latest_artifact(
            self.project,
            f"reports/accounts/{account_id}/*/report.json",
        )
        distillation, distillation_path = _latest_artifact(
            self.project,
            f"reports/accounts/{account_id}/*/distillation.json",
        )
        comment_analysis, comment_path = _latest_artifact(
            self.project,
            f"analyses/comments/{account_id}/*/analysis.json",
        )
        benchmark_profile, benchmark_path = _latest_artifact(
            self.project,
            f"analyses/accounts/{account_id}/benchmark-profiles/*/profile.json",
        )
        media_enrichment, media_path = _latest_artifact(
            self.project,
            f"analyses/accounts/{account_id}/media-enrichments/*/enrichment.json",
        )
        video_analyses = _latest_video_analyses(
            self.project,
            account_id=account_id,
            max_items=min(max(max_video_analyses, 1), 50),
        )
        growth = AccountGrowthService(self.project).summarize(account_id=account_id)

        limitations: list[str] = []
        if account is None:
            limitations.append("account_record_unavailable")
        if not comments:
            limitations.append("public_comments_unavailable")
        if comment_analysis is None:
            limitations.append("comment_semantic_analysis_unavailable")
        if not video_analyses:
            limitations.append("video_content_analysis_unavailable")
        if media_enrichment is None:
            limitations.append("local_audio_visual_media_enrichment_unavailable")
        if growth["status"] != "ready":
            limitations.append("account_growth_requires_multiple_time_separated_snapshots")
        missing_private = [
            field for field, available in private_metric_availability.items() if not available
        ]
        if missing_private:
            limitations.append("owned_private_metrics_unavailable:" + ",".join(missing_private))
        limitations.extend(
            [
                "fan_demographics_are_not_part_of_the_current_normalized_schema",
                "public_comment_samples_do_not_represent_all_viewers_or_all_comments",
                "missing_values_are_unknown_and_must_not_be_treated_as_zero",
            ]
        )

        state = self.project.load_state()
        sources = [
            path
            for path in (
                report_path,
                distillation_path,
                comment_path,
                benchmark_path,
                media_path,
                *(item["path"] for item in video_analyses),
            )
            if path is not None
        ]
        return {
            "ok": True,
            "context_version": "1.0.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "purpose": "bounded evidence context for downstream GPT-compatible analysis",
            "project": {
                "project_id": state.project_id,
                "project_name": state.project_name,
            },
            "account": account.model_dump(mode="json") if account is not None else None,
            "data_availability": {
                "account_videos": len(videos),
                "metric_snapshots": len(metrics),
                "public_comments": len(comments),
                "analyzed_videos_in_context": len(video_analyses),
                "private_metric_fields": private_metric_availability,
            },
            "growth": growth,
            "artifacts": {
                "account_health_report": (
                    None if report is None else {"path": report_path, "data": report}
                ),
                "account_distillation": (
                    None
                    if distillation is None
                    else {"path": distillation_path, "data": distillation}
                ),
                "comment_analysis": (
                    None
                    if comment_analysis is None
                    else {"path": comment_path, "data": _comment_summary(comment_analysis)}
                ),
                "benchmark_profile": (
                    None
                    if benchmark_profile is None
                    else {"path": benchmark_path, "data": benchmark_profile}
                ),
                "media_enrichment": (
                    None
                    if media_enrichment is None
                    else {"path": media_path, "data": _media_summary(media_enrichment)}
                ),
                "video_analyses": video_analyses,
            },
            "source_paths": sources,
            "limitations": limitations,
            "analysis_contract": [
                (
                    "Separate observed facts, statistical associations, hypotheses, "
                    "and recommendations."
                ),
                "Cite source_paths or artifact evidence identifiers for important claims.",
                "Do not infer missing metrics, fan demographics, or private creator data.",
                "State sample boundaries before interpreting comments or content patterns.",
                "Prefer testable next actions over causal claims.",
            ],
        }
