"""Loss-aware cleanup for transcript text passed to language models."""

from __future__ import annotations

import re

_UNREADABLE_RUN = re.compile(r"\ufffd+")
UNREADABLE_TRANSCRIPT_MARKER = "（此处转写无法辨认）"


def has_unreadable_transcript_text(value: str) -> bool:
    """Return whether decoding replacement characters remain in an ASR segment."""

    return "\ufffd" in value


def clean_transcript_text(value: str) -> str:
    """Replace undecodable runs with an explicit uncertainty marker.

    The normalized evidence remains untouched. Only model-facing text is changed,
    so an undecodable byte cannot silently become a claimed word or knowledge fact.
    """

    return _UNREADABLE_RUN.sub(UNREADABLE_TRANSCRIPT_MARKER, value)


__all__ = [
    "UNREADABLE_TRANSCRIPT_MARKER",
    "clean_transcript_text",
    "has_unreadable_transcript_text",
]
