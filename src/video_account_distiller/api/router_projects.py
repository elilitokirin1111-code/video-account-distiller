"""Project lifecycle endpoints — init, list, validate."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    CloudCredentialUpdate,
    CloudModelSettingsUpdate,
    ProjectInitRequest,
)
from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import (
    AnalysisProviderKind,
    CloudCredentialStore,
    cloud_credential_status,
    probe_account_analysis_provider,
    resolve_cloud_credential,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_text
from video_account_distiller.validation import validate_project

router = APIRouter()


def _credential_store(request: Request) -> CloudCredentialStore:
    return cast(CloudCredentialStore, request.app.state.cloud_credentials)


def _cloud_provider_credentials(store: CloudCredentialStore) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for provider in AnalysisProviderKind:
        status = cloud_credential_status(store, provider.value)
        result[provider.value] = {
            **status,
            "api_key_configured": status["configured"],
            "api_key_env": status["environment_fallback"],
        }
    return result


def _provider_executor(request: Request, provider: AnalysisProviderKind) -> Any:
    if provider is AnalysisProviderKind.OPENAI:
        return getattr(request.app.state, "openai_executor", None)
    if provider is AnalysisProviderKind.DEEPSEEK:
        return getattr(request.app.state, "deepseek_executor", None)
    return getattr(request.app.state, "bailian_executor", None)


@router.put("/cloud-model/credentials/{provider}")
async def save_cloud_model_credential(
    provider: AnalysisProviderKind,
    body: CloudCredentialUpdate,
    request: Request,
) -> dict[str, Any]:
    """Validate and persist a credential in the current user's OS keyring."""

    credential = body.api_key.get_secret_value()
    result = await asyncio.to_thread(
        probe_account_analysis_provider,
        provider,
        credential=credential,
        executor=_provider_executor(request, provider),
    )
    store = _credential_store(request)
    store.set(provider.value, credential)
    return {
        **result,
        "credential_persisted": True,
        "credential_storage": "operating_system_keyring",
    }


@router.post("/cloud-model/credentials/{provider}/probe")
async def probe_saved_cloud_model_credential(
    provider: AnalysisProviderKind,
    request: Request,
) -> dict[str, Any]:
    """Verify the saved credential and return supported models without exposing the key."""

    resolved = resolve_cloud_credential(_credential_store(request), provider.value)
    if resolved is None:
        raise DistillerError(
            ErrorCode.ADAPTER_AUTH,
            "No saved cloud API credential is available",
            details={"provider": provider.value},
        )
    result = await asyncio.to_thread(
        probe_account_analysis_provider,
        provider,
        credential=resolved.value,
        executor=_provider_executor(request, provider),
    )
    return {**result, "credential_source": resolved.source}


@router.delete("/cloud-model/credentials/{provider}")
async def delete_cloud_model_credential(
    provider: AnalysisProviderKind,
    request: Request,
) -> dict[str, Any]:
    """Delete the provider credential from the current user's OS keyring."""

    deleted = _credential_store(request).delete(provider.value)
    return {"ok": True, "provider": provider.value, "deleted": deleted}


@router.post("/projects/init")
async def init_project(body: ProjectInitRequest) -> dict[str, Any]:
    """Initialise a new distiller project at *path*."""
    template = (
        Path(body.config_template).expanduser() / "distiller.yaml" if body.config_template else None
    )
    layout, already = ProjectLayout.initialize(
        Path(body.path),
        project_name=body.name,
        config_template=template,
    )
    if not already:
        # Web-created projects default to the local llama.cpp setup so
        # per-account folders work without extra configuration.
        config = load_config(layout.config_path)
        if config.models.text_provider is None and config.models.vision_provider is None:
            config.models.text_provider = "llamacpp"
            config.models.vision_provider = "llamacpp"
            atomic_write_text(layout.config_path, config.as_yaml())
    return {
        "ok": True,
        "data": {"project": str(layout.root), "already_initialized": already},
    }


@router.get("/projects/")
async def list_projects() -> dict[str, Any]:
    """Return known project directories (from environment or defaults)."""
    # Minimal: just report the project we know about
    return {"ok": True, "data": {"projects": []}}


@router.get("/projects/{project_path:path}/validate")
async def validate(project_path: str) -> dict[str, Any]:
    """Run the project validator and return findings."""
    layout = resolve_project(project_path)
    report = validate_project(layout, persist=False)
    return {"ok": True, "data": report.model_dump(mode="json")}


@router.get("/projects/{project_path:path}/settings/cloud-model")
async def cloud_model_settings(project_path: str, request: Request) -> dict[str, Any]:
    """Return the project-level cloud-upload permission without any credential."""

    layout = resolve_project(project_path)
    config = load_config(layout.config_path)
    providers = _cloud_provider_credentials(_credential_store(request))
    return {
        "ok": True,
        "allow_cloud_model_upload": config.privacy.allow_cloud_model_upload,
        "api_key_persisted": providers["openai"]["stored_in_os_keyring"],
        "api_key_configured": providers["openai"]["api_key_configured"],
        "api_key_env": providers["openai"]["api_key_env"],
        "providers": providers,
    }


@router.put("/projects/{project_path:path}/settings/cloud-model")
async def update_cloud_model_settings(
    project_path: str,
    body: CloudModelSettingsUpdate,
    request: Request,
) -> dict[str, Any]:
    """Persist only the project permission flag; API keys remain environment-only."""

    layout = resolve_project(project_path)
    config = load_config(layout.config_path)
    privacy = config.privacy.model_copy(
        update={"allow_cloud_model_upload": body.allow_cloud_model_upload}
    )
    updated = config.model_copy(update={"privacy": privacy})
    atomic_write_text(layout.config_path, updated.as_yaml())
    providers = _cloud_provider_credentials(_credential_store(request))
    return {
        "ok": True,
        "allow_cloud_model_upload": updated.privacy.allow_cloud_model_upload,
        "api_key_persisted": providers["openai"]["stored_in_os_keyring"],
        "api_key_configured": providers["openai"]["api_key_configured"],
        "api_key_env": providers["openai"]["api_key_env"],
        "providers": providers,
    }
