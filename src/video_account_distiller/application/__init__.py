"""Application services shared by the native desktop client."""

from video_account_distiller.application.desktop_api import DesktopApiClient, DesktopApiError
from video_account_distiller.application.desktop_runtime import (
    EmbeddedApiServer,
    LocalServiceSupervisor,
    ServiceStatus,
)
from video_account_distiller.application.desktop_settings import (
    DesktopSecretStore,
    DesktopSettings,
    DesktopSettingsStore,
)
from video_account_distiller.application.desktop_updates import (
    AvailableDesktopUpdate,
    DesktopReleaseAsset,
    DesktopUpdateError,
    DesktopUpdateService,
    PreparedDesktopUpdate,
    cleanup_stale_updates,
)
from video_account_distiller.application.knowledge_packages import (
    KnowledgeBundleSummary,
    KnowledgePackageService,
)

__all__ = [
    "AvailableDesktopUpdate",
    "DesktopApiClient",
    "DesktopApiError",
    "DesktopSecretStore",
    "DesktopSettings",
    "DesktopSettingsStore",
    "DesktopReleaseAsset",
    "DesktopUpdateError",
    "DesktopUpdateService",
    "EmbeddedApiServer",
    "KnowledgeBundleSummary",
    "KnowledgePackageService",
    "LocalServiceSupervisor",
    "PreparedDesktopUpdate",
    "ServiceStatus",
    "cleanup_stale_updates",
]
