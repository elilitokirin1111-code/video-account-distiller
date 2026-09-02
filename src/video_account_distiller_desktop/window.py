"""Qt-native desktop interface; no browser or embedded web view is used."""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from video_account_distiller.application import (
    DesktopApiClient,
    DesktopApiError,
    DesktopSecretStore,
    DesktopSettings,
    DesktopSettingsStore,
    KnowledgePackageService,
    LocalServiceSupervisor,
)
from video_account_distiller.errors import DistillerError
from video_account_distiller.storage import ProjectLayout


class _WorkerSignals(QObject):
    success = Signal(object)
    failure = Signal(object)


class _Worker(QRunnable):
    def __init__(self, call: Callable[[], Any]) -> None:
        super().__init__()
        self.call = call
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.call()
        except Exception as exc:  # noqa: BLE001 - cross-thread error boundary
            self.signals.failure.emit(exc)
        else:
            self.signals.success.emit(result)


def _button(text: str, *, primary: bool = False) -> QPushButton:
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.setProperty("primary", primary)
    result.setMinimumHeight(38)
    return result


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _service_display_message(name: str, available: bool, message: str) -> str:
    if available:
        return message
    return {
        "api": "本地任务服务异常，请重新启动应用",
        "ollama": "本地模型服务未启动，可点击下方按钮启动",
        "weknora": "知识库服务未连接，请检查地址与服务状态",
    }.get(name, "服务暂不可用，请检查配置后重试")


def _nav_icon(name: str, color: str) -> QIcon:
    """Return a small code-owned line icon without adding another asset runtime."""

    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "home":
        path = QPainterPath(QPointF(3.5, 10.2))
        path.lineTo(11, 4)
        path.lineTo(18.5, 10.2)
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(5.5, 9.5, 11, 9), 1.5, 1.5)
        painter.drawLine(QPointF(10, 18.5), QPointF(10, 13.5))
    elif name == "spark":
        path = QPainterPath(QPointF(11, 2.8))
        path.lineTo(13.1, 8.9)
        path.lineTo(19.2, 11)
        path.lineTo(13.1, 13.1)
        path.lineTo(11, 19.2)
        path.lineTo(8.9, 13.1)
        path.lineTo(2.8, 11)
        path.lineTo(8.9, 8.9)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "tasks":
        for y in (5.0, 11.0, 17.0):
            painter.drawRoundedRect(QRectF(3, y - 1.4, 2.8, 2.8), 0.7, 0.7)
            painter.drawLine(QPointF(8, y), QPointF(19, y))
    elif name == "documents":
        painter.drawRoundedRect(QRectF(5, 3, 12, 16), 1.8, 1.8)
        painter.drawLine(QPointF(8, 8), QPointF(14, 8))
        painter.drawLine(QPointF(8, 12), QPointF(14, 12))
        painter.drawLine(QPointF(8, 16), QPointF(12, 16))
    elif name == "database":
        painter.drawEllipse(QRectF(4, 3, 14, 5))
        painter.drawArc(QRectF(4, 7, 14, 5), 0, -180 * 16)
        painter.drawArc(QRectF(4, 12, 14, 5), 0, -180 * 16)
        painter.drawLine(QPointF(4, 5.5), QPointF(4, 14.5))
        painter.drawLine(QPointF(18, 5.5), QPointF(18, 14.5))
    else:
        painter.drawEllipse(QRectF(6, 6, 10, 10))
        painter.drawEllipse(QRectF(9, 9, 4, 4))
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            painter.drawLine(
                QPointF(11 + math.cos(radians) * 6.2, 11 + math.sin(radians) * 6.2),
                QPointF(11 + math.cos(radians) * 8.3, 11 + math.sin(radians) * 8.3),
            )
    painter.end()
    return QIcon(pixmap)


def _field(label: str, control: QWidget, hint: str | None = None) -> QWidget:
    container = QWidget()
    container.setObjectName("fieldBlock")
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    title = QLabel(label)
    title.setObjectName("fieldLabel")
    layout.addWidget(title)
    layout.addWidget(control)
    if hint:
        detail = QLabel(hint)
        detail.setObjectName("fieldHint")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return container


class _PulseDots(QWidget):
    """A lightweight native busy animation that remains smooth during polling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(42, 18)
        self._phase = 0.0
        self._active = False
        self._color = QColor("#2F7D63")
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)

    def set_active(self, active: bool, *, color: str = "#2F7D63") -> None:
        self._active = active
        self._color = QColor(color)
        if active:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.32) % (math.pi * 2)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, x in enumerate((8.0, 21.0, 34.0)):
            wave = (math.sin(self._phase - index * 0.72) + 1.0) / 2.0
            radius = 2.5 + (1.4 * wave if self._active else 0.0)
            color = QColor(self._color)
            color.setAlpha(105 + int(150 * wave) if self._active else 125)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, 9), radius, radius)
        painter.end()


class _BusyStatusBar(QFrame):
    """Global operation feedback with a wait timer and a reassuring heartbeat."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("footerBar")
        self.setProperty("state", "idle")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(8)
        self.pulse = _PulseDots()
        self.message = QLabel("就绪")
        self.message.setObjectName("footerMessage")
        self.elapsed = QLabel("")
        self.elapsed.setObjectName("footerElapsed")
        layout.addWidget(self.pulse)
        layout.addWidget(self.message, 1)
        layout.addWidget(self.elapsed)
        self._started_at: float | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def begin(self, text: str) -> None:
        self._started_at = time.monotonic()
        self.message.setText(text)
        self.elapsed.setText("刚刚开始")
        self.setProperty("state", "busy")
        _repolish(self)
        self.pulse.set_active(True)
        self._timer.start()

    def finish(self, text: str, *, state: str = "idle") -> None:
        self._timer.stop()
        self._started_at = None
        self.message.setText(text)
        self.elapsed.setText("")
        self.setProperty("state", state)
        _repolish(self)
        color = "#B42318" if state == "error" else "#2F7D63"
        self.pulse.set_active(False, color=color)

    def setText(self, text: str) -> None:  # noqa: N802 - compatibility with QLabel callers
        self.finish(text)

    def text(self) -> str:
        return self.message.text()

    def _tick(self) -> None:
        if self._started_at is None:
            return
        elapsed = max(0, int(time.monotonic() - self._started_at))
        if elapsed < 60:
            self.elapsed.setText(f"已等待 {elapsed} 秒")
        else:
            minutes, seconds = divmod(elapsed, 60)
            self.elapsed.setText(f"已等待 {minutes}:{seconds:02d} · 程序仍在工作")


class _CollapsibleSection(QFrame):
    """Animated progressive disclosure for uncommon model parameters."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("collapsibleSection")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.toggle = QPushButton(f"›  {title}")
        self.toggle.setObjectName("collapseToggle")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.toggled.connect(self._toggle)
        outer.addWidget(self.toggle)
        self.content = QWidget()
        self.content.setObjectName("collapseContent")
        self.content_layout = QGridLayout(self.content)
        self.content_layout.setContentsMargins(16, 14, 16, 16)
        self.content_layout.setHorizontalSpacing(16)
        self.content_layout.setVerticalSpacing(14)
        self.content.setMaximumHeight(0)
        self.content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        outer.addWidget(self.content)
        self.animation = QPropertyAnimation(self.content, b"maximumHeight", self)
        self.animation.setDuration(240)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _toggle(self, expanded: bool) -> None:
        self.toggle.setText(("⌄" if expanded else "›") + self.toggle.text()[1:])
        self.animation.stop()
        self.animation.setStartValue(self.content.maximumHeight())
        target = self.content.sizeHint().height() if expanded else 0
        self.animation.setEndValue(target)
        self.animation.start()


class _StageTracker(QWidget):
    STAGES = ("准备", "采集", "媒体处理", "知识蒸馏", "生成报告", "完成")
    STAGE_INDEX = {
        "pending": 0,
        "starting": 0,
        "preflight": 0,
        "ready": 0,
        "resuming": 0,
        "collect": 1,
        "collection_complete": 1,
        "media": 2,
        "media_reparse": 2,
        "media_complete": 2,
        "video_knowledge": 3,
        "video_knowledge_complete": 3,
        "distill": 3,
        "report": 4,
        "report_complete": 4,
        "knowledge_synthesis": 4,
        "knowledge_export": 4,
        "knowledge_export_complete": 4,
        "narrative": 4,
        "narrative_complete": 4,
        "media_cleanup": 5,
        "media_cleanup_complete": 5,
        "completed": 5,
        "failed": 5,
        "cancelled": 5,
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.items: list[tuple[QLabel, QLabel]] = []
        self.lines: list[QFrame] = []
        for index, label in enumerate(self.STAGES):
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(5)
            dot = QLabel(str(index + 1))
            dot.setObjectName("stageDot")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFixedSize(24, 24)
            text = QLabel(label)
            text.setObjectName("stageLabel")
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.items.append((dot, text))
            item_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
            item_layout.addWidget(text)
            layout.addWidget(item)
            if index < len(self.STAGES) - 1:
                line = QFrame()
                line.setObjectName("stageLine")
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                self.lines.append(line)
                layout.addWidget(line, 1, Qt.AlignmentFlag.AlignTop)
                layout.setAlignment(line, Qt.AlignmentFlag.AlignVCenter)
        self.update_stage("pending", "queued")

    def update_stage(self, stage: str, status: str) -> None:
        current = self.STAGE_INDEX.get(stage, 0)
        failed = status in {"failed", "cancelled"}
        completed = status == "completed"
        for index, (dot, label) in enumerate(self.items):
            if index < current or completed:
                state = "complete"
                dot.setText("✓")
            elif index == current:
                state = "error" if failed else "active"
                dot.setText("!" if failed else str(index + 1))
            else:
                state = "pending"
                dot.setText(str(index + 1))
            for widget in (dot, label):
                widget.setProperty("stageState", state)
                _repolish(widget)
        for index, line in enumerate(self.lines):
            line.setProperty(
                "stageState", "complete" if index < current or completed else "pending"
            )
            _repolish(line)


class _TaskProgressPanel(QFrame):
    STATUS_TEXT = {
        "queued": "排队中",
        "pending": "等待执行",
        "running": "正在运行",
        "completed": "已完成",
        "failed": "执行失败",
        "cancel_requested": "正在取消",
        "cancelled": "已取消",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskProgressPanel")
        self._task: dict[str, Any] | None = None
        self._observed_at = time.monotonic()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.pulse = _PulseDots()
        self.title = QLabel("等待任务")
        self.title.setObjectName("taskProgressTitle")
        self.status = QLabel("暂无运行任务")
        self.status.setObjectName("statusPill")
        top.addWidget(self.pulse)
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.status)
        layout.addLayout(top)
        self.message = QLabel("提交蒸馏任务后，这里会持续显示当前步骤和等待时间。")
        self.message.setObjectName("taskProgressMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setObjectName("taskProgressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.stages = _StageTracker()
        layout.addWidget(self.stages)
        bottom = QHBoxLayout()
        self.detail = QLabel("系统会每 2.5 秒刷新一次，窗口可以继续使用。")
        self.detail.setObjectName("taskProgressDetail")
        self.elapsed = QLabel("")
        self.elapsed.setObjectName("taskProgressElapsed")
        bottom.addWidget(self.detail, 1)
        bottom.addWidget(self.elapsed)
        layout.addLayout(bottom)
        self._animation = QPropertyAnimation(self.progress, b"value", self)
        self._animation.setDuration(420)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_elapsed)
        self._timer.start()

    def set_task(self, task: dict[str, Any] | None) -> None:
        if task is None:
            self._task = None
            self.title.setText("等待任务")
            self.message.setText("提交蒸馏任务后，这里会持续显示当前步骤和等待时间。")
            self._set_status("idle", "暂无运行任务")
            self.pulse.set_active(False)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.stages.update_stage("pending", "queued")
            self.elapsed.setText("")
            return

        task_id = str(task.get("task_id") or "")
        previous_id = str((self._task or {}).get("task_id") or "")
        if task_id != previous_id:
            self._observed_at = time.monotonic()
        self._task = task
        status = str(task.get("status") or "pending")
        stage = str(task.get("stage") or "pending")
        active = status in {"queued", "pending", "running", "cancel_requested"}
        title = "正在执行账号蒸馏" if active else "最近一次账号蒸馏"
        self.title.setText(title)
        self.message.setText(str(task.get("message") or "正在准备任务，请稍候…"))
        self._set_status(status, self.STATUS_TEXT.get(status, status))
        self.pulse.set_active(
            active, color="#2F7D63" if status != "cancel_requested" else "#B7791F"
        )
        value = max(0, min(100, round(float(task.get("progress") or 0.0) * 100)))
        self.progress.setRange(0, 100)
        self._animation.stop()
        self._animation.setStartValue(self.progress.value())
        self._animation.setEndValue(value)
        self._animation.start()
        self.stages.update_stage(stage, status)
        self.detail.setText(f"阶段：{stage or '准备'}  ·  任务 {task_id[:8] or '-'}")
        self._update_elapsed()

    def _set_status(self, state: str, text: str) -> None:
        self.status.setText(text)
        self.status.setProperty("statusState", state)
        _repolish(self.status)

    def _update_elapsed(self) -> None:
        if self._task is None:
            return
        status = str(self._task.get("status") or "")
        created_at = str(self._task.get("created_at") or "")
        elapsed: int | None = None
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
            elapsed = max(0, int((now - created).total_seconds()))
        except (TypeError, ValueError):
            elapsed = max(0, int(time.monotonic() - self._observed_at))
        minutes, seconds = divmod(elapsed, 60)
        prefix = "已用时" if status in {"completed", "failed", "cancelled"} else "运行中"
        self.elapsed.setText(f"{prefix} {minutes:02d}:{seconds:02d}")


def _title(text: str, subtitle: str) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 12)
    heading = QLabel(text)
    heading.setObjectName("pageTitle")
    detail = QLabel(subtitle)
    detail.setObjectName("pageSubtitle")
    detail.setWordWrap(True)
    layout.addWidget(heading)
    layout.addWidget(detail)
    return container


class DistillerMainWindow(QMainWindow):
    def __init__(
        self,
        *,
        supervisor: LocalServiceSupervisor,
        client: DesktopApiClient,
        settings_store: DesktopSettingsStore,
        secret_store: DesktopSecretStore,
        settings: DesktopSettings,
    ) -> None:
        super().__init__()
        self.supervisor = supervisor
        self.client = client
        self.settings_store = settings_store
        self.secret_store = secret_store
        self.settings = settings
        self.pool = QThreadPool.globalInstance()
        self._tasks_busy = False
        self._service_busy = False
        self._bundle_rows: list[dict[str, str]] = []
        self._last_tasks: list[dict[str, Any]] = []
        self._page_animation: QPropertyAnimation | None = None

        self.setWindowTitle("Video Account Distiller")
        self.resize(1420, 900)
        self.setMinimumSize(QSize(1120, 720))
        self._build_ui()
        self._apply_theme()
        self._load_settings()

        self.task_timer = QTimer(self)
        self.task_timer.setInterval(2500)
        self.task_timer.timeout.connect(self.refresh_tasks)
        self.task_timer.start()
        QTimer.singleShot(100, self.refresh_services)
        QTimer.singleShot(250, self.refresh_tasks)
        QTimer.singleShot(400, self.refresh_bundles)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 20, 16, 16)
        side.setSpacing(6)
        brand_row = QHBoxLayout()
        brand_mark = QLabel("V")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(38, 38)
        brand_text = QWidget()
        brand_text_layout = QVBoxLayout(brand_text)
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(1)
        brand_name = QLabel("账号蒸馏台")
        brand_name.setObjectName("brandName")
        strapline = QLabel("VIDEO DISTILLER")
        strapline.setObjectName("brandStrapline")
        brand_text_layout.addWidget(brand_name)
        brand_text_layout.addWidget(strapline)
        brand_row.addWidget(brand_mark)
        brand_row.addWidget(brand_text, 1)
        side.addLayout(brand_row)
        side.addSpacing(20)
        section_label = QLabel("工作区")
        section_label.setObjectName("navSectionLabel")
        side.addWidget(section_label)

        self.stack = QStackedWidget()
        pages = [
            ("home", "总览", self._overview_page()),
            ("spark", "账号蒸馏", self._distill_page()),
            ("tasks", "任务中心", self._tasks_page()),
            ("documents", "知识结果", self._results_page()),
            ("database", "WeKnora", self._weknora_page()),
            ("settings", "设置", self._settings_page()),
        ]
        self.nav_buttons: list[QPushButton] = []
        for index, (icon_name, label, page) in enumerate(pages):
            nav = QPushButton(label)
            nav.setObjectName("navButton")
            nav.setIcon(_nav_icon(icon_name, "#91A4B3"))
            nav.setIconSize(QSize(20, 20))
            nav.setCheckable(True)
            nav.setAutoExclusive(True)
            nav.clicked.connect(lambda _checked=False, value=index: self._show_page(value))
            nav.toggled.connect(
                lambda checked, button=nav, key=icon_name: button.setIcon(
                    _nav_icon(key, "#E9FFF7" if checked else "#91A4B3")
                )
            )
            self.nav_buttons.append(nav)
            side.addWidget(nav)
            self.stack.addWidget(page)
        self.nav_buttons[0].setChecked(True)
        side.addStretch(1)
        self.sidebar_status = QLabel("● 正在检查服务")
        self.sidebar_status.setObjectName("sidebarStatus")
        self.sidebar_status.setWordWrap(True)
        side.addWidget(self.sidebar_status)
        outer.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("contentShell")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 16, 24, 14)
        content_layout.setSpacing(12)
        project_bar = QFrame()
        project_bar.setObjectName("projectBar")
        project_layout = QHBoxLayout(project_bar)
        project_layout.setContentsMargins(14, 9, 12, 9)
        project_layout.setSpacing(8)
        project_label = QLabel("项目")
        project_label.setObjectName("projectLabel")
        project_layout.addWidget(project_label)
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("选择或初始化一个本地蒸馏项目目录")
        project_layout.addWidget(self.project_edit, 1)
        browse = _button("选择目录")
        browse.clicked.connect(self.choose_project)
        initialize = _button("初始化项目", primary=True)
        initialize.clicked.connect(self.initialize_project)
        project_layout.addWidget(browse)
        project_layout.addWidget(initialize)
        service_divider = QFrame()
        service_divider.setObjectName("toolbarDivider")
        service_divider.setFixedSize(1, 24)
        project_layout.addWidget(service_divider)
        self.header_service_labels: dict[str, QLabel] = {}
        for service_name, label in (
            ("api", "API"),
            ("ollama", "Ollama"),
            ("weknora", "WeKnora"),
        ):
            pill = QLabel(f"● {label}")
            pill.setObjectName("servicePill")
            pill.setProperty("statusState", "unknown")
            self.header_service_labels[service_name] = pill
            project_layout.addWidget(pill)
        content_layout.addWidget(project_bar)
        content_layout.addWidget(self.stack, 1)
        self.footer = _BusyStatusBar()
        content_layout.addWidget(self.footer)
        outer.addWidget(content, 1)

    def _overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _title(
                "本地蒸馏工作台",
                "原生桌面应用会自动管理任务 API；采集、转写、蒸馏和同步继续使用同一套经过测试的业务层。",
            )
        )
        cards = QGridLayout()
        self.service_labels: dict[str, tuple[QLabel, QLabel]] = {}
        for index, service in enumerate(("蒸馏 API", "Ollama", "WeKnora")):
            card = QFrame()
            card.setObjectName("metricCard")
            box = QVBoxLayout(card)
            label = QLabel(service)
            label.setObjectName("cardLabel")
            state = QLabel("检查中")
            state.setObjectName("cardValue")
            detail = QLabel("-")
            detail.setObjectName("cardDetail")
            detail.setWordWrap(True)
            box.addWidget(label)
            box.addWidget(state)
            box.addWidget(detail)
            self.service_labels[service] = (state, detail)
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)
        actions = QHBoxLayout()
        refresh = _button("刷新服务状态")
        refresh.clicked.connect(self.refresh_services)
        start_ollama = _button("启动 Ollama")
        start_ollama.clicked.connect(self.start_ollama)
        start_distill = _button("开始账号蒸馏", primary=True)
        start_distill.clicked.connect(lambda: self._show_page(1))
        actions.addWidget(refresh)
        actions.addWidget(start_ollama)
        actions.addStretch(1)
        actions.addWidget(start_distill)
        layout.addLayout(actions)
        queue = QGroupBox("任务队列")
        qlayout = QHBoxLayout(queue)
        self.queue_summary = QLabel("等待服务连接")
        self.queue_summary.setObjectName("largeSummary")
        self.queue_detail = QLabel("持久化任务可在应用重启后恢复")
        self.queue_detail.setObjectName("muted")
        qlayout.addWidget(self.queue_summary)
        qlayout.addStretch(1)
        qlayout.addWidget(self.queue_detail)
        layout.addWidget(queue)
        note = QLabel(
            "提示：MediaCrawler 会在采集任务需要时打开允许的浏览器登录流程；桌面应用不会绕过登录、验证码或平台限制。"
        )
        note.setObjectName("callout")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _distill_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("scrollBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 8, 4)
        layout.setSpacing(14)
        layout.addWidget(
            _title(
                "账号采集与蒸馏",
                "按步骤配置账号来源、蒸馏目标与模型能力；提交后可实时查看每个处理阶段。",
            )
        )

        source = QFrame()
        source.setObjectName("formSection")
        source_layout = QVBoxLayout(source)
        source_layout.setContentsMargins(18, 16, 18, 18)
        source_layout.setSpacing(14)
        source_header = QLabel("1   账号与采集")
        source_header.setObjectName("sectionTitle")
        source_caption = QLabel("选择内容来源和本次处理范围")
        source_caption.setObjectName("sectionCaption")
        source_layout.addWidget(source_header)
        source_layout.addWidget(source_caption)
        source_grid = QGridLayout()
        source_grid.setHorizontalSpacing(16)
        source_grid.setVerticalSpacing(14)
        self.account_url = QLineEdit()
        self.account_url.setPlaceholderText("粘贴抖音账号主页链接")
        self.collection_provider = QComboBox()
        self.collection_provider.addItem("MediaCrawler（本机浏览器）", "mediacrawler")
        self.collection_provider.addItem("TikHub（付费 API）", "tikhub")
        self.collection_count = QSpinBox()
        self.collection_count.setRange(1, 20_000)
        self.collection_count.setValue(20)
        self.all_videos = QCheckBox("采集主页全部可用视频")
        self.all_videos.toggled.connect(
            lambda checked: self.collection_count.setEnabled(not checked)
        )
        self.media_limit = QSpinBox()
        self.media_limit.setRange(0, 20_000)
        self.media_limit.setValue(20)
        source_grid.addWidget(
            _field("账号主页", self.account_url, "支持粘贴完整主页链接，提交前会先验证格式。"),
            0,
            0,
            1,
            2,
        )
        source_grid.addWidget(_field("采集方式", self.collection_provider), 1, 0)
        source_grid.addWidget(_field("主页视频数量", self.collection_count), 1, 1)
        all_row = QWidget()
        all_layout = QHBoxLayout(all_row)
        all_layout.setContentsMargins(0, 0, 0, 0)
        all_layout.addWidget(self.all_videos)
        all_layout.addStretch(1)
        source_grid.addWidget(all_row, 2, 0, 1, 2)
        source_layout.addLayout(source_grid)
        layout.addWidget(source)

        objective = QFrame()
        objective.setObjectName("formSection")
        objective_layout = QVBoxLayout(objective)
        objective_layout.setContentsMargins(18, 16, 18, 18)
        objective_layout.setSpacing(14)
        objective_header = QLabel("2   蒸馏目标")
        objective_header.setObjectName("sectionTitle")
        objective_caption = QLabel("决定输出是逐视频知识文档，还是账号运营方法论")
        objective_caption.setObjectName("sectionCaption")
        objective_layout.addWidget(objective_header)
        objective_layout.addWidget(objective_caption)
        objective_grid = QGridLayout()
        objective_grid.setHorizontalSpacing(16)
        objective_grid.setVerticalSpacing(14)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("纯知识蒸馏 · 一视频一文档", "knowledge")
        self.mode_combo.addItem("运营蒸馏 · 选题 / 表达 / 增长", "creative_learning")
        self.mode_combo.currentIndexChanged.connect(self._update_mode_help)
        self.focus_combo = QComboBox()
        self.focus_combo.addItem("通用分析", "general")
        self.focus_combo.addItem("酒旅迁移分析", "hospitality")
        objective_grid.addWidget(_field("蒸馏模式", self.mode_combo), 0, 0)
        objective_grid.addWidget(_field("分析方向", self.focus_combo), 0, 1)
        objective_layout.addLayout(objective_grid)
        self.mode_help = QLabel()
        self.mode_help.setObjectName("callout")
        self.mode_help.setWordWrap(True)
        objective_layout.addWidget(self.mode_help)
        layout.addWidget(objective)

        models = QFrame()
        models.setObjectName("formSection")
        models_layout = QVBoxLayout(models)
        models_layout.setContentsMargins(18, 16, 18, 18)
        models_layout.setSpacing(14)
        models_header = QLabel("3   模型能力")
        models_header.setObjectName("sectionTitle")
        models_caption = QLabel(
            "支持本地关键帧，也支持 Qwen 3.7 Plus 原视频理解；云端密钥只从 Windows 凭据管理器读取"
        )
        models_caption.setObjectName("sectionCaption")
        models_layout.addWidget(models_header)
        models_layout.addWidget(models_caption)
        model_grid = QGridLayout()
        model_grid.setHorizontalSpacing(16)
        model_grid.setVerticalSpacing(14)

        self.whisper_backend = QComboBox()
        self.whisper_backend.addItem("自动选择", "auto")
        self.whisper_backend.addItem("faster-whisper", "faster-whisper")
        self.whisper_backend.addItem("OpenAI Whisper CLI", "openai-whisper")
        self.whisper_model = QLineEdit("base")
        self.vision_provider = QComboBox()
        self.vision_provider.addItem("Ollama", "ollama")
        self.vision_provider.addItem("llama.cpp", "llamacpp")
        self.vision_provider.addItem("云端兼容 API", "cloud")
        self.vision_provider.addItem("不使用视觉", "none")
        self.vision_model = QLineEdit("qwen3-vl-8b")
        self.knowledge_provider = QComboBox()
        self.knowledge_provider.addItem("Ollama", "ollama")
        self.knowledge_provider.addItem("llama.cpp", "llamacpp")
        self.knowledge_provider.addItem("云端兼容 API", "cloud")
        self.knowledge_provider.addItem("规则降级（无模型）", "none")
        self.knowledge_model = QLineEdit("qwen3:8b")
        model_grid.addWidget(_field("知识模型服务", self.knowledge_provider), 0, 0)
        model_grid.addWidget(_field("知识模型", self.knowledge_model), 0, 1)
        model_grid.addWidget(_field("视觉理解服务", self.vision_provider), 1, 0)
        model_grid.addWidget(_field("视觉模型", self.vision_model), 1, 1)
        models_layout.addLayout(model_grid)
        advanced = _CollapsibleSection("高级处理参数")
        advanced.content_layout.addWidget(
            _field("转写引擎", self.whisper_backend, "自动模式会优先选择当前可用的本地转写后端。"),
            0,
            0,
        )
        advanced.content_layout.addWidget(_field("转写模型", self.whisper_model), 0, 1)
        advanced.content_layout.addWidget(
            _field(
                "下载 / 转写上限", self.media_limit, "0 表示不限制，但长账号会显著增加等待时间。"
            ),
            1,
            0,
            1,
            2,
        )
        models_layout.addWidget(advanced)
        layout.addWidget(models)
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        action_bar = QFrame()
        action_bar.setObjectName("actionBar")
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(16, 10, 12, 10)
        action_hint = QLabel("提交后可继续浏览其他页面；任务会在后台持续运行并保留检查点。")
        action_hint.setObjectName("actionHint")
        actions.addWidget(action_hint, 1)
        preflight = _button("仅做预检")
        preflight.clicked.connect(lambda: self.submit_workflow(dry_run=True))
        self.submit_button = _button("开始完整蒸馏", primary=True)
        self.submit_button.setIcon(_nav_icon("spark", "#FFFFFF"))
        self.submit_button.clicked.connect(lambda: self.submit_workflow(dry_run=False))
        actions.addWidget(preflight)
        actions.addWidget(self.submit_button)
        outer.addWidget(action_bar)
        self._update_mode_help()
        return page

    def _tasks_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(
            _title(
                "任务中心",
                "实时观察采集、媒体处理和知识生成进度；离开此页面不会中断任务。",
            )
        )
        self.task_progress_panel = _TaskProgressPanel()
        layout.addWidget(self.task_progress_panel)
        history = QFrame()
        history.setObjectName("panel")
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(16, 14, 16, 16)
        history_layout.setSpacing(10)
        history_title = QLabel("任务记录")
        history_title.setObjectName("sectionTitle")
        history_layout.addWidget(history_title)
        actions = QHBoxLayout()
        refresh = _button("刷新")
        refresh.clicked.connect(self.refresh_tasks)
        details = _button("查看详情")
        details.clicked.connect(self.show_task_details)
        retry = _button("重试失败任务")
        retry.clicked.connect(self.retry_selected_task)
        cancel = _button("取消任务")
        cancel.clicked.connect(self.cancel_selected_task)
        actions.addWidget(refresh)
        actions.addWidget(details)
        actions.addWidget(retry)
        actions.addWidget(cancel)
        actions.addStretch(1)
        history_layout.addLayout(actions)
        self.tasks_table = QTableWidget(0, 7)
        self.tasks_table.setHorizontalHeaderLabels(
            ["状态", "类型", "阶段", "进度", "消息", "更新时间", "任务 ID"]
        )
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tasks_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tasks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tasks_table.doubleClicked.connect(self.show_task_details)
        header = self.tasks_table.horizontalHeader()
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.tasks_table.verticalHeader().setVisible(False)
        self.tasks_table.setAlternatingRowColors(True)
        history_layout.addWidget(self.tasks_table, 3)
        layout.addWidget(history, 3)
        self.task_details = QTextEdit()
        self.task_details.setReadOnly(True)
        self.task_details.setPlaceholderText("选择一个任务查看 checkpoint、错误与输出路径。")
        self.task_details.setMaximumHeight(160)
        layout.addWidget(self.task_details)
        return page

    def _results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _title(
                "一视频一文档知识结果",
                "读取项目内真实 manifest；标题文件名会保留在 ZIP 中，可直接归档或导入其他知识系统。",
            )
        )
        actions = QHBoxLayout()
        self.bundle_account_filter = QLineEdit()
        self.bundle_account_filter.setPlaceholderText("可选：按 account_id 筛选")
        refresh = _button("刷新结果")
        refresh.clicked.connect(self.refresh_bundles)
        open_folder = _button("打开结果目录")
        open_folder.clicked.connect(self.open_selected_bundle)
        export_zip = _button("导出知识包 ZIP", primary=True)
        export_zip.clicked.connect(self.export_selected_bundle)
        actions.addWidget(self.bundle_account_filter, 1)
        actions.addWidget(refresh)
        actions.addWidget(open_folder)
        actions.addWidget(export_zip)
        layout.addLayout(actions)
        self.bundles_table = QTableWidget(0, 7)
        self.bundles_table.setHorizontalHeaderLabels(
            ["生成时间", "账号", "状态", "文档", "降级", "跳过", "Manifest"]
        )
        self.bundles_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bundles_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.bundles_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bundles_table.doubleClicked.connect(self.open_selected_bundle)
        self.bundles_table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.bundles_table, 1)
        return page

    def _weknora_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _title(
                "WeKnora 同步",
                "密钥只保存到 Windows 凭据管理器。系统不会自动创建知识库，也不会把密钥写入项目。",
            )
        )
        connection = QGroupBox("连接")
        form = QFormLayout(connection)
        self.weknora_url = QLineEdit("http://127.0.0.1:8080")
        self.weknora_key = QLineEdit()
        self.weknora_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.weknora_key.setPlaceholderText("留空表示继续使用已安全保存的密钥")
        self.weknora_kb = QComboBox()
        form.addRow("服务地址", self.weknora_url)
        form.addRow("API Key", self.weknora_key)
        form.addRow("目标知识库", self.weknora_kb)
        layout.addWidget(connection)
        connection_actions = QHBoxLayout()
        save_key = _button("安全保存密钥")
        save_key.clicked.connect(self.save_weknora_key)
        list_kb = _button("连接并读取知识库", primary=True)
        list_kb.clicked.connect(self.load_weknora_kbs)
        connection_actions.addWidget(save_key)
        connection_actions.addWidget(list_kb)
        connection_actions.addStretch(1)
        layout.addLayout(connection_actions)
        sync = QGroupBox("同步账号结果")
        sync_form = QFormLayout(sync)
        self.sync_account_id = QLineEdit()
        self.sync_account_id.setPlaceholderText("acc_...")
        self.sync_mode = QComboBox()
        self.sync_mode.addItem("逐视频纯知识文档", "knowledge")
        self.sync_mode.addItem("账号运营知识", "creative_learning")
        sync_form.addRow("账号 ID", self.sync_account_id)
        sync_form.addRow("文档类型", self.sync_mode)
        layout.addWidget(sync)
        sync_button = _button("同步到所选知识库", primary=True)
        sync_button.clicked.connect(self.sync_weknora)
        sync_row = QHBoxLayout()
        sync_row.addStretch(1)
        sync_row.addWidget(sync_button)
        layout.addLayout(sync_row)
        self.weknora_result = QTextEdit()
        self.weknora_result.setReadOnly(True)
        self.weknora_result.setPlaceholderText("连接、替换和上传结果会显示在这里。")
        layout.addWidget(self.weknora_result, 1)
        return page

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _title(
                "模型与密钥设置",
                "端点和模型名属于非秘密设置；API Key 只进入 Windows Credential Manager。",
            )
        )
        models = QGroupBox("模型服务")
        form = QFormLayout(models)
        self.ollama_url = QLineEdit("http://127.0.0.1:11434")
        self.cloud_provider = QComboBox()
        self.cloud_provider.addItem("百炼 / DashScope", "bailian")
        self.cloud_provider.addItem("OpenAI", "openai")
        self.cloud_provider.addItem("DeepSeek", "deepseek")
        self.cloud_url = QLineEdit()
        self.cloud_text_model = QLineEdit()
        self.cloud_vision_model = QLineEdit()
        self.cloud_key = QLineEdit()
        self.cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_key.setPlaceholderText("仅在保存时读取；不会写入设置文件")
        form.addRow("Ollama 地址", self.ollama_url)
        form.addRow("云端凭据类型", self.cloud_provider)
        form.addRow("云端兼容端点", self.cloud_url)
        form.addRow("文本模型", self.cloud_text_model)
        form.addRow("视觉模型", self.cloud_vision_model)
        form.addRow("云模型 API Key", self.cloud_key)
        recommended = _button("应用 Qwen 视频 + DeepSeek 蒸馏组合")
        recommended.clicked.connect(self._apply_qwen_deepseek_preset)
        form.addRow("推荐组合", recommended)
        preset_help = QLabel(
            "Qwen 3.7 Plus 读取原视频并保留混合关键帧证据；DeepSeek V4 Flash 负责知识提取与深度推理。"
        )
        preset_help.setObjectName("muted")
        preset_help.setWordWrap(True)
        form.addRow("", preset_help)
        layout.addWidget(models)
        crawler = QGroupBox("采集凭据")
        crawler_form = QFormLayout(crawler)
        self.tikhub_key = QLineEdit()
        self.tikhub_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.tikhub_key.setPlaceholderText("可选；MediaCrawler 不需要 TikHub Key")
        crawler_form.addRow("TikHub API Key", self.tikhub_key)
        layout.addWidget(crawler)
        buttons = QHBoxLayout()
        save_cloud = _button("验证并保存云模型密钥")
        save_cloud.clicked.connect(self.save_cloud_key)
        save = _button("保存设置", primary=True)
        save.clicked.connect(self.save_settings)
        buttons.addWidget(save_cloud)
        buttons.addStretch(1)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self.settings_path = QLabel(str(self.settings_store.path))
        self.settings_path.setObjectName("muted")
        self.settings_path.setWordWrap(True)
        layout.addWidget(self.settings_path)
        layout.addStretch(1)
        return page

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, #appRoot, #contentShell { background: #F3F5F7; color: #16212A; }
            QLabel { background: transparent; }
            QStackedWidget, QStackedWidget > QWidget, #scrollBody { background: transparent; }
            #sidebar { background: #111D27; border: 0; }
            #brandMark { color: #F4FFFA; background: #2F7D63; border-radius: 11px;
                         font-size: 17px; font-weight: 800; }
            #brandName { color: #F4F7F9; font-size: 17px; font-weight: 700; }
            #brandStrapline { color: #6F8796; font-size: 9px; font-weight: 700; letter-spacing: 1px; }
            #navSectionLabel { color: #617786; font-size: 10px; font-weight: 700;
                               padding: 0 8px 5px 8px; letter-spacing: 1px; }
            #sidebarStatus { color: #8EA1AE; background: #172732; border: 1px solid #223743;
                             border-radius: 9px; padding: 10px; font-size: 11px; }
            #navButton { min-height: 40px; text-align: left; color: #AFC0CA; background: transparent;
                         border: 0; padding: 0 12px; border-radius: 9px; font-weight: 600; }
            #navButton:hover { background: #192B36; color: #F5F8FA; }
            #navButton:checked { background: #214C40; color: #E9FFF7; }

            #projectBar, #panel, QGroupBox, #metricCard, #formSection, #taskProgressPanel,
            #actionBar { background: #FFFFFF; border: 1px solid #DDE3E7; border-radius: 11px; }
            #projectBar { min-height: 48px; }
            #projectLabel { color: #5B6973; font-size: 11px; font-weight: 700;
                            background: #F1F4F5; border-radius: 6px; padding: 6px 8px; }
            #toolbarDivider { background: #E1E6E9; border: 0; }
            #servicePill { color: #6C7A84; background: #F5F7F8; border: 1px solid #E2E7EA;
                           border-radius: 11px; padding: 4px 8px; font-size: 10px; }
            #servicePill[statusState="available"] { color: #236B53; background: #ECF8F2; border-color: #CBE9DA; }
            #servicePill[statusState="unavailable"] { color: #9A3412; background: #FFF5EE; border-color: #FED7C3; }

            #pageTitle { font-size: 25px; font-weight: 700; color: #14232D; }
            #pageSubtitle, #muted, #cardDetail, #sectionCaption, #fieldHint { color: #6B7882; }
            #pageSubtitle { font-size: 12px; }
            #sectionTitle { color: #1A2A34; font-size: 15px; font-weight: 700; }
            #sectionCaption { font-size: 11px; }
            #fieldLabel { color: #3E4C56; font-size: 11px; font-weight: 650; }
            #fieldHint { font-size: 10px; }
            #cardLabel { color: #667784; font-weight: 650; }
            #cardValue { font-size: 22px; font-weight: 750; color: #205744; }
            #largeSummary { font-size: 20px; font-weight: 700; }
            #callout { background: #EDF8F3; border: 1px solid #C9E8DA; border-radius: 8px;
                       padding: 11px; color: #245C4A; font-size: 11px; }
            #actionHint { color: #687781; font-size: 11px; }
            #pageScroll { background: transparent; border: 0; }
            #pageScroll > QWidget > QWidget { background: transparent; }
            #actionBar { background: #FAFBFB; }

            #collapsibleSection { background: #F7F9FA; border: 1px solid #E3E8EB; border-radius: 8px; }
            #collapseToggle { text-align: left; color: #40515C; background: transparent; border: 0;
                              padding: 10px 13px; font-weight: 650; }
            #collapseToggle:hover { color: #236B53; background: #F0F5F3; }
            #collapseContent { background: #FBFCFC; border-top: 1px solid #E7EBED; }

            #footerBar { background: #FAFBFB; border: 1px solid #E1E6E9; border-radius: 9px; }
            #footerBar[state="busy"] { background: #F0F8F4; border-color: #C9E6D8; }
            #footerBar[state="error"] { background: #FFF3F1; border-color: #F3C9C3; }
            #footerMessage { color: #52616B; font-size: 11px; }
            #footerElapsed { color: #7A8992; font-size: 10px; }

            #taskProgressPanel { background: #FCFDFD; }
            #taskProgressTitle { color: #183027; font-size: 16px; font-weight: 700; }
            #taskProgressMessage { color: #354650; font-size: 12px; }
            #taskProgressDetail, #taskProgressElapsed { color: #73818A; font-size: 10px; }
            #statusPill { color: #52616A; background: #EEF1F3; border-radius: 10px;
                          padding: 4px 9px; font-size: 10px; font-weight: 700; }
            #statusPill[statusState="running"], #statusPill[statusState="queued"],
            #statusPill[statusState="pending"] { color: #236B53; background: #E7F5EE; }
            #statusPill[statusState="completed"] { color: #17633F; background: #DCF5E8; }
            #statusPill[statusState="failed"] { color: #B42318; background: #FDEAE7; }
            #statusPill[statusState="cancel_requested"] { color: #9A6700; background: #FFF4D6; }
            #statusPill[statusState="cancelled"] { color: #6B7280; background: #ECEFF1; }
            #taskProgressBar { min-height: 7px; max-height: 7px; background: #E5EBE8;
                               border: 0; border-radius: 3px; }
            #taskProgressBar::chunk { background: #2F7D63; border-radius: 3px; }
            #stageDot { color: #7B8991; background: #EEF1F2; border: 1px solid #DCE2E5;
                        border-radius: 12px; font-size: 9px; font-weight: 700; }
            #stageDot[stageState="active"] { color: white; background: #2F7D63; border-color: #2F7D63; }
            #stageDot[stageState="complete"] { color: white; background: #5F9B82; border-color: #5F9B82; }
            #stageDot[stageState="error"] { color: white; background: #C24135; border-color: #C24135; }
            #stageLabel { color: #839098; font-size: 9px; }
            #stageLabel[stageState="active"] { color: #245C4A; font-weight: 700; }
            #stageLabel[stageState="complete"] { color: #4F6B60; }
            #stageLabel[stageState="error"] { color: #B42318; font-weight: 700; }
            #stageLine { background: #E2E7E5; border: 0; }
            #stageLine[stageState="complete"] { background: #8BB9A5; }

            QGroupBox { margin-top: 12px; padding: 20px 15px 14px 15px; font-weight: 700; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #263842; }
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget {
                background: #FFFFFF; border: 1px solid #CDD6DB; border-radius: 7px; padding: 7px 9px;
                selection-background-color: #2F7D63; min-height: 20px;
            }
            QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #9AAAB3; }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {
                border: 1px solid #2F7D63; background: #FEFFFF;
            }
            QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {
                color: #8D989F; background: #F2F4F5; border-color: #E0E5E8;
            }
            QComboBox::drop-down { border: 0; width: 28px; }
            QSpinBox::up-button, QSpinBox::down-button { width: 22px; background: #F5F7F8; border: 0; }
            QCheckBox { color: #44545E; spacing: 8px; }
            QPushButton { background: #FFFFFF; border: 1px solid #BAC6CC; border-radius: 7px;
                          padding: 7px 14px; font-weight: 650; color: #2B3C46; }
            QPushButton:hover { border-color: #2F7D63; color: #245C4A; background: #F6FAF8; }
            QPushButton:pressed { background: #EAF3EF; }
            QPushButton[primary="true"] { background: #236B53; border-color: #236B53; color: white; }
            QPushButton[primary="true"]:hover { background: #195440; border-color: #195440; }
            QPushButton[primary="true"]:pressed { background: #123F30; }
            QHeaderView::section { background: #F2F5F6; color: #53636D; border: 0;
                                   border-bottom: 1px solid #D8E0E4; padding: 9px; font-weight: 700; }
            QTableWidget { gridline-color: #E7EBED; alternate-background-color: #FAFBFB; }
            QTableWidget::item { padding: 5px; border-bottom: 1px solid #EFF2F3; }
            QTableWidget::item:selected { background: #DDEFE7; color: #173C2F; }
            QScrollBar:vertical { width: 9px; background: transparent; margin: 2px; }
            QScrollBar::handle:vertical { background: #C6D0D5; min-height: 32px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #9DACB4; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        target = self.stack.currentWidget()
        assert target is not None
        effect = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", target)
        animation.setDuration(180)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda widget=target: widget.setGraphicsEffect(None))
        self._page_animation = animation
        animation.start()
        if index == 2:
            self.refresh_tasks()
        elif index == 3:
            self.refresh_bundles()
        elif index == 0:
            self.refresh_services()

    def _run(
        self,
        call: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        message: str,
        on_failure: Callable[[Exception], None] | None = None,
        show_busy: bool = True,
    ) -> None:
        if show_busy:
            self.footer.begin(message)
        worker = _Worker(call)

        def success(value: object) -> None:
            if show_busy:
                self.footer.finish("操作完成", state="success")
            on_success(value)

        def failure(value: object) -> None:
            assert isinstance(value, Exception)
            if show_busy:
                self.footer.finish("操作失败", state="error")
            if on_failure is not None:
                on_failure(value)
            else:
                self._show_error(value)

        worker.signals.success.connect(success)
        worker.signals.failure.connect(failure)
        self.pool.start(worker)

    def _show_error(self, exc: Exception) -> None:
        if isinstance(exc, DesktopApiError):
            extra = f"\n\n错误代码：{exc.code}" if exc.code else ""
            if exc.details:
                extra += "\n" + json.dumps(exc.details, ensure_ascii=False, indent=2)
            message = f"{exc}{extra}"
        elif isinstance(exc, DistillerError):
            message = exc.as_dict()["error"]["message"]
        else:
            message = str(exc)
        QMessageBox.critical(self, "操作未完成", message)

    def _project(self, *, require_initialized: bool = True) -> Path:
        raw = self.project_edit.text().strip()
        if not raw:
            raise ValueError("请先选择项目目录。")
        path = Path(raw).expanduser().resolve()
        if require_initialized:
            ProjectLayout.open(path)
        return path

    def choose_project(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "选择蒸馏项目目录", self.project_edit.text()
        )
        if directory:
            self.project_edit.setText(directory)
            self.settings.project_path = directory
            self.save_settings(silent=True)
            self.refresh_bundles()

    def initialize_project(self) -> None:
        try:
            path = self._project(require_initialized=False)
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return

        def done(payload: object) -> None:
            self.footer.setText("项目已就绪")
            self.settings.project_path = str(path)
            self.save_settings(silent=True)
            QMessageBox.information(
                self,
                "项目已就绪",
                "已打开现有项目。"
                if isinstance(payload, dict) and payload.get("already_initialized")
                else "项目初始化完成。",
            )

        self._run(lambda: self.client.initialize_project(path), done, message="正在初始化项目…")

    def _update_mode_help(self) -> None:
        knowledge = self.mode_combo.currentData() == "knowledge"
        self.focus_combo.setEnabled(not knowledge)
        if knowledge:
            self.mode_help.setText(
                "纯知识模式：逐条提取视频中的事实、概念、方法、案例、数据、新闻与观点；不生成运营画像，成功后输出标题命名的一视频一文档知识包。"
            )
        else:
            self.mode_help.setText(
                "运营模式：保留账号定位、受众、内容机制、评论、模式与反例、账号报告和可选酒旅迁移分析。"
            )

    def _workflow_payload(self) -> dict[str, Any]:
        url = self.account_url.text().strip()
        if not url:
            raise ValueError("请填写账号主页链接。")
        mode = str(self.mode_combo.currentData())
        vision = str(self.vision_provider.currentData())
        knowledge_provider = str(self.knowledge_provider.currentData())
        payload: dict[str, Any] = {
            "url": url,
            "profile": "standard",
            "count": None if self.all_videos.isChecked() else self.collection_count.value(),
            "all_videos": self.all_videos.isChecked(),
            "sort": "latest",
            "provider": str(self.collection_provider.currentData()),
            "comments_per_video": 0 if mode == "knowledge" else 10,
            "comment_video_limit": None
            if self.all_videos.isChecked()
            else self.collection_count.value(),
            "confirm_provider_cost": self.collection_provider.currentData() == "tikhub",
            "media_limit": self.media_limit.value(),
            "distillation_mode": mode,
            "analysis_focus": str(self.focus_combo.currentData()),
            "whisper_backend": str(self.whisper_backend.currentData()),
            "whisper_model": self.whisper_model.text().strip() or "base",
            "vision_provider": None if vision == "none" else vision,
            "vision_model": self.vision_model.text().strip() or "qwen3-vl-8b",
            "ollama_base_url": self.ollama_url.text().strip() or "http://127.0.0.1:11434",
            "cloud_credential_provider": str(self.cloud_provider.currentData()),
            "cloud_base_url": self.cloud_url.text().strip() or None,
            "cloud_text_model": self.cloud_text_model.text().strip() or None,
            "cloud_vision_model": self.cloud_vision_model.text().strip() or None,
            "distill_video_knowledge": mode == "knowledge",
            "video_knowledge_provider": knowledge_provider if mode == "knowledge" else None,
            "video_knowledge_model": self.knowledge_model.text().strip() or None,
            "export_knowledge": True,
        }
        if mode == "knowledge" and self.media_limit.value() <= 0:
            raise ValueError("纯知识蒸馏需要把“下载/转写数量”设置为大于 0。")
        return payload

    def submit_workflow(self, *, dry_run: bool) -> None:
        try:
            project = self._project()
            payload = self._workflow_payload()
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return

        def submit() -> dict[str, Any]:
            requires_ollama = "ollama" in {
                payload.get("vision_provider"),
                payload.get("video_knowledge_provider"),
            }
            if requires_ollama:
                self.supervisor.start_ollama(ollama_base_url=str(payload.get("ollama_base_url")))
            return self.client.submit_account_distill(project, payload, dry_run=dry_run)

        def done(result: object) -> None:
            task_id = result.get("task_id") if isinstance(result, dict) else None
            self.submit_button.setEnabled(True)
            self.submit_button.setText("开始完整蒸馏")
            self.footer.setText(f"任务已提交：{task_id or '-'}")
            self.task_progress_panel.set_task(
                {
                    "task_id": task_id,
                    "task_type": "account_distill",
                    "status": "pending",
                    "stage": "pending",
                    "progress": 0.0,
                    "message": "任务已经进入本地队列，正在等待执行…",
                    "created_at": datetime.now().astimezone().isoformat(),
                }
            )
            self._show_page(2)
            self.refresh_tasks()

        def failed(exc: Exception) -> None:
            self.submit_button.setEnabled(True)
            self.submit_button.setText("开始完整蒸馏")
            self._show_error(exc)

        self._capture_settings_from_ui()
        self.settings_store.save(self.settings)
        self.submit_button.setEnabled(False)
        self.submit_button.setText("正在提交…")
        self._run(
            submit,
            done,
            message="正在提交预检…" if dry_run else "正在提交蒸馏任务…",
            on_failure=failed,
        )

    def refresh_tasks(self) -> None:
        if self._tasks_busy or not self.supervisor.api.running:
            return
        self._tasks_busy = True

        def done(value: object) -> None:
            self._tasks_busy = False
            tasks = value if isinstance(value, list) else []
            self._last_tasks = [task for task in tasks if isinstance(task, dict)]
            active_states = {"queued", "pending", "running", "cancel_requested"}
            featured = next(
                (task for task in self._last_tasks if task.get("status") in active_states),
                self._last_tasks[0] if self._last_tasks else None,
            )
            self.task_progress_panel.set_task(featured)
            self.tasks_table.setRowCount(len(tasks))
            for row, task in enumerate(tasks):
                progress = task.get("progress")
                progress_text = (
                    f"{float(progress) * 100:.0f}%" if isinstance(progress, int | float) else "-"
                )
                status = str(task.get("status") or "")
                status_text = _TaskProgressPanel.STATUS_TEXT.get(status, status)
                values = [
                    status_text,
                    task.get("task_type"),
                    task.get("stage"),
                    progress_text,
                    task.get("message"),
                    task.get("updated_at"),
                    task.get("task_id"),
                ]
                for column, text in enumerate(values):
                    item = QTableWidgetItem(str(text or ""))
                    if column == 0:
                        color = {
                            "completed": "#237A57",
                            "failed": "#B42318",
                            "running": "#236B53",
                            "cancelled": "#6B7280",
                        }.get(status)
                        if color:
                            item.setForeground(QColor(color))
                    self.tasks_table.setItem(row, column, item)
            if any(task.get("status") == "completed" for task in tasks[:3]):
                self.refresh_bundles()

        def failed(exc: Exception) -> None:
            self._tasks_busy = False
            self.sidebar_status.setText("● 本地 API 未连接")
            if self.stack.currentIndex() == 2:
                self.footer.finish(str(exc), state="error")

        self._run(
            lambda: self.client.list_tasks(limit=80),
            done,
            message="正在刷新任务…",
            on_failure=failed,
            show_busy=False,
        )

    def _selected_task_id(self) -> str:
        row = self.tasks_table.currentRow()
        if row < 0:
            raise ValueError("请先选择一个任务。")
        item = self.tasks_table.item(row, 6)
        if item is None or not item.text():
            raise ValueError("所选行没有任务 ID。")
        return item.text()

    def show_task_details(self) -> None:
        try:
            task_id = self._selected_task_id()
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return

        def done(result: object) -> None:
            self.task_details.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self.footer.setText(f"已读取任务详情：{task_id}")

        self._run(lambda: self.client.get_task(task_id), done, message="正在读取任务详情…")

    def retry_selected_task(self) -> None:
        try:
            task_id = self._selected_task_id()
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return

        def done(result: object) -> None:
            new_id = result.get("task_id") if isinstance(result, dict) else None
            self.footer.setText(f"重试任务已提交：{new_id or '-'}")
            self.refresh_tasks()

        self._run(lambda: self.client.retry_task(task_id), done, message="正在重试任务…")

    def cancel_selected_task(self) -> None:
        try:
            task_id = self._selected_task_id()
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return
        self._run(
            lambda: self.client.cancel_task(task_id),
            lambda _result: self.refresh_tasks(),
            message="正在请求取消任务…",
        )

    def refresh_services(self) -> None:
        if self._service_busy:
            return
        self._service_busy = True
        ollama_url = (
            self.ollama_url.text().strip()
            if hasattr(self, "ollama_url")
            else self.settings.ollama_base_url
        )
        weknora_url = (
            self.weknora_url.text().strip()
            if hasattr(self, "weknora_url")
            else self.settings.weknora_base_url
        )

        def check() -> tuple[list[Any], dict[str, Any]]:
            return (
                self.supervisor.statuses(
                    ollama_base_url=ollama_url or "http://127.0.0.1:11434",
                    weknora_base_url=weknora_url or "http://127.0.0.1:8080",
                ),
                self.client.task_queue_status(),
            )

        def done(value: object) -> None:
            self._service_busy = False
            statuses, queue = value if isinstance(value, tuple) else ([], {})
            for status in statuses:
                labels = self.service_labels.get(status.name)
                if labels:
                    labels[0].setText("可用" if status.available else "未连接")
                    labels[0].setStyleSheet(
                        "color: #237A57;" if status.available else "color: #B84A4A;"
                    )
                    labels[1].setText(
                        f"{_service_display_message(status.name, status.available, status.message)}"
                        f"\n{status.endpoint}"
                    )
                    labels[1].setToolTip(f"{status.message}\n{status.endpoint}")
                header_label = self.header_service_labels.get(status.name)
                if header_label is not None:
                    display_name = {
                        "api": "API",
                        "ollama": "Ollama",
                        "weknora": "WeKnora",
                    }.get(status.name, status.name)
                    header_label.setText(f"● {display_name}")
                    header_label.setProperty(
                        "statusState", "available" if status.available else "unavailable"
                    )
                    header_label.setToolTip(f"{status.message}\n{status.endpoint}")
                    _repolish(header_label)
            api_ok = bool(statuses and statuses[0].available)
            self.sidebar_status.setText("● 服务运行中" if api_ok else "● 服务异常")
            by_status = queue.get("by_status", {}) if isinstance(queue, dict) else {}
            limits = queue.get("limits", {}) if isinstance(queue, dict) else {}
            queued = by_status.get("pending", 0) if isinstance(by_status, dict) else 0
            running = by_status.get("running", 0) if isinstance(by_status, dict) else 0
            self.queue_summary.setText(f"{running} 个运行中 · {queued} 个等待中")
            self.queue_detail.setText(
                f"并发上限 {limits.get('max_concurrent', '-')} · "
                f"等待上限 {limits.get('max_pending', '-')}"
                if isinstance(limits, dict)
                else ""
            )

        def failed(exc: Exception) -> None:
            self._service_busy = False
            self.sidebar_status.setText("● 服务异常")
            for header_label in self.header_service_labels.values():
                header_label.setProperty("statusState", "unavailable")
                _repolish(header_label)
            if self.stack.currentIndex() == 0:
                self.footer.finish(str(exc), state="error")

        self._run(
            check,
            done,
            message="正在检查服务…",
            on_failure=failed,
            show_busy=False,
        )

    def start_ollama(self) -> None:
        url = self.ollama_url.text().strip() or "http://127.0.0.1:11434"

        def done(value: object) -> None:
            if value:
                self.footer.setText("Ollama 已就绪")
            else:
                QMessageBox.warning(
                    self, "未找到 Ollama", "未检测到 ollama.exe，请先安装或配置其他模型服务。"
                )
            self.refresh_services()

        self._run(
            lambda: self.supervisor.start_ollama(ollama_base_url=url),
            done,
            message="正在启动 Ollama…",
        )

    def _knowledge_service(self) -> KnowledgePackageService:
        return KnowledgePackageService(ProjectLayout.open(self._project()))

    def refresh_bundles(self) -> None:
        try:
            service = self._knowledge_service()
        except Exception:
            self.bundles_table.setRowCount(0)
            return
        account = self.bundle_account_filter.text().strip() or None
        bundles = service.list_bundles(account_id=account)
        self._bundle_rows = [item.model_dump(mode="json") for item in bundles]
        self.bundles_table.setRowCount(len(bundles))
        for row, bundle in enumerate(bundles):
            values = [
                bundle.generated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                bundle.account_id,
                bundle.status,
                bundle.document_count,
                bundle.degraded_count,
                bundle.skipped_count,
                bundle.manifest_id,
            ]
            for column, value in enumerate(values):
                self.bundles_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.footer.setText(f"发现 {len(bundles)} 个知识包")

    def _selected_bundle(self) -> dict[str, str]:
        row = self.bundles_table.currentRow()
        if row < 0 or row >= len(self._bundle_rows):
            raise ValueError("请先选择一个知识结果。")
        return self._bundle_rows[row]

    def open_selected_bundle(self) -> None:
        try:
            bundle = self._selected_bundle()
            QDesktopServices.openUrl(QUrl.fromLocalFile(bundle["output_directory"]))
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)

    def export_selected_bundle(self) -> None:
        try:
            bundle = self._selected_bundle()
            service = self._knowledge_service()
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择知识包导出目录",
            str(self._project() / "exports"),
        )
        if not directory:
            return
        try:
            output = service.export_zip(bundle["manifest_path"], destination_dir=directory)
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return
        self.footer.setText(f"知识包已导出：{output}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output.parent)))

    def save_weknora_key(self) -> None:
        key = self.weknora_key.text().strip()
        if not key:
            self._show_error(ValueError("请输入 WeKnora API Key。"))
            return
        try:
            self.secret_store.set("weknora-api-key", key)
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return
        self.weknora_key.clear()
        self.footer.setText("WeKnora 密钥已保存到 Windows 凭据管理器")

    def _weknora_secret(self) -> str:
        entered = self.weknora_key.text().strip()
        if entered:
            self.secret_store.set("weknora-api-key", entered)
            self.weknora_key.clear()
            return entered
        saved = self.secret_store.get("weknora-api-key")
        if not saved:
            raise ValueError("请先输入并安全保存 WeKnora API Key。")
        return saved

    def load_weknora_kbs(self) -> None:
        try:
            project = self._project()
            key = self._weknora_secret()
            base_url = self.weknora_url.text().strip()
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return

        def done(value: object) -> None:
            values = value if isinstance(value, list) else []
            self.weknora_kb.clear()
            for item in values:
                name = str(item.get("name") or item.get("id") or "未命名知识库")
                self.weknora_kb.addItem(name, str(item.get("id") or ""))
            saved_index = self.weknora_kb.findData(self.settings.weknora_kb_id)
            if saved_index >= 0:
                self.weknora_kb.setCurrentIndex(saved_index)
            self.weknora_result.setPlainText(f"已读取 {len(values)} 个可见知识库。")
            self.footer.setText("WeKnora 连接成功")
            self.refresh_services()

        self._run(
            lambda: self.client.list_weknora_knowledge_bases(
                project, base_url=base_url, api_key=key
            ),
            done,
            message="正在读取 WeKnora 知识库…",
        )

    def sync_weknora(self) -> None:
        try:
            project = self._project()
            key = self._weknora_secret()
            account_id = self.sync_account_id.text().strip()
            kb_id = str(self.weknora_kb.currentData() or "")
            if not account_id or not kb_id:
                raise ValueError("请填写账号 ID 并选择目标知识库。")
            base_url = self.weknora_url.text().strip()
            mode = str(self.sync_mode.currentData())
        except Exception as exc:  # noqa: BLE001
            self._show_error(exc)
            return

        def done(result: object) -> None:
            self.weknora_result.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            self.footer.setText("WeKnora 同步完成")
            self.settings.weknora_kb_id = kb_id
            self.settings.weknora_kb_name = self.weknora_kb.currentText()
            self.save_settings(silent=True)

        self._run(
            lambda: self.client.sync_account_weknora(
                project,
                account_id=account_id,
                base_url=base_url,
                api_key=key,
                kb_id=kb_id,
                distillation_mode=mode,
            ),
            done,
            message="正在同步 WeKnora；请勿关闭应用…",
        )

    def save_cloud_key(self) -> None:
        provider = str(self.cloud_provider.currentData())
        key = self.cloud_key.text().strip()
        if not key:
            self._show_error(ValueError("请输入云模型 API Key。"))
            return

        def done(result: object) -> None:
            self.cloud_key.clear()
            self.footer.setText(f"{provider} 密钥已验证并保存到 Windows 凭据管理器")
            QMessageBox.information(
                self, "密钥已保存", json.dumps(result, ensure_ascii=False, indent=2)
            )

        self._run(
            lambda: self.client.save_cloud_credential(provider, key),
            done,
            message="正在验证云模型密钥…",
        )

    def _apply_qwen_deepseek_preset(self) -> None:
        """Configure the single-key Bailian route for native video plus deep synthesis."""

        self._select_data(self.cloud_provider, "bailian")
        self.cloud_url.setText("https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.cloud_vision_model.setText("qwen3.7-plus")
        self.cloud_text_model.setText("deepseek-v4-flash")
        self._select_data(self.vision_provider, "cloud")
        self.vision_model.setText("qwen3.7-plus")
        self._select_data(self.knowledge_provider, "cloud")
        self.knowledge_model.setText("deepseek-v4-flash")
        self.save_settings(silent=True)
        self.footer.setText("已应用：Qwen 3.7 Plus 原视频理解 + DeepSeek V4 Flash 深度蒸馏")

    def _capture_settings_from_ui(self) -> None:
        self.settings.project_path = self.project_edit.text().strip() or None
        self.settings.account_url = self.account_url.text().strip()
        self.settings.collection_provider = str(self.collection_provider.currentData())
        self.settings.collection_count = self.collection_count.value()
        self.settings.collect_all_videos = self.all_videos.isChecked()
        self.settings.media_limit = self.media_limit.value()
        self.settings.distillation_mode = str(self.mode_combo.currentData())
        self.settings.analysis_focus = str(self.focus_combo.currentData())
        self.settings.whisper_backend = str(self.whisper_backend.currentData())
        self.settings.whisper_model = self.whisper_model.text().strip() or "base"
        self.settings.vision_provider = str(self.vision_provider.currentData())
        self.settings.vision_model = self.vision_model.text().strip() or "qwen3-vl-8b"
        self.settings.ollama_base_url = self.ollama_url.text().strip() or "http://127.0.0.1:11434"
        self.settings.cloud_credential_provider = str(self.cloud_provider.currentData())
        self.settings.cloud_base_url = self.cloud_url.text().strip()
        self.settings.cloud_text_model = self.cloud_text_model.text().strip()
        self.settings.cloud_vision_model = self.cloud_vision_model.text().strip()
        self.settings.video_knowledge_provider = str(self.knowledge_provider.currentData())
        self.settings.video_knowledge_model = self.knowledge_model.text().strip()
        self.settings.weknora_base_url = self.weknora_url.text().strip()
        self.settings.weknora_kb_id = str(
            self.weknora_kb.currentData() or self.settings.weknora_kb_id
        )
        self.settings.weknora_kb_name = (
            self.weknora_kb.currentText() or self.settings.weknora_kb_name
        )

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _load_settings(self) -> None:
        if self.settings.project_path:
            self.project_edit.setText(self.settings.project_path)
        self.account_url.setText(self.settings.account_url)
        self._select_data(self.collection_provider, self.settings.collection_provider)
        self.collection_count.setValue(self.settings.collection_count)
        self.all_videos.setChecked(self.settings.collect_all_videos)
        self.media_limit.setValue(self.settings.media_limit)
        self._select_data(self.mode_combo, self.settings.distillation_mode)
        self._select_data(self.focus_combo, self.settings.analysis_focus)
        self._select_data(self.whisper_backend, self.settings.whisper_backend)
        self.whisper_model.setText(self.settings.whisper_model)
        self._select_data(self.vision_provider, self.settings.vision_provider)
        self.vision_model.setText(self.settings.vision_model)
        self._select_data(self.knowledge_provider, self.settings.video_knowledge_provider)
        self.knowledge_model.setText(self.settings.video_knowledge_model)
        self.ollama_url.setText(self.settings.ollama_base_url)
        self._select_data(self.cloud_provider, self.settings.cloud_credential_provider)
        self.cloud_url.setText(self.settings.cloud_base_url)
        self.cloud_text_model.setText(self.settings.cloud_text_model)
        self.cloud_vision_model.setText(self.settings.cloud_vision_model)
        self.weknora_url.setText(self.settings.weknora_base_url)
        if self.secret_store.get("weknora-api-key"):
            self.weknora_key.setPlaceholderText("已安全保存；输入新值可替换")
        if self.secret_store.get("tikhub-api-key"):
            self.tikhub_key.setPlaceholderText("已安全保存；输入新值可替换")
        self._update_mode_help()

    def save_settings(self, *, silent: bool = False) -> None:
        self._capture_settings_from_ui()
        tikhub_key = self.tikhub_key.text().strip()
        if tikhub_key:
            try:
                self.secret_store.set("tikhub-api-key", tikhub_key)
                os.environ["TIKHUB_API_KEY"] = tikhub_key
            except Exception as exc:  # noqa: BLE001
                self._show_error(exc)
                return
            self.tikhub_key.clear()
            self.tikhub_key.setPlaceholderText("已安全保存；输入新值可替换")
        self.settings_store.save(self.settings)
        if not silent:
            self.footer.setText("设置已保存；设置文件不包含任何密钥")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        try:
            self.save_settings(silent=True)
        finally:
            self.task_timer.stop()
        event.accept()
