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
    MODEL_UNAVAILABLE = "E_MODEL_UNAVAILABLE"
    MODEL_SCHEMA_INVALID = "E_MODEL_SCHEMA_INVALID"
    MEDIA_DECODE = "E_MEDIA_DECODE"
    ADAPTER_AUTH = "E_ADAPTER_AUTH"
    RATE_LIMIT = "E_RATE_LIMIT"
    ADAPTER_RESPONSE = "E_ADAPTER_RESPONSE"
    PROFILE_URL_INVALID = "E_PROFILE_URL_INVALID"
    PROVIDER_COST_CONFIRMATION_REQUIRED = "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
    MEDIACRAWLER_UNAVAILABLE = "E_MEDIACRAWLER_UNAVAILABLE"
    BROWSER_LOGIN_REQUIRED = "E_BROWSER_LOGIN_REQUIRED"
    COLLECTION_TIMEOUT = "E_COLLECTION_TIMEOUT"
    MEDIA_DOWNLOAD_FAILED = "E_MEDIA_DOWNLOAD_FAILED"
    TRANSCRIPTION_UNAVAILABLE = "E_TRANSCRIPTION_UNAVAILABLE"
    TRANSCRIPTION_FAILED = "E_TRANSCRIPTION_FAILED"
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
    ErrorCode.MODEL_UNAVAILABLE: 13,
    ErrorCode.MODEL_SCHEMA_INVALID: 14,
    ErrorCode.MEDIA_DECODE: 15,
    ErrorCode.ADAPTER_AUTH: 16,
    ErrorCode.RATE_LIMIT: 17,
    ErrorCode.ADAPTER_RESPONSE: 18,
    ErrorCode.PROFILE_URL_INVALID: 19,
    ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED: 20,
    ErrorCode.MEDIACRAWLER_UNAVAILABLE: 21,
    ErrorCode.BROWSER_LOGIN_REQUIRED: 22,
    ErrorCode.COLLECTION_TIMEOUT: 23,
    ErrorCode.MEDIA_DOWNLOAD_FAILED: 24,
    ErrorCode.TRANSCRIPTION_UNAVAILABLE: 25,
    ErrorCode.TRANSCRIPTION_FAILED: 26,
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
