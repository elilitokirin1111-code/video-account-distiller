"""TikHub response-shape drift detection for production collection runs."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal

from video_account_distiller.collection.providers import (
    COMMENTS_PATH,
    POSTS_PATHS,
    PROFILE_PATH,
    RESOLVE_PATH,
)
from video_account_distiller.models import (
    CollectionProviderKind,
    ProviderDriftIssue,
    ProviderDriftReport,
    ProviderDriftSeverity,
    ProviderRawPage,
)
from video_account_distiller.utils.hashing import sha256_json

TIKHUB_CONTRACT_VERSION = "2026-07-30"
_POST_ENDPOINTS = frozenset(POSTS_PATHS.values())


def _provider_data(payload: dict[str, Any]) -> object:
    return payload.get("data") if "data" in payload else payload


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _has_scalar(value: object, keys: tuple[str, ...]) -> bool:
    return any(
        isinstance(item, dict)
        and any(isinstance(item.get(key), (str, int)) and str(item[key]).strip() for key in keys)
        for item in _walk(value)
    )


def _find_list(value: object, keys: tuple[str, ...]) -> tuple[bool, list[dict[str, Any]]]:
    for item in _walk(value):
        if not isinstance(item, dict):
            continue
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, list):
                return True, [child for child in candidate if isinstance(child, dict)]
    return False, []


def _shape_paths(value: object, prefix: str = "$", depth: int = 0) -> set[str]:
    """Return a bounded value-free response signature suitable for audit fingerprints."""

    if depth >= 8:
        return {f"{prefix}:depth-limit"}
    if isinstance(value, dict):
        paths = {f"{prefix}:object"}
        for key in sorted(str(item) for item in value):
            paths.update(_shape_paths(value[key], f"{prefix}.{key}", depth + 1))
        return paths
    if isinstance(value, list):
        paths = {f"{prefix}:array"}
        for item in value[:5]:
            paths.update(_shape_paths(item, f"{prefix}[]", depth + 1))
        return paths
    if value is None:
        kind = "null"
    elif isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)):
        kind = "number"
    elif isinstance(value, str):
        kind = "string"
    else:
        kind = type(value).__name__
    return {f"{prefix}:{kind}"}


class TikHubDriftDetector:
    """Validate mapping-critical response paths while allowing additive provider fields."""

    def evaluate(self, pages: list[ProviderRawPage]) -> ProviderDriftReport:
        issues: list[ProviderDriftIssue] = []
        by_endpoint: dict[str, list[ProviderRawPage]] = {}
        shape_paths: set[str] = set()
        endpoint_counts: dict[str, int] = {}
        for page in pages:
            by_endpoint.setdefault(page.endpoint, []).append(page)
            endpoint_counts[page.endpoint] = endpoint_counts.get(page.endpoint, 0) + 1
            shape_paths.update(_shape_paths(page.payload, prefix=f"endpoint:{page.endpoint}"))

        self._require_endpoint(by_endpoint, RESOLVE_PATH, issues)
        self._require_endpoint(by_endpoint, PROFILE_PATH, issues)
        post_pages = [
            page
            for endpoint, endpoint_pages in by_endpoint.items()
            if endpoint in _POST_ENDPOINTS
            for page in endpoint_pages
        ]
        if not post_pages:
            issues.append(
                self._issue(
                    "/douyin/posts",
                    ProviderDriftSeverity.ERROR,
                    "posts_endpoint_missing",
                    "No supported TikHub Douyin posts response was retained.",
                )
            )

        for page in by_endpoint.get(RESOLVE_PATH, []):
            if not _has_scalar(_provider_data(page.payload), ("sec_user_id", "sec_uid")):
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.ERROR,
                        "resolve_account_id_missing",
                        "Resolve response no longer exposes sec_user_id or sec_uid.",
                    )
                )
        for page in by_endpoint.get(PROFILE_PATH, []):
            data = _provider_data(page.payload)
            if not _has_scalar(data, ("nickname", "name")):
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.ERROR,
                        "profile_name_missing",
                        "Profile response no longer exposes a recognizable display name.",
                    )
                )
            if not _has_scalar(data, ("follower_count", "followers", "fans_count")):
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.WARNING,
                        "profile_followers_missing",
                        "Profile response has no recognized follower-count field.",
                    )
                )
        for page in post_pages:
            present, items = _find_list(
                _provider_data(page.payload),
                ("aweme_list", "items", "videos"),
            )
            if not present:
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.ERROR,
                        "posts_list_missing",
                        "Posts response no longer exposes aweme_list, items, or videos.",
                    )
                )
                continue
            if items and any(
                not _has_scalar(item, ("aweme_id", "item_id", "id")) for item in items[:5]
            ):
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.ERROR,
                        "post_id_missing",
                        "A sampled post has no recognized video identifier.",
                    )
                )
            if items and all(
                not any(
                    isinstance(candidate, dict) and "statistics" in candidate
                    for candidate in _walk(item)
                )
                for item in items[:5]
            ):
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.WARNING,
                        "post_statistics_missing",
                        "Sampled posts have no recognized statistics object.",
                    )
                )
        for page in by_endpoint.get(COMMENTS_PATH, []):
            present, items = _find_list(
                _provider_data(page.payload),
                ("comments", "comment_list", "items"),
            )
            if not present:
                issues.append(
                    self._issue(
                        page.endpoint,
                        ProviderDriftSeverity.ERROR,
                        "comments_list_missing",
                        "Comments response no longer exposes a recognized comments list.",
                    )
                )
                continue
            for item in items[:5]:
                if not _has_scalar(item, ("cid", "comment_id", "id")):
                    issues.append(
                        self._issue(
                            page.endpoint,
                            ProviderDriftSeverity.ERROR,
                            "comment_id_missing",
                            "A sampled comment has no recognized comment identifier.",
                        )
                    )
                if not _has_scalar(item, ("text", "content", "comment_text")):
                    issues.append(
                        self._issue(
                            page.endpoint,
                            ProviderDriftSeverity.ERROR,
                            "comment_text_missing",
                            "A sampled comment has no recognized text field.",
                        )
                    )

        has_errors = any(issue.severity == ProviderDriftSeverity.ERROR for issue in issues)
        status: Literal["pass", "warn", "fail"] = (
            "fail" if has_errors else "warn" if issues else "pass"
        )
        return ProviderDriftReport(
            provider=CollectionProviderKind.TIKHUB,
            contract_version=TIKHUB_CONTRACT_VERSION,
            checked_at=datetime.now(UTC),
            status=status,
            ok=not has_errors,
            schema_fingerprint=sha256_json(sorted(shape_paths)),
            endpoints=dict(sorted(endpoint_counts.items())),
            issues=issues,
        )

    @staticmethod
    def _require_endpoint(
        by_endpoint: dict[str, list[ProviderRawPage]],
        endpoint: str,
        issues: list[ProviderDriftIssue],
    ) -> None:
        if endpoint not in by_endpoint:
            issues.append(
                TikHubDriftDetector._issue(
                    endpoint,
                    ProviderDriftSeverity.ERROR,
                    "required_endpoint_missing",
                    "A mapping-critical TikHub response was not retained.",
                )
            )

    @staticmethod
    def _issue(
        endpoint: str,
        severity: ProviderDriftSeverity,
        code: str,
        message: str,
    ) -> ProviderDriftIssue:
        return ProviderDriftIssue(
            endpoint=endpoint,
            severity=severity,
            code=code,
            message=message,
        )
