"""Strict Phase 6 contracts for local media analysis and timestamped evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from video_account_distiller.models.core import StrictModel, TraceFields
from video_account_distiller.version import MEDIA_SCHEMA_VERSION


class MediaMetadata(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    media_hash: str
    container: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    rotation_degrees: int | None = None
    frame_rate: float | None = Field(default=None, ge=0)
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = Field(default=None, ge=0)
    audio_sample_rate: int | None = Field(default=None, ge=0)
    file_size_bytes: int = Field(ge=0)
    backend: str
    backend_version: str | None = None


class KeyframeEvidence(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    keyframe_id: str
    shot_id: str
    timestamp_ms: int = Field(ge=0)
    path: str
    sha256: str
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)


class ShotSegment(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    shot_id: str
    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    keyframe_ids: list[str] = Field(default_factory=list)
    visual_annotation_id: str | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> ShotSegment:
        if self.end_ms < self.start_ms:
            raise ValueError("shot end_ms must be greater than or equal to start_ms")
        if self.duration_ms != self.end_ms - self.start_ms:
            raise ValueError("shot duration_ms must equal end_ms - start_ms")
        return self


class SilenceInterval(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_interval(self) -> SilenceInterval:
        if self.end_ms < self.start_ms:
            raise ValueError("silence end_ms must be greater than or equal to start_ms")
        return self


class AudioFeatures(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    status: Literal["complete", "degraded", "skipped"]
    has_audio: bool | None = None
    analyzed_duration_ms: int | None = Field(default=None, ge=0)
    sample_rate: int | None = Field(default=None, ge=0)
    rms_dbfs: float | None = None
    peak_dbfs: float | None = None
    dynamic_range_db: float | None = Field(default=None, ge=0)
    loudness_variance: float | None = Field(default=None, ge=0)
    silence_ratio: float | None = Field(default=None, ge=0, le=1)
    activity_ratio: float | None = Field(default=None, ge=0, le=1)
    silence_intervals: list[SilenceInterval] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OcrObservation(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    observation_id: str
    text: str = Field(min_length=1)
    shot_id: str
    keyframe_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: list[float] | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> OcrObservation:
        if self.end_ms < self.start_ms:
            raise ValueError("OCR end_ms must be greater than or equal to start_ms")
        if self.bounding_box is not None and len(self.bounding_box) != 4:
            raise ValueError("OCR bounding_box must contain four coordinates")
        return self


class ShotVisualAnnotation(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    annotation_id: str
    shot_id: str
    summary: str | None = None
    labels: list[str] = Field(default_factory=list)
    dominant_colors: list[str] = Field(default_factory=list)
    composition: list[str] = Field(default_factory=list)
    camera: list[str] = Field(default_factory=list)
    lighting: list[str] = Field(default_factory=list)
    text_overlay_styles: list[str] = Field(default_factory=list)
    motion_graphics: list[str] = Field(default_factory=list)
    branding: list[str] = Field(default_factory=list)
    ocr_observation_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class MediaVisionAnnotation(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    shot_annotations: list[ShotVisualAnnotation] = Field(default_factory=list)
    ocr_observations: list[OcrObservation] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_links(self) -> MediaVisionAnnotation:
        annotation_ids = [item.annotation_id for item in self.shot_annotations]
        observation_ids = [item.observation_id for item in self.ocr_observations]
        if len(annotation_ids) != len(set(annotation_ids)):
            raise ValueError("visual annotation IDs must be unique")
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("OCR observation IDs must be unique")
        observations = {item.observation_id: item for item in self.ocr_observations}
        for annotation in self.shot_annotations:
            for observation_id in annotation.ocr_observation_ids:
                observation = observations.get(observation_id)
                if observation is None or observation.shot_id != annotation.shot_id:
                    raise ValueError("visual annotation references invalid OCR evidence")
        return self


class VisionInputKeyframe(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    keyframe_id: str
    shot_id: str
    timestamp_ms: int = Field(ge=0)
    path: str
    sha256: str


class VisionInputShot(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    shot_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    keyframe_ids: list[str] = Field(default_factory=list)


class MediaVisionBundle(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    video_id: str
    media_hash: str
    shots: list[VisionInputShot]
    keyframes: list[VisionInputKeyframe]


class VisionTaskTrace(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    provider: str
    model: str
    input_hash: str
    attempts: int = Field(ge=0)
    status: Literal["success", "degraded", "skipped"]
    errors: list[str] = Field(default_factory=list)


class MediaEvidenceItem(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    evidence_id: str
    kind: Literal["media", "shot", "keyframe", "audio", "ocr", "visual"]
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    path: str | None = None
    sha256: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class MediaEvidenceIndex(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    analysis_id: str
    video_id: str
    run_id: str
    generated_at: datetime
    media_hash: str
    items: list[MediaEvidenceItem]


class MediaAnalysis(StrictModel):
    schema_version: str = MEDIA_SCHEMA_VERSION
    analysis_id: str
    analysis_version: str
    video_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    status: Literal["complete", "degraded"]
    raw_media_path: str
    metadata: MediaMetadata
    shots: list[ShotSegment]
    keyframes: list[KeyframeEvidence]
    audio: AudioFeatures
    vision: MediaVisionAnnotation | None = None
    vision_trace: VisionTaskTrace
    timeline_path: str
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> MediaAnalysis:
        shot_ids = [item.shot_id for item in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot IDs must be unique")
        ordered = sorted(self.shots, key=lambda item: (item.start_ms, item.index))
        if any(
            left.end_ms > right.start_ms for left, right in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError("shots must not overlap")
        keyframe_ids = {item.keyframe_id for item in self.keyframes}
        if any(set(item.keyframe_ids) - keyframe_ids for item in self.shots):
            raise ValueError("shot references an unknown keyframe")
        if self.vision is not None:
            valid_shots = set(shot_ids)
            valid_keyframes = keyframe_ids
            if any(item.shot_id not in valid_shots for item in self.vision.shot_annotations):
                raise ValueError("visual annotation references an unknown shot")
            if any(
                item.shot_id not in valid_shots or item.keyframe_id not in valid_keyframes
                for item in self.vision.ocr_observations
            ):
                raise ValueError("OCR observation references unknown evidence")
            annotations = {item.annotation_id: item for item in self.vision.shot_annotations}
            for shot in self.shots:
                if shot.visual_annotation_id is None:
                    continue
                annotation = annotations.get(shot.visual_annotation_id)
                if annotation is None or annotation.shot_id != shot.shot_id:
                    raise ValueError("shot references an invalid visual annotation")
        return self


class MediaFeatureRecord(TraceFields):
    schema_version: str = MEDIA_SCHEMA_VERSION
    media_feature_id: str
    analysis_id: str
    video_id: str
    media_hash: str
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    shot_count: int = Field(ge=0)
    keyframe_count: int = Field(ge=0)
    average_shot_duration_ms: float | None = Field(default=None, ge=0)
    silence_ratio: float | None = Field(default=None, ge=0, le=1)
    rms_dbfs: float | None = None
    ocr_observation_count: int = Field(ge=0)
    visual_annotation_count: int = Field(ge=0)
    visual_labels: list[str] = Field(default_factory=list)
    dominant_colors: list[str] = Field(default_factory=list)
    visual_style_tags: list[str] = Field(default_factory=list)
    text_overlay_style_tags: list[str] = Field(default_factory=list)
    motion_graphic_tags: list[str] = Field(default_factory=list)
    branding_tags: list[str] = Field(default_factory=list)
    analysis_status: Literal["complete", "degraded"]
    analysis_path: str
