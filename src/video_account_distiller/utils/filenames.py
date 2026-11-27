"""Readable, cross-platform filenames for exported knowledge documents."""

from __future__ import annotations

import re

MAX_DOCUMENT_STEM_LENGTH = 80
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "CONIN$",
    "CONOUT$",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def readable_document_stem(value: str | None, fallback: str) -> str:
    """Create a readable filename stem without Windows-invalid characters."""

    cleaned = re.sub(r'[\x00-\x1f\\/:*?"<>|]', "", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = re.sub(r'[\x00-\x1f\\/:*?"<>|]', "", fallback)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .") or "未命名文档"
    device_name, separator, remainder = cleaned.partition(".")
    if device_name.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{device_name}_视频{separator}{remainder}"
    cleaned = cleaned[:MAX_DOCUMENT_STEM_LENGTH].rstrip(" .")
    return cleaned or "未命名文档"


def unique_document_stem(
    value: str | None,
    fallback: str,
    used: set[str],
) -> str:
    """Return a readable stem, adding a deterministic human suffix for duplicates."""

    base = readable_document_stem(value, fallback)
    stem = base
    suffix_index = 2
    while stem.casefold() in used:
        suffix = f"（{suffix_index}）"
        stem = f"{base[: MAX_DOCUMENT_STEM_LENGTH - len(suffix)]}{suffix}".rstrip(" .")
        suffix_index += 1
    used.add(stem.casefold())
    return stem
