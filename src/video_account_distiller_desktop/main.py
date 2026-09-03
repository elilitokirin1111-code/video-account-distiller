"""Native desktop entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from video_account_distiller.application import (
    DesktopApiClient,
    DesktopSecretStore,
    DesktopSettingsStore,
    EmbeddedApiServer,
    LocalServiceSupervisor,
)
from video_account_distiller.application.desktop_updates import DesktopUpdateService
from video_account_distiller.collection.mediacrawler import (
    MEDIACRAWLER_REQUIRED_FILES,
    default_mediacrawler_home,
)
from video_account_distiller.config import MediaSection
from video_account_distiller.media import FFmpegMediaBackend
from video_account_distiller_desktop.window import DistillerMainWindow


def _configure_windows_error_mode() -> None:
    """Keep recoverable child-process loader failures inside the task UI."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        current_mode = int(kernel32.GetErrorMode())
        # Microsoft recommends SEM_FAILCRITICALERRORS for unattended GUI apps.
        # Keep WER enabled so a native application crash still leaves diagnostics.
        kernel32.SetErrorMode(current_mode | 0x0001)
    except (AttributeError, OSError):
        pass


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="VideoAccountDistiller")
    parser.add_argument(
        "--smoke-test-output",
        type=Path,
        help="Start the packaged native application stack and write a JSON acceptance result.",
    )
    return parser.parse_args(argv)


def _application(argv: list[str]) -> QApplication:
    app = QApplication([sys.argv[0], *argv])
    app.setApplicationName("Video Account Distiller")
    app.setOrganizationName("Video Account Distiller")
    app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "app-icon.svg")))
    return app


def _run_smoke_test(output_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = _application([])
    with tempfile.TemporaryDirectory(prefix="distiller-desktop-smoke-") as temporary:
        temporary_root = Path(temporary)
        supervisor = LocalServiceSupervisor(
            api=EmbeddedApiServer(task_db_path=temporary_root / "smoke-tasks.sqlite3")
        )
        client: DesktopApiClient | None = None
        try:
            supervisor.start()
            client = DesktopApiClient(supervisor.api.base_url)
            project_path = temporary_root / "验收项目"
            initialized = client.initialize_project(project_path, name="桌面打包验收")
            validation = client.validate_project(project_path)
            settings_store = DesktopSettingsStore(temporary_root / "settings.json")
            window = DistillerMainWindow(
                supervisor=supervisor,
                client=client,
                settings_store=settings_store,
                secret_store=DesktopSecretStore(),
                settings=settings_store.load(),
            )
            page_count = window.stack.count()
            progress_stage_count = len(window.task_progress_panel.stages.items)
            animated_wait_feedback = all(
                hasattr(window.footer, member) for member in ("begin", "finish", "pulse")
            )
            window.task_timer.stop()
            window.close()
            app.processEvents()
            mediacrawler_home = default_mediacrawler_home()
            mediacrawler_missing = [
                relative.as_posix()
                for relative in MEDIACRAWLER_REQUIRED_FILES
                if not (mediacrawler_home / relative).is_file()
            ]
            media_backend = FFmpegMediaBackend(MediaSection())
            payload = {
                "ok": True,
                "native_qt_window": True,
                "page_count": page_count,
                "progress_stage_count": progress_stage_count,
                "animated_wait_feedback": animated_wait_feedback,
                "mediacrawler_runtime_complete": not mediacrawler_missing,
                "mediacrawler_runtime_missing": mediacrawler_missing,
                "ffmpeg_available": media_backend.available,
                "ffmpeg_external_process_ready": media_backend.version is not None,
                "ffmpeg_version": media_backend.version,
                "health": client.health(),
                "project_initialized": initialized.get("ok") is True,
                "project_valid": validation.get("ok") is True,
                "api_base_url": supervisor.api.base_url,
            }
        except Exception as exc:  # pragma: no cover - packaged failure evidence
            payload = {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        finally:
            if client is not None:
                client.close()
            supervisor.stop()
    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = destination.with_suffix(destination.suffix + ".tmp")
    temporary_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_output, destination)
    if not payload["ok"]:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    _configure_windows_error_mode()
    arguments = _arguments(list(sys.argv[1:] if argv is None else argv))
    if arguments.smoke_test_output is not None:
        _run_smoke_test(arguments.smoke_test_output)
        return

    update_service = DesktopUpdateService()
    try:
        update_service.cleanup_stale_updates()
    except (OSError, ValueError):
        pass
    finally:
        update_service.close()

    settings_store = DesktopSettingsStore()
    settings = settings_store.load()
    secrets = DesktopSecretStore()
    tikhub_key = secrets.get("tikhub-api-key")
    if tikhub_key:
        os.environ["TIKHUB_API_KEY"] = tikhub_key

    app = _application([])

    supervisor = LocalServiceSupervisor()
    startup_error: str | None = None
    try:
        supervisor.start()
    except RuntimeError as exc:
        startup_error = str(exc)
    client = DesktopApiClient(supervisor.api.base_url)
    window = DistillerMainWindow(
        supervisor=supervisor,
        client=client,
        settings_store=settings_store,
        secret_store=secrets,
        settings=settings,
    )
    window.show()
    if startup_error:
        QMessageBox.critical(window, "本地服务启动失败", startup_error)
    exit_code = app.exec()
    client.close()
    supervisor.stop()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
