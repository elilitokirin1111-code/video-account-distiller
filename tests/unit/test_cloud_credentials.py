from __future__ import annotations

from typing import Any

import pytest

from video_account_distiller.insights.cloud_credentials import (
    KEYRING_SERVICE,
    KeyringCloudCredentialStore,
    cloud_credential_status,
    resolve_cloud_credential,
)


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, provider: str) -> str | None:
        return self.values.get(provider)

    def set(self, provider: str, credential: str) -> None:
        self.values[provider] = credential

    def delete(self, provider: str) -> bool:
        return self.values.pop(provider, None) is not None


def test_stored_credential_wins_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryStore()
    store.set("bailian", "stored-secret")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "environment-secret")

    resolved = resolve_cloud_credential(store, "bailian")

    assert resolved is not None
    assert resolved.value == "stored-secret"
    assert resolved.source == "operating_system_keyring"
    assert cloud_credential_status(store, "bailian") == {
        "configured": True,
        "source": "operating_system_keyring",
        "environment_fallback": "DASHSCOPE_API_KEY",
        "persisted_in_project": False,
        "stored_in_os_keyring": True,
    }


def test_keyring_store_uses_provider_scoped_windows_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[tuple[str, str], str] = {}

    def get_password(service: str, username: str) -> str | None:
        return values.get((service, username))

    def set_password(service: str, username: str, value: str) -> None:
        values[(service, username)] = value

    def delete_password(service: str, username: str) -> None:
        del values[(service, username)]

    monkeypatch.setattr("keyring.get_password", get_password)
    monkeypatch.setattr("keyring.set_password", set_password)
    monkeypatch.setattr("keyring.delete_password", delete_password)
    store = KeyringCloudCredentialStore()

    store.set("openai", "  persistent-secret  ")

    assert store.get("openai") == "persistent-secret"
    assert values[(KEYRING_SERVICE, "cloud-model:openai")] == "persistent-secret"
    assert store.delete("openai") is True
    assert store.get("openai") is None
    assert store.delete("openai") is False


def test_keyring_store_does_not_expose_backend_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from keyring.errors import KeyringError

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise KeyringError("backend detail")

    monkeypatch.setattr("keyring.get_password", fail)

    assert KeyringCloudCredentialStore().get("openai") is None
