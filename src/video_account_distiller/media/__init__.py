"""Local multimodal media analysis."""

from video_account_distiller.media.backend import (
    FFmpegMediaBackend,
    MediaBackend,
    MediaBackendFailure,
    SceneDetectionResult,
)
from video_account_distiller.media.enrichment import (
    ACCOUNT_MEDIA_ADAPTER_VERSION,
    CLAUDE_VIDEO_UPSTREAM_COMMIT,
    AccountMediaEnrichmentService,
    DownloadedMedia,
    HttpMediaDownloader,
    LocalTranscriber,
    MediaDownloader,
    TranscribedMedia,
    WhisperCliTranscriber,
)
from video_account_distiller.media.pipeline import LocalMediaAnalysisService
from video_account_distiller.media.providers import (
    OllamaVisionProvider,
    StructuredVisionFileProvider,
    VisionModelProvider,
    VisionSchemaFailure,
    ollama_model_available,
)

__all__ = [
    "ACCOUNT_MEDIA_ADAPTER_VERSION",
    "CLAUDE_VIDEO_UPSTREAM_COMMIT",
    "AccountMediaEnrichmentService",
    "DownloadedMedia",
    "FFmpegMediaBackend",
    "MediaBackend",
    "MediaBackendFailure",
    "LocalMediaAnalysisService",
    "LocalTranscriber",
    "MediaDownloader",
    "OllamaVisionProvider",
    "SceneDetectionResult",
    "StructuredVisionFileProvider",
    "TranscribedMedia",
    "VisionModelProvider",
    "VisionSchemaFailure",
    "WhisperCliTranscriber",
    "HttpMediaDownloader",
    "ollama_model_available",
]
