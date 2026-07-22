from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_account_distiller.comments.pipeline import redact_comment_text
from video_account_distiller.models import CommentSignalAnnotation


def test_comment_redaction_removes_direct_identifiers() -> None:
    text, count = redact_comment_text(
        "电话13812345678，邮箱 guest@example.com，找 @hotel_manager，https://example.com"
    )
    assert count == 4
    assert "13812345678" not in text
    assert "guest@example.com" not in text
    assert "hotel_manager" not in text
    assert "example.com" not in text
    assert text.count("REDACTED") == 4


def test_comment_annotation_requires_at_least_one_intent() -> None:
    with pytest.raises(ValidationError):
        CommentSignalAnnotation.model_validate(
            {
                "sentiment": "neutral",
                "intent_labels": [],
                "spam_probability": 0.0,
                "confidence": 0.5,
            }
        )
