from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

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
    pass


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
