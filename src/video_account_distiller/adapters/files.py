"""CSV, JSON, and JSONL input adapter."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from video_account_distiller.errors import DistillerError, ErrorCode


class FileAdapter:
    """Load user-provided export files without network access."""

    supported_suffixes = {".csv", ".json", ".jsonl", ".ndjson"}

    def validate_source(self, source: Path) -> None:
        """Validate that an input exists and has a supported format."""

        if not source.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Input file not found: {source}")
        if source.suffix.lower() not in self.supported_suffixes:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Unsupported file format: {source.suffix}",
                details={"supported": sorted(self.supported_suffixes)},
            )

    def load_records(self, source: Path) -> list[dict[str, Any]]:
        """Read CSV, JSON array/object, or newline-delimited JSON records."""

        self.validate_source(source)
        suffix = source.suffix.lower()
        try:
            if suffix == ".csv":
                with source.open("r", encoding="utf-8-sig", newline="") as handle:
                    return [dict(row) for row in csv.DictReader(handle)]
            if suffix in {".jsonl", ".ndjson"}:
                records: list[dict[str, Any]] = []
                for line_number, line in enumerate(
                    source.read_text(encoding="utf-8-sig").splitlines(), start=1
                ):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError(f"line {line_number} is not an object")
                    records.append(value)
                return records
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
            return [dict(item) for item in values]
        except (UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"Could not parse input file: {source}",
                details={"reason": str(exc)},
            ) from exc
