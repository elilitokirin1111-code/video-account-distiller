"""Per-user desktop settings and secure secret persistence."""

from __future__ import annotations

import os
from pathlib import Path

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import BaseModel, ConfigDict, Field

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.utils.io import atomic_write_json, read_json

DESKTOP_KEYRING_SERVICE = "video-account-distiller"


def default_desktop_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "VideoAccountDistiller"
    return Path.home() / ".video-account-distiller" / "desktop"


class DesktopSettings(BaseModel):
    """Non-secret desktop preferences safe to serialize to JSON."""

    model_config = ConfigDict(extra="ignore")

    project_path: str | None = None
    account_url: str = ""
    collection_provider: str = "mediacrawler"
    collection_count: int = Field(default=20, ge=1, le=20_000)
    collect_all_videos: bool = False
    media_limit: int = Field(default=20, ge=0, le=20_000)
    distillation_mode: str = "knowledge"
    analysis_focus: str = "general"
    whisper_backend: str = "auto"
    whisper_model: str = "base"
    vision_provider: str = "ollama"
    vision_model: str = "qwen3-vl-8b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    cloud_credential_provider: str = "bailian"
    cloud_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    cloud_text_model: str = "qwen-plus"
    cloud_vision_model: str = "qwen-vl-max"
    video_knowledge_provider: str = "ollama"
    video_knowledge_model: str = "qwen3:8b"
    weknora_base_url: str = "http://127.0.0.1:8080"
    weknora_kb_id: str = ""
    weknora_kb_name: str = ""


class DesktopSettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (default_desktop_data_dir() / "settings.json")

    def load(self) -> DesktopSettings:
        if not self.path.is_file():
            return DesktopSettings()
        try:
            return DesktopSettings.model_validate(read_json(self.path))
        except (OSError, ValueError):
            return DesktopSettings()

    def save(self, settings: DesktopSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, settings.model_dump(mode="json"))


class DesktopSecretStore:
    """Store desktop-only secrets in Windows Credential Manager/keyring."""

    @staticmethod
    def _username(name: str) -> str:
        return f"desktop:{name.strip().lower()}"

    def get(self, name: str) -> str | None:
        try:
            value = keyring.get_password(DESKTOP_KEYRING_SERVICE, self._username(name))
        except KeyringError:
            return None
        return value.strip() if isinstance(value, str) and value.strip() else None

    def set(self, name: str, secret: str) -> None:
        value = secret.strip()
        if not value:
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "Secret cannot be empty")
        try:
            keyring.set_password(DESKTOP_KEYRING_SERVICE, self._username(name), value)
        except KeyringError as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "The operating-system credential store is unavailable",
            ) from exc

    def delete(self, name: str) -> bool:
        if self.get(name) is None:
            return False
        try:
            keyring.delete_password(DESKTOP_KEYRING_SERVICE, self._username(name))
        except PasswordDeleteError:
            return False
        except KeyringError as exc:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "The operating-system credential store is unavailable",
            ) from exc
        return True
