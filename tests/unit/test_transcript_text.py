from __future__ import annotations

from video_account_distiller.utils.transcript_text import (
    UNREADABLE_TRANSCRIPT_MARKER,
    clean_transcript_text,
    has_unreadable_transcript_text,
)


def test_clean_transcript_text_marks_undecodable_runs_without_guessing() -> None:
    source = "财神节\ufffd\ufffd招财"

    cleaned = clean_transcript_text(source)

    assert cleaned == f"财神节{UNREADABLE_TRANSCRIPT_MARKER}招财"
    assert "\ufffd" not in cleaned
    assert has_unreadable_transcript_text(source) is True
    assert has_unreadable_transcript_text(cleaned) is False
