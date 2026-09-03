"""Persistent per-user cloud credentials backed by the operating-system keyring."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from video_account_distiller.errors import DistillerError, ErrorCode

KEYRING_SERVICE = "video-account-distiller"
CREDENTIAL_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "bailian": "DASHSCOPE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


class CloudCredentialStore(Protocol):
    def get(self, provider: str) -> str | None: ...

    def set(self, provider: str, credential: str) -> None: ...

    def delete(self, provider: str) -> bool: ...


class KeyringCloudCredentialStore:
    """Store secrets in Windows Credential Manager or the platform's secure keyring."""

    @staticmethod
    def _username(provider: str) -> str:
        return f"cloud-model:{provider}"

    def get(self, provider: str) -> str | None:
        try:
            value = keyring.get_password(KEYRING_SERVICE, self._username(provider))
        except KeyringError:
            return None
        return value.strip() if isinstance(value, str) and value.strip() else None

    def set(self, provider: str, credential: str) -> None:
        value = credential.strip()
        if not value:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Cloud API credential cannot be empty")
        try:
            keyring.set_password(KEYRING_SERVICE, self._username(provider), value)
        except KeyringError as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "The operating-system credential store is unavailable",
                details={"provider": provider},
            ) from exc

    def delete(self, provider: str) -> bool:
        existed = self.get(provider) is not None
        if not existed:
            return False
        try:
            keyring.delete_password(KEYRING_SERVICE, self._username(provider))
        except PasswordDeleteError:
            return False
        except KeyringError as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "The operating-system credential store is unavailable",
                details={"provider": provider},
            ) from exc
        return True


@dataclass(frozen=True)
class ResolvedCloudCredential:
    value: str
    source: str


def resolve_cloud_credential(
    store: CloudCredentialStore,
    provider: str,
) -> ResolvedCloudCredential | None:
    stored = store.get(provider)
    if stored is not None:
        return ResolvedCloudCredential(stored, "operating_system_keyring")
    environment = CREDENTIAL_ENVIRONMENTS[provider]
    value = os.environ.get(environment, "").strip()
    if value:
        return ResolvedCloudCredential(value, environment)
    return None


def cloud_credential_status(
    store: CloudCredentialStore,
    provider: str,
) -> dict[str, object]:
    resolved = resolve_cloud_credential(store, provider)
    return {
        "configured": resolved is not None,
        "source": resolved.source if resolved is not None else None,
        "environment_fallback": CREDENTIAL_ENVIRONMENTS[provider],
        "persisted_in_project": False,
        "stored_in_os_keyring": store.get(provider) is not None,
    }
