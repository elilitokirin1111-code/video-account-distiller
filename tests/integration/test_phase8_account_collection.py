from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from video_account_distiller.collection import AccountCollectionService
from video_account_distiller.models import (
    AccountCollectionBatch,
    AccountCollectionRequest,
    CollectedAccount,
    CollectedComment,
    CollectedMetricSnapshot,
    CollectedVideo,
    CollectionProviderKind,
    ProviderRawPage,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.validation import validate_project


class FixtureAccountProvider:
    def __init__(self) -> None:
        self.calls = 0

    def collect(self, request: AccountCollectionRequest) -> AccountCollectionBatch:
        self.calls += 1
        fetched_at = datetime(2026, 7, 23, 4, 0, tzinfo=UTC)
        platform_account_id = "MS4wLjABAAAAphase8-hotel"
        videos: list[CollectedVideo] = []
        metrics: list[CollectedMetricSnapshot] = []
        comments: list[CollectedComment] = []
        video_count = request.count if request.count is not None else 12
        for index in range(video_count):
            video_id = f"74000000000000000{index:02d}"
            videos.append(
                CollectedVideo(
                    platform_video_id=video_id,
                    account_id=platform_account_id,
                    url=f"https://www.douyin.com/video/{video_id}",
                    title=f"酒店内容样本 {index + 1}",
                    description=f"酒店内容样本 {index + 1} #酒店",
                    published_at=fetched_at - timedelta(days=index + 1),
                    duration_seconds=15.0 + index,
                    content_type="hotel-introduction" if index % 2 == 0 else "service-process",
                    is_ad=False,
                    is_pinned=index == 0,
                    is_deleted=False,
                    is_repost=False,
                    hashtags=["酒店"],
                )
            )
            metrics.append(
                CollectedMetricSnapshot(
                    video_id=video_id,
                    snapshot_at=fetched_at,
                    views=10000 + index * 2300,
                    likes=500 + index * 80,
                    comments=40 + index * 7,
                    shares=20 + index * 5,
                    saves=70 + index * 9,
                    favorites=70 + index * 9,
                    metric_source="fixture:tikhub",
                )
            )
            if index < request.comment_video_limit and request.comments_per_video > 0:
                for comment_index in range(request.comments_per_video):
                    comments.append(
                        CollectedComment(
                            platform_comment_id=(
                                f"75000000000000000{index:02d}{comment_index:02d}"
                            ),
                            video_id=video_id,
                            author_hash=f"{index:064x}",
                            text=(
                                f"住客问题 {index + 1}-{comment_index + 1}："
                                "亲子入住需要提前准备什么？"
                            ),
                            created_at=fetched_at - timedelta(hours=comment_index + 1),
                            like_count=comment_index + 1,
                            is_creator_reply=False,
                            is_pinned=comment_index == 0,
                            language="zh-CN",
                        )
                    )
        return AccountCollectionBatch(
            provider=request.provider,
            profile_url=request.profile_url,
            platform_account_id=platform_account_id,
            fetched_at=fetched_at,
            account=CollectedAccount(
                platform_account_id=platform_account_id,
                handle="phase8_hotel",
                display_name="Phase 8 示例酒店",
                bio="把服务流程讲清楚",
                profile_url=request.profile_url,
                verified=True,
                follower_count_current=24000,
                following_count_current=58,
                total_likes_current=320000,
                video_count_current=86,
                category_raw="酒店官方账号",
                country_or_region="中国",
                language="zh-CN",
                snapshot_at=fetched_at,
            ),
            videos=videos,
            metrics=metrics,
            comments=comments,
            raw_pages=[
                ProviderRawPage(
                    endpoint="/fixture/account",
                    fetched_at=fetched_at,
                    payload={"fixture": True, "videos": video_count},
                )
            ],
        )


def test_account_url_runs_existing_normalized_report_and_distillation_pipeline(
    project: ProjectLayout,
) -> None:
    provider = FixtureAccountProvider()
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAphase8-hotel",
        count=10,
        comments_per_video=2,
        comment_video_limit=2,
    )

    result = AccountCollectionService(project, provider).analyze_url(
        request=request,
        confirm_provider_cost=True,
    )

    account_id = stable_id("acc_", "douyin", "MS4wLjABAAAAphase8-hotel")
    assert provider.calls == 1
    assert result["account"]["account_id"] == account_id
    assert result["collection"]["videos"] == 10
    assert result["collection"]["comments"] == 4
    assert result["collection"]["comment_videos"] == 2
    assert result["normalization"]["counts"]["accounts"] == 1
    assert result["normalization"]["counts"]["videos"] == 10
    assert result["normalization"]["counts"]["metrics"] == 10
    assert result["normalization"]["counts"]["comments"] == 4
    assert result["metrics"]["records"] == 10
    assert result["comment_analysis"]["analysis"]["comment_count"] == 4
    assert result["report"]["report"]["data_scope"]["population_size"] == 10
    assert result["distillation"]["distillation"]["data_scope"]["video_count"] == 10
    raw_artifact = project.root / Path(result["collection"]["raw_artifact"])
    assert raw_artifact.is_file()
    assert (project.normalized_dir / "accounts.parquet").is_file()
    assert (project.normalized_dir / "derived_metrics.parquet").is_file()
    assert (raw_artifact.parent / "comments.json").is_file()
    assert validate_project(project).error_count == 0

    videos_path = raw_artifact.parent / "videos.json"
    tampered = read_json(videos_path)
    tampered[0]["title"] = "tampered"
    atomic_write_json(videos_path, tampered)
    validation = validate_project(project)
    assert validation.error_count == 1
    assert validation.issues[0].entity == "phase8_collection"


def test_account_url_dry_run_never_calls_provider_or_writes(
    project: ProjectLayout,
) -> None:
    provider = FixtureAccountProvider()
    collection_dir = project.root / "raw" / "account-collections"

    result = AccountCollectionService(project, provider).analyze_url(
        request=AccountCollectionRequest(
            profile_url="https://v.douyin.com/fixture/",
            count=41,
        ),
        dry_run=True,
    )

    assert provider.calls == 0
    assert result["provider_calls"]["homepage_post_pages_max"] == 3
    assert not list(collection_dir.rglob("*.json"))


def test_mediacrawler_account_url_runs_full_pipeline_without_cost_confirmation(
    project: ProjectLayout,
) -> None:
    provider = FixtureAccountProvider()
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAphase8-hotel",
        count=10,
        provider=CollectionProviderKind.MEDIACRAWLER,
        comments_per_video=2,
        comment_video_limit=2,
    )

    result = AccountCollectionService(project, provider).analyze_url(request=request)

    assert provider.calls == 1
    assert result["request"]["provider"] == "mediacrawler"
    assert result["collection"]["videos"] == 10
    assert result["collection"]["comments"] == 4
    assert result["normalization"]["counts"]["metrics"] == 10
    assert result["comment_analysis"]["analysis"]["comment_count"] == 4
    assert result["distillation"]["distillation"]["data_scope"]["video_count"] == 10
