from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import Platform, TranscriptSegment
from video_account_distiller.transcripts import parse_transcript


def test_parse_srt_fixture(fixtures_dir: Path) -> None:
    segments = parse_transcript(fixtures_dir / "phase3" / "hotel-video.srt")
    assert len(segments) == 4
    assert segments[0].start_ms == 0
    assert segments[0].end_ms == 4_000
    assert segments[-1].text.startswith("收藏")


def test_parse_vtt_txt_and_json(tmp_path: Path) -> None:
    vtt = tmp_path / "sample.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello <b>hotel</b>\n",
        encoding="utf-8",
    )
    assert parse_transcript(vtt)[0].text == "Hello hotel"

    text = tmp_path / "sample.txt"
    text.write_text("第一行\n\n第二行\n", encoding="utf-8")
    text_segments = parse_transcript(text)
    assert [item.text for item in text_segments] == ["第一行", "第二行"]
    assert text_segments[0].start_ms is None

    json_path = tmp_path / "sample.json"
    json_path.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "id": "a",
                        "start": 1.25,
                        "end": 2.5,
                        "text": "JSON cue",
                        "confidence": 0.91,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    parsed_json = parse_transcript(json_path)[0]
    assert parsed_json.start_ms == 1_250
    assert parsed_json.end_ms == 2_500
    assert parsed_json.confidence == 0.91


def test_transcript_parser_and_model_reject_invalid_input(tmp_path: Path) -> None:
    empty = tmp_path / "empty.srt"
    empty.write_text("not a cue", encoding="utf-8")
    with pytest.raises(DistillerError) as exc_info:
        parse_transcript(empty)
    assert exc_info.value.code == ErrorCode.SCHEMA_INVALID

    reversed_json = tmp_path / "reversed.json"
    reversed_json.write_text(
        json.dumps({"segments": [{"start_ms": 2_000, "end_ms": 1_000, "text": "bad"}]}),
        encoding="utf-8",
    )
    with pytest.raises(DistillerError) as reversed_info:
        parse_transcript(reversed_json)
    assert reversed_info.value.code == ErrorCode.SCHEMA_INVALID

    with pytest.raises(ValidationError):
        TranscriptSegment(
            record_id="ts_bad",
            source_platform=Platform.DOUYIN,
            source_type="transcript_segment",
            source_record_id="1",
            run_id="run_test",
            raw_hash="a" * 64,
            segment_id="ts_bad",
            video_id="vid_test",
            start_ms=2_000,
            end_ms=1_000,
            text="bad timing",
            source="fixture",
        )
