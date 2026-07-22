"""Stable domain errors shared by the library and CLI."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INPUT_MISSING = "E_INPUT_MISSING"
    SCHEMA_INVALID = "E_SCHEMA_INVALID"
    FIELD_MAPPING_REQUIRED = "E_FIELD_MAPPING_REQUIRED"
    DUPLICATE_RECORD = "E_DUPLICATE_RECORD"
    PLATFORM_UNSUPPORTED = "E_PLATFORM_UNSUPPORTED"
    PROJECT_EXISTS = "E_PROJECT_EXISTS"
    PROJECT_NOT_INITIALIZED = "E_PROJECT_NOT_INITIALIZED"
    RAW_INTEGRITY = "E_RAW_INTEGRITY"
    QUERY_FAILED = "E_QUERY_FAILED"
    INSUFFICIENT_SAMPLE = "E_INSUFFICIENT_SAMPLE"
    REPORT_GENERATION = "E_REPORT_GENERATION"
    INTERNAL = "E_INTERNAL"


EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.INPUT_MISSING: 2,
    ErrorCode.SCHEMA_INVALID: 3,
    ErrorCode.FIELD_MAPPING_REQUIRED: 4,
    ErrorCode.DUPLICATE_RECORD: 5,
    ErrorCode.PLATFORM_UNSUPPORTED: 6,
    ErrorCode.PROJECT_EXISTS: 7,
    ErrorCode.PROJECT_NOT_INITIALIZED: 8,
    ErrorCode.RAW_INTEGRITY: 9,
    ErrorCode.QUERY_FAILED: 10,
    ErrorCode.INSUFFICIENT_SAMPLE: 11,
    ErrorCode.REPORT_GENERATION: 12,
    ErrorCode.INTERNAL: 70,
}


class DistillerError(Exception):
    """Expected failure with a stable machine-readable error code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def exit_code(self) -> int:
        """Return the stable process exit code for this error."""

        return EXIT_CODES[self.code]

    def as_dict(self) -> dict[str, Any]:
        """Return the stable JSON error envelope."""

        return {
            "ok": False,
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            },
        }
