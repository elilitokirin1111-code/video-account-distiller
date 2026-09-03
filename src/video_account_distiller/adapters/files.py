"""CSV, JSON, and JSONL input adapter."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from video_account_distiller.errors import DistillerError, ErrorCode

# Safety limits to prevent OOM / excessive processing from user-supplied files.
_MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MiB
_MAX_RECORDS = 1_000_000
_MAX_FIELD_LENGTH = 50_000


class FileAdapter:
    """Load user-provided export files without network access."""

    supported_suffixes = {".csv", ".json", ".jsonl", ".ndjson"}

    def validate_source(self, source: Path) -> None:
        """Validate that an input exists, has a supported format, and is not excessive."""

        if not source.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Input file not found: {source}")
        if source.suffix.lower() not in self.supported_suffixes:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Unsupported file format: {source.suffix}",
                details={"supported": sorted(self.supported_suffixes)},
            )
        size = source.stat().st_size
        if size > _MAX_FILE_BYTES:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"Input file too large: {size} bytes (max {_MAX_FILE_BYTES})",
                details={"file_bytes": size, "max_bytes": _MAX_FILE_BYTES},
            )

    def load_records(self, source: Path) -> list[dict[str, Any]]:
        """Read CSV, JSON array/object, or newline-delimited JSON records."""

        self.validate_source(source)
        suffix = source.suffix.lower()
        records: list[dict[str, Any]]
        try:
            if suffix == ".csv":
                with source.open("r", encoding="utf-8-sig", newline="") as handle:
                    records = [dict(row) for row in csv.DictReader(handle)]
            elif suffix in {".jsonl", ".ndjson"}:
                records = []
                for line_number, line in enumerate(
                    source.read_text(encoding="utf-8-sig").split("\n"),
                    start=1,
                ):
                    line = line.rstrip("\r")
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError(f"line {line_number} is not an object")
                    records.append(value)
                    if len(records) > _MAX_RECORDS:
                        raise DistillerError(
                            ErrorCode.SCHEMA_INVALID,
                            f"Too many records: exceeded {_MAX_RECORDS}",
                        )
            else:
                payload = json.loads(source.read_text(encoding="utf-8-sig"))
                if isinstance(payload, list):
                    values = payload
                elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
                    values = payload["records"]
                elif isinstance(payload, dict):
                    values = [payload]
                else:
                    raise ValueError("JSON root must be an object or array")
                if not all(isinstance(item, dict) for item in values):
                    raise ValueError("all JSON records must be objects")
                records = [dict(item) for item in values]
            if len(records) > _MAX_RECORDS:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    f"Too many records: {len(records)} (max {_MAX_RECORDS})",
                )
            # Validate field lengths
            for idx, record in enumerate(records):
                for key, val in record.items():
                    if isinstance(val, str) and len(val) > _MAX_FIELD_LENGTH:
                        raise DistillerError(
                            ErrorCode.SCHEMA_INVALID,
                            f"Field '{key}' in record {idx} exceeds max length {_MAX_FIELD_LENGTH}",
                            details={"field": key, "record_index": idx},
                        )
            return records
        except DistillerError:
            raise
        except (UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Could not parse input file: {source}",
                details={"reason": str(exc)},
            ) from exc
