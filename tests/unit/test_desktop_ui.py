from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Api:
    running = False


class _Supervisor:
    api = _Api()

    def statuses(self, **_kwargs: Any) -> list[Any]:
        return []

    def start_ollama(self, **_kwargs: Any) -> bool:
        return False


class _Client:
    def list_project_accounts(self, _project: Path) -> list[dict[str, str]]:
        return []


class _Secrets:
    def get(self, _name: str) -> str | None:
        return None

    def set(self, _name: str, _secret: str) -> None:
        return None


def test_native_window_builds_secret_free_knowledge_workflow_payload(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    app = QApplication.instance() or QApplication([])
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, _Client()),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(
            distillation_mode="creative_learning",
            vision_provider="cloud",
            vision_model="qwen3.7-plus",
            cloud_credential_provider="bailian",
            cloud_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            cloud_text_base_url=(
                "https://workspace-demo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
            ),
            cloud_text_model="deepseek-v4-flash",
            cloud_vision_model="qwen3.7-plus",
            video_knowledge_provider="cloud",
            video_knowledge_model="deepseek-v4-flash",
        ),
    )
    window.account_url.setText("https://www.douyin.com/user/demo")

    payload = window._workflow_payload()

    assert window.stack.count() == 6
    assert window.mode_combo.currentText() == ("完整创作蒸馏 · 内容 / 选材 / 表达 / 拍摄 / 增长")
    assert payload["distillation_mode"] == "creative_learning"
    assert payload["distill_video_knowledge"] is True
    assert payload["vision_provider"] == "cloud"
    assert payload["vision_model"] == "qwen3.7-plus"
    assert payload["video_knowledge_provider"] == "cloud"
    assert payload["video_knowledge_model"] == "deepseek-v4-flash"
    assert payload["cloud_credential_provider"] == "bailian"
    assert payload["cloud_text_base_url"].endswith("/compatible-mode/v1")
    assert "cloud_api_key" not in payload
    assert "weknora" not in payload
    assert window.update_version.text().startswith("当前版本 ")
    assert window.update_button.text() == "检查更新"
    assert "覆盖当前安装目录" in window.update_status.text()
    assert window._active_update_task([{"task_id": "task-running", "status": "running"}]) == {
        "task_id": "task-running",
        "status": "running",
    }
    assert window._active_update_task([{"task_id": "task-complete", "status": "completed"}]) is None
    window.task_timer.stop()
    window.close()
    app.processEvents()


def test_task_progress_and_wait_feedback_reflect_live_work() -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller_desktop.window import _BusyStatusBar, _TaskProgressPanel

    app = QApplication.instance() or QApplication([])
    panel = _TaskProgressPanel()
    panel.set_task(
        {
            "task_id": "task-12345678",
            "status": "running",
            "stage": "video_knowledge",
            "progress": 0.58,
            "message": "正在提取逐视频知识",
            "created_at": "2026-09-02T09:00:00+08:00",
        }
    )

    assert panel.status.text() == "正在运行"
    assert panel.message.text() == "正在提取逐视频知识"
    assert panel._animation.endValue() == 58
    assert panel.stages.items[3][0].property("stageState") == "active"
    assert panel.stages.items[0][0].property("stageState") == "complete"

    panel.set_task(
        {
            "task_id": "task-12345678",
            "status": "running",
            "stage": "video_creative_distillation",
            "progress": 0.84,
            "message": "正在拆解选材与表达",
            "created_at": "2026-09-02T09:00:00+08:00",
        }
    )
    assert panel.stages.items[3][0].property("stageState") == "active"

    footer = _BusyStatusBar()
    footer.begin("正在检查项目与依赖")
    footer._started_at = time.monotonic() - 65
    footer._tick()

    assert footer.property("state") == "busy"
    assert "程序仍在工作" in footer.elapsed.text()

    footer.finish("预检完成")
    assert footer.text() == "预检完成"
    assert footer.elapsed.text() == ""
    panel._timer.stop()
    panel.close()
    footer.close()
    app.processEvents()


def test_weknora_account_selector_shows_friendly_names_and_preserves_ids(
    tmp_path: Path,
) -> None:
    from PySide6.QtWidgets import QApplication, QComboBox

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    app = QApplication.instance() or QApplication([])
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, _Client()),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(),
    )
    window.task_timer.stop()

    window._populate_sync_accounts(
        [
            {
                "account_id": "acc_second",
                "display_name": "第二家酒店",
                "handle": "hotel_two",
                "platform": "xiaohongshu",
            },
            {
                "account_id": "acc_first",
                "display_name": "小宁饱饱🐰",
                "handle": "LEN040223",
                "platform": "douyin",
            },
        ]
    )

    assert isinstance(window.sync_account_id, QComboBox)
    assert window.sync_account_id.isEditable() is True
    assert window.sync_account_id.currentIndex() == -1
    assert window.sync_account_id.itemText(0) == "小宁饱饱🐰 · @LEN040223 · 抖音"
    assert window.sync_account_id.itemData(0) == "acc_first"
    assert window.sync_account_id.itemText(1) == "第二家酒店 · @hotel_two · 小红书"
    assert window.sync_account_id.itemData(1) == "acc_second"

    window.sync_account_id.setCurrentIndex(1)
    assert window._selected_sync_account_id() == "acc_second"
    assert window.sync_account_id_value.text() == "acc_second"

    window._populate_sync_accounts(
        [
            {
                "account_id": "acc_second",
                "display_name": "第二家酒店",
                "handle": "hotel_two",
                "platform": "xiaohongshu",
            },
            {
                "account_id": "acc_first",
                "display_name": "小宁饱饱🐰",
                "handle": "LEN040223",
                "platform": "douyin",
            },
        ]
    )
    assert window.sync_account_id.currentData() == "acc_second"

    window.copy_sync_account_id()
    assert QApplication.clipboard().text() == "acc_second"
    window.close()
    app.processEvents()


def test_weknora_account_selector_autoselects_single_account_and_validates_manual_id(
    tmp_path: Path,
) -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    app = QApplication.instance() or QApplication([])
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, _Client()),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(),
    )
    window.task_timer.stop()

    window._populate_sync_accounts(
        [
            {
                "account_id": "acc_only",
                "display_name": "唯一账号",
                "handle": "only_one",
                "platform": "douyin",
            }
        ]
    )
    assert window.sync_account_id.currentData() == "acc_only"
    assert window.sync_account_id_value.text() == "acc_only"

    window._clear_sync_accounts()
    window.sync_account_id.setEditText("acc_manual_123")
    assert window._selected_sync_account_id() == "acc_manual_123"
    assert window.sync_account_id_value.text() == "acc_manual_123"

    window.sync_account_id.setEditText("平台昵称不是账号ID")
    with pytest.raises(ValueError, match="只接受 acc_ 开头"):
        window._selected_sync_account_id()
    window.close()
    app.processEvents()


def test_weknora_sync_uses_selected_account_item_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    class RecordingClient(_Client):
        def __init__(self) -> None:
            self.sync_kwargs: dict[str, Any] | None = None

        def sync_account_weknora(self, project: Path, **kwargs: Any) -> dict[str, Any]:
            self.sync_kwargs = {"project": project, **kwargs}
            return {"ok": True}

    app = QApplication.instance() or QApplication([])
    client = RecordingClient()
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, client),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(),
    )
    window.task_timer.stop()
    window._populate_sync_accounts(
        [
            {
                "account_id": "acc_real_id",
                "display_name": "用户看到的名称",
                "handle": "friendly_handle",
                "platform": "douyin",
            }
        ]
    )
    window.weknora_kb.addItem("运营知识库", "kb-1")
    monkeypatch.setattr(window, "_project", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(window, "_weknora_secret", lambda: "secret")

    def run_now(
        call: Any,
        on_success: Any,
        **_kwargs: Any,
    ) -> None:
        on_success(call())

    monkeypatch.setattr(window, "_run", run_now)
    window.sync_weknora()

    assert client.sync_kwargs is not None
    assert client.sync_kwargs["account_id"] == "acc_real_id"
    assert client.sync_kwargs["kb_id"] == "kb-1"
    assert client.sync_kwargs["project"] == tmp_path
    window.close()
    app.processEvents()


def test_selecting_knowledge_bundle_updates_weknora_account_selector(
    tmp_path: Path,
) -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    app = QApplication.instance() or QApplication([])
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, _Client()),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(),
    )
    window.task_timer.stop()
    window._populate_sync_accounts(
        [
            {
                "account_id": "acc_bundle",
                "display_name": "知识包账号",
                "handle": "bundle",
                "platform": "douyin",
            }
        ]
    )
    window._bundle_rows = [{"account_id": "acc_bundle"}]
    window.bundles_table.setRowCount(1)
    window.bundles_table.selectRow(0)
    app.processEvents()

    assert window.sync_account_id.currentData() == "acc_bundle"
    assert window.sync_account_id_value.text() == "acc_bundle"
    window.close()
    app.processEvents()


def test_unavailable_service_message_is_concise_but_actionable() -> None:
    from video_account_distiller_desktop.window import _service_display_message

    raw_error = "HTTPConnectionPool(host='127.0.0.1', port=11434): Max retries exceeded"

    assert _service_display_message("ollama", False, raw_error) == (
        "本地模型服务未启动，可点击下方按钮启动"
    )
    assert _service_display_message("ollama", True, "模型服务可达") == "模型服务可达"


def test_native_window_defers_close_until_active_worker_finishes(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from video_account_distiller.application import DesktopSettings, DesktopSettingsStore
    from video_account_distiller_desktop.window import DistillerMainWindow

    app = QApplication.instance() or QApplication([])
    window = DistillerMainWindow(
        supervisor=cast(Any, _Supervisor()),
        client=cast(Any, _Client()),
        settings_store=DesktopSettingsStore(tmp_path / "settings.json"),
        secret_store=cast(Any, _Secrets()),
        settings=DesktopSettings(),
    )
    completed: list[object] = []

    def delayed_result() -> str:
        time.sleep(0.08)
        return "done"

    window.show()
    app.processEvents()
    window._run(
        delayed_result,
        completed.append,
        message="closing worker regression",
        show_busy=False,
    )

    assert len(window._workers) == 1
    window.close()
    assert window._closing is True
    assert window.isVisible() is True

    deadline = time.monotonic() + 5
    while (window._workers or window.isVisible()) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)

    assert window._workers == {}
    assert completed == []
    assert window.isVisible() is False


def test_background_workers_survive_until_queued_callbacks_complete() -> None:
    """Exercise the PySide wrapper lifetime in a child process to contain native failures."""

    script = r"""
import gc
import json
import time

from PySide6.QtCore import QCoreApplication, QThreadPool

from video_account_distiller_desktop.window import DistillerMainWindow


class Harness:
    _run = DistillerMainWindow._run
    _start_worker = DistillerMainWindow._start_worker

    def __init__(self):
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        self._workers = {}
        self._closing = False


app = QCoreApplication([])
harness = Harness()
completed = []
failures = []
for index in range(40):
    harness._run(
        lambda value=index: (time.sleep(0.05), value)[1],
        completed.append,
        message="worker lifetime regression",
        on_failure=failures.append,
        show_busy=False,
    )

retained_after_submit = len(harness._workers)
gc.collect()
deadline = time.monotonic() + 10
while len(completed) + len(failures) < 40 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.005)
harness.pool.waitForDone(5000)
for _ in range(10):
    app.processEvents()
    time.sleep(0.001)

print(json.dumps({
    "retained_after_submit": retained_after_submit,
    "completed": len(completed),
    "failures": len(failures),
    "remaining": len(harness._workers),
}))
"""
    environment = dict(os.environ)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "retained_after_submit": 40,
        "completed": 40,
        "failures": 0,
        "remaining": 0,
    }
