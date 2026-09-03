"""Local multimodal media analysis."""

from video_account_distiller.media.backend import (
    FFmpegMediaBackend,
    MediaBackend,
    MediaBackendFailure,
    SceneDetectionResult,
)
from video_account_distiller.media.cleanup import DownloadedMediaCleanupService
from video_account_distiller.media.enrichment import (
    ACCOUNT_MEDIA_ADAPTER_VERSION,
    CLAUDE_VIDEO_UPSTREAM_COMMIT,
    AccountMediaEnrichmentService,
    DownloadedMedia,
    FasterWhisperTranscriber,
    HttpMediaDownloader,
    LocalTranscriber,
    MediaDownloader,
    TranscribedMedia,
    WhisperCliTranscriber,
    build_local_transcriber,
)
from video_account_distiller.media.pipeline import LocalMediaAnalysisService
from video_account_distiller.media.providers import (
    CloudVisionProvider,
    DeepSeekVisionProvider,
    LlamaCppVisionProvider,
    OllamaVisionProvider,
    QwenNativeVideoProvider,
    StructuredVisionFileProvider,
    VisionModelProvider,
    VisionProviderUnavailable,
    VisionSchemaFailure,
    llamacpp_model_available,
    ollama_model_available,
)

__all__ = [
    "ACCOUNT_MEDIA_ADAPTER_VERSION",
    "CLAUDE_VIDEO_UPSTREAM_COMMIT",
    "AccountMediaEnrichmentService",
    "CloudVisionProvider",
    "DeepSeekVisionProvider",
    "DownloadedMedia",
    "DownloadedMediaCleanupService",
    "FasterWhisperTranscriber",
    "FFmpegMediaBackend",
    "MediaBackend",
    "MediaBackendFailure",
    "LocalMediaAnalysisService",
    "LocalTranscriber",
    "LlamaCppVisionProvider",
    "MediaDownloader",
    "OllamaVisionProvider",
    "QwenNativeVideoProvider",
    "SceneDetectionResult",
    "StructuredVisionFileProvider",
    "TranscribedMedia",
    "VisionModelProvider",
    "VisionProviderUnavailable",
    "VisionSchemaFailure",
    "WhisperCliTranscriber",
    "build_local_transcriber",
    "HttpMediaDownloader",
    "ollama_model_available",
    "llamacpp_model_available",
]
