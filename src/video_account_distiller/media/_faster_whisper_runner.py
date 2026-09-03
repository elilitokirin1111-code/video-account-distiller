"""Standalone faster-whisper runner for an external Python environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _probe() -> int:
    faster_spec = importlib.util.find_spec("faster_whisper")
    ctranslate_spec = importlib.util.find_spec("ctranslate2")
    if faster_spec is None or ctranslate_spec is None:
        print(
            json.dumps(
                {
                    "available": False,
                    "reason": "faster_whisper_or_ctranslate2_not_installed",
                },
                ensure_ascii=False,
            )
        )
        return 1

    cuda_detected = shutil.which("nvidia-smi") is not None
    print(
        json.dumps(
            {
                "available": True,
                "faster_whisper_version": importlib.metadata.version("faster-whisper"),
                "ctranslate2_version": importlib.metadata.version("ctranslate2"),
                "cuda_devices": 1 if cuda_detected else 0,
                "device": "cuda" if cuda_detected else "cpu",
                "compute_type": "int8_float16" if cuda_detected else "int8",
            },
            ensure_ascii=False,
        )
    )
    return 0


def _transcribe(args: argparse.Namespace) -> int:
    from faster_whisper import (  # type: ignore[import-not-found]
        BatchedInferencePipeline,
        WhisperModel,
    )

    model = WhisperModel(
        args.model,
        device=args.device,
        compute_type=args.compute_type,
    )
    language = None if args.language == "auto" else args.language
    options: dict[str, Any] = {
        "language": language,
        "beam_size": args.beam_size,
        "vad_filter": args.vad_filter,
    }
    if args.batch_size > 1:
        pipeline = BatchedInferencePipeline(model=model)
        segments, info = pipeline.transcribe(
            str(args.source),
            batch_size=args.batch_size,
            **options,
        )
    else:
        segments, info = model.transcribe(str(args.source), **options)

    normalized = []
    for index, segment in enumerate(segments, start=1):
        text = str(segment.text or "").strip()
        if not text:
            continue
        normalized.append(
            {
                "id": index,
                "start": float(segment.start),
                "end": float(segment.end),
                "text": text,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "language": getattr(info, "language", language or "unknown"),
                "segments": normalized,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="base")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--vad-filter", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.probe:
        return _probe()
    if args.source is None or args.output is None:
        raise SystemExit("--source and --output are required")
    return _transcribe(args)


if __name__ == "__main__":  # pragma: no cover - external process entry point
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
