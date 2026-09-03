from __future__ import annotations

from video_account_distiller.distillation.account_knowledge import (
    MAX_DOCUMENT_STEM_LENGTH,
    _title_document_stem,
    _unique_document_stem,
)


def test_title_document_stem_keeps_readable_title_and_removes_unsafe_characters() -> None:
    stem = _title_document_stem('家装/投放：怎么选？* "完整指南"', "vid_fallback")

    assert stem == "家装投放：怎么选？ 完整指南"
    assert "/" not in stem
    assert "*" not in stem
    assert '"' not in stem


def test_title_document_stem_handles_duplicates_reserved_names_and_length() -> None:
    used: set[str] = set()

    first = _unique_document_stem("同名视频", "vid_1", used)
    second = _unique_document_stem("同名视频", "vid_2", used)
    reserved = _unique_document_stem("CON", "vid_3", used)
    long_name = _unique_document_stem("标题" * 100, "vid_4", used)

    assert first == "同名视频"
    assert second == "同名视频（2）"
    assert reserved == "CON_视频"
    assert len(long_name) == MAX_DOCUMENT_STEM_LENGTH
