from __future__ import annotations

import json
from array import array
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.media import (
    AccountMediaEnrichmentService,
    DownloadedMedia,
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


def _write_provider_batch(project: ProjectLayout) -> Path:
    fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
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
        videos=[
            CollectedVideo(
                platform_video_id="p2-01",
                account_id="phase2-hotel",
                title="客房样本01",
                duration_seconds=20,
                language="zh-CN",
            )
        ],
        metrics=[
            CollectedMetricSnapshot(
                video_id="p2-01",
                snapshot_at=fetched_at,
                views=1000,
                likes=100,
                comments=10,
                shares=5,
            )
        ],
        raw_pages=[
            ProviderRawPage(
                endpoint="/aweme/v1/web/aweme/detail/?aweme_id=p2-01",
                fetched_at=fetched_at,
                payload={
                    "aweme_id": "p2-01",
                    "video": {
                        "play_addr_h264": {
                            "url_list": [
                                (
                                    "https://v11-weba.douyinvod.com/video.mp4"
                                    "?signed_token=fixture-opaque"
                                )
                            ]
                        }
                    },
                },
            )
        ],
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
    assert item.transcription.segment_count == 2
    assert item.text_analysis_id is not None
    assert item.text_analysis_status == "degraded"
    assert distillation.data_scope["analyzed_video_count"] == 1
    assert distillation.data_scope["analyzed_media_count"] == 1
    assert distillation.content_clusters[0].name != "unknown"
    assert distillation.positioning.visual_and_audio_identity
    assert "竖屏" in " ".join(distillation.positioning.visual_and_audio_identity)
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
