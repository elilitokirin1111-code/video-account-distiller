"""Local multimodal media analysis."""

from video_account_distiller.media.backend import (
    FFmpegMediaBackend,
    MediaBackend,
    MediaBackendFailure,
    SceneDetectionResult,
)
from video_account_distiller.media.pipeline import LocalMediaAnalysisService
from video_account_distiller.media.providers import (
    StructuredVisionFileProvider,
    VisionModelProvider,
    VisionSchemaFailure,
)

__all__ = [
    "FFmpegMediaBackend",
    "MediaBackend",
    "MediaBackendFailure",
    "LocalMediaAnalysisService",
    "SceneDetectionResult",
    "StructuredVisionFileProvider",
    "VisionModelProvider",
    "VisionSchemaFailure",
]
