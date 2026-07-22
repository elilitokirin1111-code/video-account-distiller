"""Parsers for user-provided SRT, VTT, TXT, and JSON transcripts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, model_validator

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models.core import StrictModel

SUPPORTED_TRANSCRIPT_SUFFIXES = {".srt", ".vtt", ".txt", ".json", ".jsonl"}
TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)


class ParsedTranscriptSegment(StrictModel):
    """Format-neutral subtitle cue before provenance is attached."""

    source_id: str
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str = Field(min_length=1)
    speaker: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_timing(self) -> ParsedTranscriptSegment:
        """Reject reversed known intervals before the import run is created."""

        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        return self


def _timestamp_ms(value: str) -> int:
    normalized = value.replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    whole_seconds, milliseconds = seconds.split(".")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(whole_seconds) * 1_000
        + int(milliseconds)
    )


def _parse_cues(text: str, *, is_vtt: bool) -> list[ParsedTranscriptSegment]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if is_vtt and normalized.startswith("WEBVTT"):
        normalized = normalized.split("\n", 1)[1] if "\n" in normalized else ""
    blocks = re.split(r"\n\s*\n", normalized.strip())
    segments: list[ParsedTranscriptSegment] = []
    for block_index, block in enumerate(blocks, start=1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_index = next(
            (index for index, line in enumerate(lines) if TIMING_RE.search(line)),
            None,
        )
        if timing_index is None:
            continue
        match = TIMING_RE.search(lines[timing_index])
        assert match is not None
        cue_text = " ".join(lines[timing_index + 1 :]).strip()
        if not cue_text:
            continue
        source_id = lines[0] if timing_index == 1 else str(block_index)
        segments.append(
            ParsedTranscriptSegment(
                source_id=source_id,
                start_ms=_timestamp_ms(match.group("start")),
                end_ms=_timestamp_ms(match.group("end")),
                text=re.sub(r"<[^>]+>", "", cue_text).strip(),
            )
        )
    return segments


def _json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    else:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
            values = payload["segments"]
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            values = payload["records"]
        elif isinstance(payload, list):
            values = payload
        else:
            values = [payload]
    if not all(isinstance(item, dict) for item in values):
        raise ValueError("all transcript JSON records must be objects")
    return [dict(item) for item in values]


def _milliseconds(record: dict[str, Any], millisecond_key: str, second_key: str) -> int | None:
    if record.get(millisecond_key) is not None:
        return int(record[millisecond_key])
    if record.get(second_key) is not None:
        return round(float(record[second_key]) * 1_000)
    return None


def _parse_json(path: Path) -> list[ParsedTranscriptSegment]:
    segments: list[ParsedTranscriptSegment] = []
    for index, record in enumerate(_json_records(path), start=1):
        text = str(record.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            ParsedTranscriptSegment(
                source_id=str(record.get("segment_id") or record.get("id") or index),
                start_ms=_milliseconds(record, "start_ms", "start"),
                end_ms=_milliseconds(record, "end_ms", "end"),
                text=text,
                speaker=(str(record["speaker"]).strip() if record.get("speaker") else None),
                confidence=(
                    float(record["confidence"]) if record.get("confidence") is not None else None
                ),
            )
        )
    return segments


def parse_transcript(path: Path) -> list[ParsedTranscriptSegment]:
    """Parse a supported transcript file or raise a stable schema error."""

    path = path.expanduser().resolve()
    if not path.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Transcript file not found: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TRANSCRIPT_SUFFIXES:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Unsupported transcript format: {suffix}",
            details={"supported": sorted(SUPPORTED_TRANSCRIPT_SUFFIXES)},
        )
    try:
        if suffix == ".srt":
            segments = _parse_cues(path.read_text(encoding="utf-8-sig"), is_vtt=False)
        elif suffix == ".vtt":
            segments = _parse_cues(path.read_text(encoding="utf-8-sig"), is_vtt=True)
        elif suffix in {".json", ".jsonl"}:
            segments = _parse_json(path)
        else:
            segments = [
                ParsedTranscriptSegment(source_id=str(index), text=line.strip())
                for index, line in enumerate(
                    path.read_text(encoding="utf-8-sig").splitlines(), start=1
                )
                if line.strip()
            ]
    except (UnicodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Could not parse transcript: {path}",
            details={"reason": str(exc)},
        ) from exc
    if not segments:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Transcript contains no usable segments: {path}",
        )
    return segments
