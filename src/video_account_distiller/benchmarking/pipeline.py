"""Build reusable account profiles from retained metrics, comments, and distillation."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.metrics.calculations import median
from video_account_distiller.models import (
    AccountBenchmarkProfile,
    AccountDistillation,
    AccountRankingEntry,
    Comment,
    CommentAnalysis,
    CommentContentBenchmarkSummary,
    ContentInteractionSummary,
    InteractionBenchmarkSummary,
)
from video_account_distiller.sampling.dataset import AccountDataset, load_account_dataset
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json

BENCHMARK_PROFILE_VERSION = "1.0.0"
RANKING_BASIS = (
    "median_likes_per_video",
    "median_comments_per_video",
    "median_shares_per_video",
    "median_saves_per_video",
    "interactions_per_1000_followers",
)


def _latest_model(
    paths: list[Path],
    model_type: type[AccountDistillation] | type[CommentAnalysis],
) -> AccountDistillation | CommentAnalysis | None:
    candidates: list[AccountDistillation | CommentAnalysis] = []
    for path in paths:
        try:
            candidates.append(model_type.model_validate(read_json(path)))
        except (OSError, ValidationError, ValueError):
            continue
    return (
        max(candidates, key=lambda item: (item.generated_at, item.run_id)) if candidates else None
    )


def _latest_distillation(project: ProjectLayout, account_id: str) -> AccountDistillation:
    value = _latest_model(
        list((project.root / "reports" / "accounts" / account_id).glob("*/distillation.json")),
        AccountDistillation,
    )
    if not isinstance(value, AccountDistillation):
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No account distillation found for benchmark profile: {account_id}",
        )
    return value


def _latest_comment_analysis(
    project: ProjectLayout,
    account_id: str,
) -> CommentAnalysis | None:
    value = _latest_model(
        list((project.root / "analyses" / "comments" / account_id).glob("*/analysis.json")),
        CommentAnalysis,
    )
    return value if isinstance(value, CommentAnalysis) else None


def _metric_values(dataset: AccountDataset) -> tuple[dict[str, list[int]], list[int]]:
    values: dict[str, list[int]] = {
        "likes": [],
        "comments": [],
        "shares": [],
        "saves": [],
    }
    interaction_totals: list[int] = []
    for record in dataset.records:
        metric = record.metric
        if metric is None:
            continue
        observed: list[int] = []
        for name in ("likes", "comments", "shares"):
            value = getattr(metric, name)
            if value is not None:
                values[name].append(value)
                observed.append(value)
        save_candidates = [value for value in (metric.saves, metric.favorites) if value is not None]
        if save_candidates:
            save_value = max(save_candidates)
            values["saves"].append(save_value)
            observed.append(save_value)
        if observed:
            interaction_totals.append(sum(observed))
    return values, interaction_totals


def _interaction_summary(dataset: AccountDataset) -> InteractionBenchmarkSummary:
    values, per_video_interactions = _metric_values(dataset)
    totals = {name: sum(items) for name, items in values.items()}
    medians = {name: median([float(item) for item in items]) for name, items in values.items()}
    total_interactions = sum(totals.values())
    mix = {
        name: (round(value / total_interactions, 6) if total_interactions else None)
        for name, value in totals.items()
    }
    median_interactions = median([float(item) for item in per_video_interactions])
    followers = dataset.account.follower_count_current
    return InteractionBenchmarkSummary(
        metric_video_count=len(per_video_interactions),
        totals=totals,
        medians_per_video=medians,
        interaction_mix=mix,
        median_interactions_per_video=median_interactions,
        interactions_per_1000_followers=(
            round(median_interactions * 1000 / followers, 6)
            if median_interactions is not None and followers
            else None
        ),
        unavailable_fields=[name for name, items in values.items() if not items],
    )


def _content_interaction_summaries(
    dataset: AccountDataset,
    distillation: AccountDistillation,
) -> list[ContentInteractionSummary]:
    records = {record.video.video_id: record for record in dataset.records}
    summaries: list[ContentInteractionSummary] = []
    for cluster in distillation.content_clusters:
        values: dict[str, list[float]] = {
            "likes": [],
            "comments": [],
            "shares": [],
            "saves": [],
            "interactions": [],
        }
        source_video_ids = sorted(video_id for video_id in cluster.video_ids if video_id in records)
        for video_id in source_video_ids:
            metric = records[video_id].metric
            if metric is None:
                continue
            observed: list[float] = []
            for name in ("likes", "comments", "shares"):
                value = getattr(metric, name)
                if value is not None:
                    values[name].append(float(value))
                    observed.append(float(value))
            save_candidates = [
                value for value in (metric.saves, metric.favorites) if value is not None
            ]
            if save_candidates:
                save_value = float(max(save_candidates))
                values["saves"].append(save_value)
                observed.append(save_value)
            if observed:
                values["interactions"].append(sum(observed))
        summaries.append(
            ContentInteractionSummary(
                feature_name=cluster.method,
                feature_value=cluster.feature_value,
                video_count=len(source_video_ids),
                source_video_ids=source_video_ids,
                medians_per_video={name: median(items) for name, items in values.items()},
            )
        )
    return summaries


def _top_text_values(values: list[str], *, limit: int = 10) -> list[str]:
    normalized = [" ".join(item.split())[:160] for item in values if item.strip()]
    counts = Counter(item for item in normalized if item)
    return [
        item
        for item, _count in sorted(
            counts.items(),
            key=lambda pair: (-pair[1], pair[0]),
        )[:limit]
    ]


def _comment_summary(
    analysis: CommentAnalysis | None,
    comment_likes: dict[str, int | None],
) -> CommentContentBenchmarkSummary:
    if analysis is None:
        return CommentContentBenchmarkSummary(
            comment_count=0,
            video_count=0,
            sentiment_counts={},
            intent_counts={},
        )
    sentiment = Counter(str(item.annotation.sentiment) for item in analysis.signals)
    intents = Counter(
        str(intent) for item in analysis.signals for intent in item.annotation.intent_labels
    )
    count = len(analysis.signals)
    purchase_values = [
        item.annotation.purchase_intent
        for item in analysis.signals
        if item.annotation.purchase_intent is not None
    ]
    question_count = sum(
        bool(item.annotation.questions)
        or any(
            str(intent) in {"follow_up", "request_tutorial", "request_link", "question_evidence"}
            for intent in item.annotation.intent_labels
        )
        for item in analysis.signals
    )
    known_like_counts = [
        value
        for item in analysis.signals
        if (value := comment_likes.get(item.comment_id)) is not None
    ]
    return CommentContentBenchmarkSummary(
        comment_count=count,
        video_count=analysis.video_count,
        sentiment_counts=dict(sorted(sentiment.items())),
        intent_counts=dict(sorted(intents.items())),
        comment_like_count_coverage=(round(len(known_like_counts) / count, 6) if count else None),
        comment_like_total=sum(known_like_counts) if known_like_counts else None,
        comment_like_median=median([float(item) for item in known_like_counts]),
        question_rate=round(question_count / count, 6) if count else None,
        pain_point_rate=(
            round(sum(bool(item.annotation.pain_points) for item in analysis.signals) / count, 6)
            if count
            else None
        ),
        objection_rate=(
            round(sum(bool(item.annotation.objections) for item in analysis.signals) / count, 6)
            if count
            else None
        ),
        purchase_intent_mean=(round(fmean(purchase_values), 6) if purchase_values else None),
        spam_rate=(
            round(fmean(item.annotation.spam_probability for item in analysis.signals), 6)
            if count
            else None
        ),
        need_clusters=[
            f"{item.name}:{item.frequency}"
            for item in sorted(
                analysis.need_clusters,
                key=lambda item: (-item.frequency, item.name),
            )[:10]
        ],
        top_questions=_top_text_values(
            [question for item in analysis.signals for question in item.annotation.questions]
        ),
        top_pain_points=_top_text_values(
            [pain_point for item in analysis.signals for pain_point in item.annotation.pain_points]
        ),
        top_objections=_top_text_values(
            [objection for item in analysis.signals for objection in item.annotation.objections]
        ),
        top_content_opportunities=_top_text_values(
            [
                opportunity
                for item in analysis.signals
                for opportunity in item.annotation.content_opportunities
            ]
        ),
    )


class AccountBenchmarkProfileService:
    """Persist one reusable account snapshot for later same-platform comparisons."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def build(self, *, account_id: str, dry_run: bool = False) -> dict[str, Any]:
        dataset = load_account_dataset(self.project, account_id)
        distillation = _latest_distillation(self.project, account_id)
        comment_analysis = _latest_comment_analysis(self.project, account_id)
        video_ids = {record.video.video_id for record in dataset.records}
        comment_likes = {
            comment.comment_id: comment.like_count
            for comment in read_models(
                self.project.normalized_dir / "comments.parquet",
                Comment,
            )
            if comment.video_id in video_ids
        }
        interactions = _interaction_summary(dataset)
        comments = _comment_summary(comment_analysis, comment_likes)
        content_interactions = _content_interaction_summaries(dataset, distillation)
        input_hashes = sorted(
            {
                *dataset.input_hashes,
                sha256_json(distillation.model_dump(mode="json")),
                *(
                    [sha256_json(comment_analysis.model_dump(mode="json"))]
                    if comment_analysis is not None
                    else []
                ),
                *(comment_analysis.input_hashes if comment_analysis is not None else []),
            }
        )
        seed = {
            "version": BENCHMARK_PROFILE_VERSION,
            "account_id": account_id,
            "distillation_id": distillation.distillation_id,
            "input_hashes": input_hashes,
            "interactions": interactions.model_dump(mode="json"),
            "comments": comments.model_dump(mode="json"),
            "content_interactions": [item.model_dump(mode="json") for item in content_interactions],
        }
        profile_id = stable_id("abp_", sha256_json(seed))
        output_dir = (
            self.project.root
            / "analyses"
            / "accounts"
            / account_id
            / "benchmark-profiles"
            / profile_id
        )
        profile_path = output_dir / "profile.json"
        warnings_path = output_dir / "warnings.json"
        outputs = [
            self.project.relative(profile_path),
            self.project.relative(warnings_path),
        ]
        if profile_path.is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "profile": read_json(profile_path),
                "outputs": outputs,
            }
        warnings: list[str] = []
        if interactions.unavailable_fields:
            warnings.append(
                "interaction_fields_unavailable:" + ",".join(interactions.unavailable_fields)
            )
        if interactions.interactions_per_1000_followers is None:
            warnings.append("follower_normalized_interactions_unavailable")
        if comments.comment_count == 0:
            warnings.append("comment_content_analysis_unavailable")
        if all(record.metric is None or record.metric.views is None for record in dataset.records):
            warnings.append("view_metrics_unavailable_not_ranked")
        run_id = stable_id("run_dry_", profile_id)
        manifest = None
        if not dry_run:
            manifest = self.project.begin_run(
                "build account benchmark profile",
                input_hashes=input_hashes,
            )
            run_id = manifest.run_id
        profile = AccountBenchmarkProfile(
            profile_id=profile_id,
            account_id=account_id,
            platform=dataset.account.platform.value,
            generated_at=datetime.now(UTC),
            run_id=run_id,
            source_distillation_id=distillation.distillation_id,
            account_snapshot_at=dataset.account.snapshot_at,
            latest_metric_snapshot_at=max(
                (
                    record.metric.snapshot_at
                    for record in dataset.records
                    if record.metric is not None
                ),
                default=None,
            ),
            follower_count=dataset.account.follower_count_current,
            sampled_video_count=len(dataset.records),
            analyzed_video_count=int(distillation.data_scope.get("analyzed_video_count") or 0),
            analyzed_media_count=int(distillation.data_scope.get("analyzed_media_count") or 0),
            interactions=interactions,
            comment_content=comments,
            content_interactions=content_interactions,
            content_pillars=[
                item.name
                for item in sorted(
                    distillation.content_clusters,
                    key=lambda item: (-item.video_count, item.name),
                )
                if item.name != "unknown"
            ],
            visual_and_audio_identity=distillation.positioning.visual_and_audio_identity,
            input_hashes=input_hashes,
            warnings=warnings,
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "profile": profile.model_dump(mode="json"),
            "outputs": outputs,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(profile_path, profile.model_dump(mode="json"))
        atomic_write_json(warnings_path, warnings)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "videos": profile.sampled_video_count,
                "comments": profile.comment_content.comment_count,
            },
            output_files=outputs,
            warnings=warnings,
        )
        return result


def _profile_indicators(profile: AccountBenchmarkProfile) -> dict[str, float | None]:
    medians = profile.interactions.medians_per_video
    return {
        "median_likes_per_video": medians.get("likes"),
        "median_comments_per_video": medians.get("comments"),
        "median_shares_per_video": medians.get("shares"),
        "median_saves_per_video": medians.get("saves"),
        "interactions_per_1000_followers": (profile.interactions.interactions_per_1000_followers),
    }


def _percentile_score(value: float, population: list[float]) -> float:
    less = sum(item < value for item in population)
    equal = sum(item == value for item in population)
    return round(100 * (less + 0.5 * equal) / len(population), 6)


def rank_account_profiles(
    profiles: list[AccountBenchmarkProfile],
) -> list[AccountRankingEntry]:
    """Rank same-platform accounts on per-post interactions without using views."""

    if not profiles:
        return []
    indicators = {item.account_id: _profile_indicators(item) for item in profiles}
    populations: dict[str, list[float]] = {}
    for name in RANKING_BASIS:
        populations[name] = []
        for values in indicators.values():
            value = values[name]
            if value is not None:
                populations[name].append(float(value))
    provisional: list[tuple[AccountBenchmarkProfile, float, dict[str, float | None], float]] = []
    for profile in profiles:
        raw = indicators[profile.account_id]
        scores = {
            name: (
                _percentile_score(float(value), populations[name])
                if value is not None and populations[name]
                else None
            )
            for name, value in raw.items()
        }
        available = [value for value in scores.values() if value is not None]
        coverage = len(available) / len(RANKING_BASIS)
        composite = round(fmean(available), 6) if available else 0.0
        provisional.append((profile, composite, scores, coverage))
    provisional.sort(key=lambda item: (-item[1], -item[3], item[0].account_id))
    return [
        AccountRankingEntry(
            account_id=profile.account_id,
            rank=index,
            composite_score=composite,
            dimension_scores=scores,
            raw_indicators=indicators[profile.account_id],
            data_coverage=coverage,
            limitations=[
                "views_not_used_platform_visibility_limit",
                "same_platform_public_snapshot_only",
                *(["partial_ranking_dimensions"] if coverage < 1 else []),
            ],
        )
        for index, (profile, composite, scores, coverage) in enumerate(provisional, start=1)
    ]
