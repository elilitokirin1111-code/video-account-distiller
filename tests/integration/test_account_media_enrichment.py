from __future__ import annotations

import json
from array import array
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from video_account_distiller.media import (
    AccountMediaEnrichmentService,
    DownloadedMedia,
    DownloadedMediaCleanupService,
    SceneDetectionResult,
    TranscribedMedia,
)
from video_account_distiller.models import (
    AccountCollectionBatch,
    AccountDistillation,
    AccountMediaEnrichment,
    CollectedAccount,
    CollectedMetricSnapshot,
    CollectedVideo,
    CollectionProviderKind,
    MediaMetadata,
    ProviderRawPage,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.validation import validate_project


class FixtureDownloader:
    def download(
        self,
        candidates: Sequence[str],
        destination: Path,
    ) -> DownloadedMedia:
        assert candidates
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"offline-public-hotel-video")
        return DownloadedMedia(
            path=destination,
            host="v11-weba.douyinvod.com",
            size_bytes=destination.stat().st_size,
        )


class FixtureTranscriber:
    provider_name = "fixture-local-whisper"
    model_name = "fixture-zh"
    available = True

    def transcribe(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
    ) -> TranscribedMedia:
        assert source.is_file()
        atomic_write_json(
            destination,
            {
                "segments": [
                    {
                        "segment_id": "1",
                        "start": 0.0,
                        "end": 4.0,
                        "text": "酒店前台遇到客诉，第一步要先确认客人的真实需求。",
                    },
                    {
                        "segment_id": "2",
                        "start": 4.0,
                        "end": 9.0,
                        "text": "今天分享我们酒店处理投诉的完整服务流程，记得收藏。",
                    },
                ]
            },
        )
        return TranscribedMedia(
            path=destination,
            provider=self.provider_name,
            model=self.model_name,
            language=language,
            segment_count=2,
        )


class UnknownFixtureTranscriber(FixtureTranscriber):
    def transcribe(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
    ) -> TranscribedMedia:
        assert source.is_file()
        atomic_write_json(
            destination,
            {
                "segments": [
                    {
                        "segment_id": "1",
                        "start": 0.0,
                        "end": 4.0,
                        "text": "今天记录一只刚认识的小猫，大家来帮它取个名字。",
                    }
                ]
            },
        )
        return TranscribedMedia(
            path=destination,
            provider=self.provider_name,
            model=self.model_name,
            language=language,
            segment_count=1,
        )


class NoSpeechFixtureTranscriber(FixtureTranscriber):
    def transcribe(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
    ) -> TranscribedMedia:
        assert source.is_file()
        atomic_write_json(
            destination,
            {"segments": [], "warnings": ["no_speech_detected"]},
        )
        return TranscribedMedia(
            path=destination,
            provider=self.provider_name,
            model=self.model_name,
            language=language,
            segment_count=0,
        )


class FixtureMediaBackend:
    available = True
    name = "fixture-ffmpeg"
    version = "1"

    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        return MediaMetadata(
            media_hash=media_hash,
            container="mp4",
            duration_ms=9000,
            width=1080,
            height=1920,
            frame_rate=25,
            video_codec="h264",
            audio_codec="aac",
            audio_channels=1,
            audio_sample_rate=8000,
            file_size_bytes=source.stat().st_size,
            backend=self.name,
            backend_version=self.version,
        )

    def detect_scenes(
        self,
        source: Path,
        *,
        duration_ms: int,
        threshold: float,
        max_shots: int,
    ) -> SceneDetectionResult:
        del source, duration_ms, threshold, max_shots
        return SceneDetectionResult([0, 2000, 5000, 9000], [])

    def extract_frame(
        self,
        source: Path,
        *,
        timestamp_ms: int,
        width: int,
        output: Path,
    ) -> None:
        del source, width
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"jpeg-{timestamp_ms}".encode())

    def decode_audio_pcm(
        self,
        source: Path,
        *,
        sample_rate: int,
        max_seconds: int,
    ) -> bytes:
        del source, sample_rate, max_seconds
        return array("h", [1200] * 72_000).tobytes()


def _write_provider_batch(
    project: ProjectLayout,
    *,
    video_count: int = 1,
    source_shape: Literal["detail", "listing", "missing", "image_post"] = "detail",
) -> Path:
    fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    videos = [
        CollectedVideo(
            platform_video_id=f"p2-{index:02d}",
            account_id="phase2-hotel",
            title=f"客房样本{index:02d}",
            duration_seconds=20,
            language="zh-CN",
        )
        for index in range(1, video_count + 1)
    ]
    metrics = [
        CollectedMetricSnapshot(
            video_id=video.platform_video_id,
            snapshot_at=fetched_at,
            views=1000,
            likes=100,
            comments=10,
            shares=5,
        )
        for video in videos
    ]
    retained_items: list[dict[str, object]] = []
    for video in videos:
        item: dict[str, object] = {"aweme_id": video.platform_video_id}
        if source_shape == "image_post":
            item.update(
                {
                    "aweme_type": 68,
                    "media_type": 42,
                    "images": [{"url_list": ["https://example.invalid/image.jpeg"]}],
                    "video": {
                        "duration": 0,
                        "play_addr": {
                            "url_list": [
                                "https://sf6-cdn-tos.douyinstatic.com/obj/background-audio"
                            ]
                        },
                    },
                }
            )
        elif source_shape != "missing":
            item["video"] = {
                "play_addr_h264": {
                    "url_list": [
                        (
                            "https://v11-weba.douyinvod.com/"
                            f"{video.platform_video_id}.mp4?signed_token=fixture-opaque"
                        )
                    ]
                }
            }
        retained_items.append(item)
    if source_shape == "detail":
        raw_pages = [
            ProviderRawPage(
                endpoint=f"/aweme/v1/web/aweme/detail/?aweme_id={item['aweme_id']}",
                fetched_at=fetched_at,
                payload=item,
            )
            for item in retained_items
        ]
    else:
        raw_pages = [
            ProviderRawPage(
                endpoint="/aweme/v1/web/aweme/post/",
                fetched_at=fetched_at,
                payload={"aweme_list": retained_items},
            )
        ]
    batch = AccountCollectionBatch(
        provider=CollectionProviderKind.MEDIACRAWLER,
        profile_url="https://www.douyin.com/user/phase2-hotel",
        platform_account_id="phase2-hotel",
        fetched_at=fetched_at,
        account=CollectedAccount(
            platform_account_id="phase2-hotel",
            handle="phase2_hotel",
            display_name="Phase 2 酒店样本",
            snapshot_at=fetched_at,
        ),
        videos=videos,
        metrics=metrics,
        raw_pages=raw_pages,
    )
    payload = batch.model_dump(mode="json")
    directory = project.root / "raw" / "account-collections" / "mediacrawler" / sha256_json(payload)
    path = directory / "provider-batch.json"
    atomic_write_json(path, payload)
    atomic_write_json(directory / "accounts.json", [batch.account.model_dump(mode="json")])
    atomic_write_json(
        directory / "videos.json",
        [item.model_dump(mode="json") for item in batch.videos],
    )
    atomic_write_json(
        directory / "metrics.json",
        [item.model_dump(mode="json") for item in batch.metrics],
    )
    return path


def test_account_media_enrichment_completes_traceable_video_to_distillation_chain(
    phase2_project: ProjectLayout,
) -> None:
    batch_path = _write_provider_batch(phase2_project)
    batch_file_hash = sha256_file(batch_path)
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=FixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )

    result = service.enrich(account_id=account_id, limit=1)
    enrichment = AccountMediaEnrichment.model_validate(result["enrichment"])
    item = enrichment.videos[0]
    assert enrichment.distillation_path is not None
    distillation = AccountDistillation.model_validate(
        read_json(phase2_project.root / enrichment.distillation_path)
    )

    assert result["ok"] is True
    assert enrichment.completed_count == 1
    assert enrichment.degraded_count == 0
    assert item.media_analysis_id is not None
    assert item.media_analysis_path is not None
    assert item.transcription.segment_count == 2
    assert item.text_analysis_id is not None
    assert item.text_analysis_status == "degraded"
    assert distillation.data_scope["analyzed_video_count"] == 1
    assert distillation.data_scope["analyzed_media_count"] == 1
    assert distillation.content_clusters[0].name != "unknown"
    assert distillation.positioning.visual_and_audio_identity
    assert "竖屏" in " ".join(distillation.positioning.visual_and_audio_identity)
    # Without a vision provider the craft profile stays empty but structured.
    assert distillation.craft_profile is not None
    assert distillation.craft_profile.analyzed_media_count == 1
    assert distillation.craft_profile.annotated_media_count == 0
    assert any("画面语义标注" in item for item in distillation.craft_profile.unknowns)
    assert any("拍摄手法与表现形式" in item for item in distillation.positioning.unknowns)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "signed_token" not in serialized
    assert "fixture-opaque" not in serialized
    assert sha256_file(batch_path) == batch_file_hash

    repeated = service.enrich(account_id=account_id, limit=1)
    assert repeated["already_generated"] is True
    assert repeated["enrichment"]["enrichment_id"] == enrichment.enrichment_id

    validation = validate_project(phase2_project)
    assert validation.error_count == 0
    assert validation.stats["media_enrichments"] == 1

    analysis_path = item.media_analysis_path
    raw_media_path = (
        phase2_project.root / read_json(phase2_project.root / analysis_path)["raw_media_path"]
    )
    assert raw_media_path.is_file()

    cleanup = DownloadedMediaCleanupService(phase2_project).cleanup_account(
        account_id=account_id,
        media_analysis_paths=[analysis_path],
    )

    assert cleanup["ok"] is True
    assert cleanup["deleted_count"] == 1
    assert cleanup["deleted_bytes"] > 0
    assert not raw_media_path.exists()
    assert (phase2_project.root / item.media_analysis_path).is_file()
    assert validate_project(phase2_project, persist=False).error_count == 0

    reparsed = service.enrich(
        account_id=account_id,
        limit=1,
        selection_mode="selected",
        video_ids=[item.video_id],
        refresh_media=True,
    )
    reparsed_item = AccountMediaEnrichment.model_validate(reparsed["enrichment"]).videos[0]
    assert reparsed_item.media_analysis_path is not None
    restored_analysis = read_json(phase2_project.root / reparsed_item.media_analysis_path)
    restored_raw = phase2_project.root / restored_analysis["raw_media_path"]
    assert restored_raw.is_file()

    cleanup_again = DownloadedMediaCleanupService(phase2_project).cleanup_account(
        account_id=account_id,
        media_analysis_paths=[reparsed_item.media_analysis_path],
        reason="test_post_reparse_cleanup",
    )
    assert cleanup_again["deleted_count"] == 1
    assert not restored_raw.exists()


def test_account_media_enrichment_advances_past_metadata_grounded_fallback_analysis(
    phase2_project: ProjectLayout,
) -> None:
    _write_provider_batch(phase2_project, video_count=2)
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=UnknownFixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )

    first = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1)["enrichment"]
    )
    first_item = first.videos[0]
    assert first_item.text_analysis_path is not None
    first_analysis = read_json(phase2_project.root / first_item.text_analysis_path)
    assert first_analysis["blind_analysis"]["semantics"]["primary_pillar"] == "客房与清洁管理"

    second = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1)["enrichment"]
    )

    assert first_item.platform_video_id == "p2-01"
    assert second.videos[0].platform_video_id == "p2-02"
    assert second.enrichment_id != first.enrichment_id


def test_account_media_enrichment_keeps_strict_workflow_running_for_no_speech(
    phase2_project: ProjectLayout,
) -> None:
    _write_provider_batch(phase2_project)
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=NoSpeechFixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )

    enrichment = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1, strict=True)["enrichment"]
    )
    item = enrichment.videos[0]

    assert enrichment.completed_count == 1
    assert enrichment.failed_count == 0
    assert item.status == "complete"
    assert item.transcription.status == "complete"
    assert item.transcription.segment_count == 0
    assert item.transcription.warnings == ["no_speech_detected"]
    assert "no_speech_detected" in item.warnings
    assert "text_analysis_skipped_no_speech" in item.warnings
    assert item.text_analysis_id is None
    assert enrichment.distillation_path is not None
    assert validate_project(phase2_project, persist=False).error_count == 0


def test_account_media_enrichment_uses_retained_account_listing_video_source(
    phase2_project: ProjectLayout,
) -> None:
    _write_provider_batch(phase2_project, source_shape="listing")
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=FixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )

    enrichment = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1, strict=True)["enrichment"]
    )

    assert enrichment.completed_count == 1
    assert enrichment.failed_count == 0
    assert enrichment.videos[0].media_analysis_id is not None


def test_account_media_enrichment_records_missing_retained_source_without_aborting(
    phase2_project: ProjectLayout,
) -> None:
    _write_provider_batch(phase2_project, source_shape="missing")
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=FixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )

    enrichment = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1, strict=True)["enrichment"]
    )
    item = enrichment.videos[0]

    assert enrichment.completed_count == 0
    assert enrichment.failed_count == 1
    assert item.status == "failed"
    assert "retained_source_unavailable" in item.warnings
    assert enrichment.distillation_path is not None


def test_account_media_enrichment_skips_retained_image_post_audio_without_retry(
    phase2_project: ProjectLayout,
) -> None:
    _write_provider_batch(phase2_project, source_shape="image_post")
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=FixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )

    enrichment = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1, strict=True)["enrichment"]
    )
    item = enrichment.videos[0]

    assert enrichment.completed_count == 0
    assert enrichment.failed_count == 1
    assert item.status == "failed"
    assert "retained_non_video_post" in item.warnings
    assert enrichment.distillation_path is not None
    reparsing = service.reparse_candidates(account_id=account_id)
    assert reparsing["candidates"][0]["retry_recommended"] is False


def test_account_media_reparse_selects_degraded_or_explicit_videos(
    phase2_project: ProjectLayout,
) -> None:
    _write_provider_batch(phase2_project, video_count=2)
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountMediaEnrichmentService(
        phase2_project,
        downloader=FixtureDownloader(),
        transcriber=FixtureTranscriber(),
        media_backend=FixtureMediaBackend(),
    )
    first = AccountMediaEnrichment.model_validate(
        service.enrich(account_id=account_id, limit=1)["enrichment"]
    )
    assert first.videos[0].text_analysis_status == "degraded"

    candidates = service.reparse_candidates(account_id=account_id)
    assert candidates["candidate_count"] == 2
    assert candidates["retry_recommended_count"] == 1
    assert candidates["candidates"][0]["retry_recommended"] is True
    assert candidates["candidates"][1]["status"] == "not_analyzed"

    preview = service.enrich(
        account_id=account_id,
        limit=1,
        selection_mode="selected",
        video_ids=["p2-01"],
        refresh_media=True,
        dry_run=True,
    )
    assert preview["selection_policy"] == "media_reparse_selected"
    assert preview["refresh_media"] is True
    assert preview["selected"][0]["platform_video_id"] == "p2-01"

    reparsed = AccountMediaEnrichment.model_validate(
        service.enrich(
            account_id=account_id,
            limit=1,
            selection_mode="failed_or_degraded",
            refresh_media=True,
        )["enrichment"]
    )
    assert reparsed.selection_policy == "media_reparse_failed_or_degraded"
    assert reparsed.videos[0].platform_video_id == "p2-01"
