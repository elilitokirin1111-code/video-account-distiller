"""Qt-native desktop interface; no browser or embedded web view is used."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 26, 22, 20)
        brand = QLabel("VAD")
        brand.setObjectName("brandMark")
        name = QLabel("Video Account\nDistiller")
        name.setObjectName("brandName")
        strapline = QLabel("账号内容蒸馏工作台")
        strapline.setObjectName("brandStrapline")
        side.addWidget(brand)
        side.addWidget(name)
        side.addWidget(strapline)
        side.addSpacing(24)

        self.stack = QStackedWidget()
        pages = [
            ("总览", self._overview_page()),
            ("账号蒸馏", self._distill_page()),
            ("任务中心", self._tasks_page()),
            ("知识结果", self._results_page()),
            ("WeKnora", self._weknora_page()),
            ("设置", self._settings_page()),
        ]
        self.nav_buttons: list[QPushButton] = []
        for index, (label, page) in enumerate(pages):
            nav = QPushButton(label)
            nav.setObjectName("navButton")
            nav.setCheckable(True)
            nav.setAutoExclusive(True)
            nav.clicked.connect(lambda _checked=False, value=index: self._show_page(value))
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
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 20, 28, 18)
        content_layout.setSpacing(14)
        project_bar = QFrame()
        project_bar.setObjectName("projectBar")
        project_layout = QHBoxLayout(project_bar)
        project_layout.setContentsMargins(16, 10, 16, 10)
        project_layout.addWidget(QLabel("当前项目"))
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("选择或初始化一个本地蒸馏项目目录")
        project_layout.addWidget(self.project_edit, 1)
        browse = _button("选择目录")
        browse.clicked.connect(self.choose_project)
        initialize = _button("初始化项目", primary=True)
        initialize.clicked.connect(self.initialize_project)
        project_layout.addWidget(browse)
        project_layout.addWidget(initialize)
        content_layout.addWidget(project_bar)
        content_layout.addWidget(self.stack, 1)
        self.footer = QLabel("就绪")
        self.footer.setObjectName("footer")
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
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            _title(
                "账号采集与蒸馏",
                "一个入口完成主页采集、视频下载、语音转写、视觉理解以及运营蒸馏或纯知识蒸馏。",
            )
        )
        form_frame = QFrame()
        form_frame.setObjectName("panel")
        grid = QGridLayout(form_frame)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(14)

        self.account_url = QLineEdit()
        self.account_url.setPlaceholderText("粘贴抖音账号主页链接")
        grid.addWidget(QLabel("账号主页"), 0, 0)
        grid.addWidget(self.account_url, 0, 1, 1, 5)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("纯知识蒸馏 · 一视频一文档", "knowledge")
        self.mode_combo.addItem("运营蒸馏 · 选题/表达/增长", "creative_learning")
        self.mode_combo.currentIndexChanged.connect(self._update_mode_help)
        self.focus_combo = QComboBox()
        self.focus_combo.addItem("通用分析", "general")
        self.focus_combo.addItem("酒旅迁移分析", "hospitality")
        self.collection_provider = QComboBox()
        self.collection_provider.addItem("MediaCrawler（本机浏览器）", "mediacrawler")
        self.collection_provider.addItem("TikHub（付费 API）", "tikhub")
        grid.addWidget(QLabel("蒸馏目标"), 1, 0)
        grid.addWidget(self.mode_combo, 1, 1)
        grid.addWidget(QLabel("分析方向"), 1, 2)
        grid.addWidget(self.focus_combo, 1, 3)
        grid.addWidget(QLabel("采集方式"), 1, 4)
        grid.addWidget(self.collection_provider, 1, 5)

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
        grid.addWidget(QLabel("视频数量"), 2, 0)
        grid.addWidget(self.collection_count, 2, 1)
        grid.addWidget(self.all_videos, 2, 2, 1, 2)
        grid.addWidget(QLabel("下载/转写数量"), 2, 4)
        grid.addWidget(self.media_limit, 2, 5)

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
        grid.addWidget(QLabel("转写引擎"), 3, 0)
        grid.addWidget(self.whisper_backend, 3, 1)
        grid.addWidget(QLabel("转写模型"), 3, 2)
        grid.addWidget(self.whisper_model, 3, 3)
        grid.addWidget(QLabel("视觉服务"), 3, 4)
        grid.addWidget(self.vision_provider, 3, 5)
        grid.addWidget(QLabel("视觉模型"), 4, 4)
        grid.addWidget(self.vision_model, 4, 5)

        self.knowledge_provider = QComboBox()
        self.knowledge_provider.addItem("Ollama", "ollama")
        self.knowledge_provider.addItem("llama.cpp", "llamacpp")
        self.knowledge_provider.addItem("云端兼容 API", "cloud")
        self.knowledge_provider.addItem("规则降级（无模型）", "none")
        self.knowledge_model = QLineEdit("qwen3:8b")
        grid.addWidget(QLabel("知识模型服务"), 4, 0)
        grid.addWidget(self.knowledge_provider, 4, 1)
        grid.addWidget(QLabel("知识模型"), 4, 2)
        grid.addWidget(self.knowledge_model, 4, 3)

        self.mode_help = QLabel()
        self.mode_help.setObjectName("callout")
        self.mode_help.setWordWrap(True)
        grid.addWidget(self.mode_help, 5, 0, 1, 6)
        layout.addWidget(form_frame)
        actions = QHBoxLayout()
        preflight = _button("仅做预检")
        preflight.clicked.connect(lambda: self.submit_workflow(dry_run=True))
        submit = _button("开始完整蒸馏", primary=True)
        submit.clicked.connect(lambda: self.submit_workflow(dry_run=False))
        actions.addStretch(1)
        actions.addWidget(preflight)
        actions.addWidget(submit)
        layout.addLayout(actions)
        layout.addStretch(1)
        self._update_mode_help()
        return page

    def _tasks_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_title("任务中心", "轻量轮询任务摘要；只有查看单个任务时才读取完整结果。"))
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
        layout.addLayout(actions)
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
        layout.addWidget(self.tasks_table, 3)
        self.task_details = QTextEdit()
        self.task_details.setReadOnly(True)
        self.task_details.setPlaceholderText("选择一个任务查看 checkpoint、错误与输出路径。")
        layout.addWidget(self.task_details, 2)
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
            QMainWindow, QWidget { background: #F4F6F8; color: #17212B; }
            #sidebar { background: #12202B; }
            #brandMark { color: #67E8B4; font-size: 13px; font-weight: 800; letter-spacing: 2px; }
            #brandName { color: white; font-size: 22px; font-weight: 700; }
            #brandStrapline, #sidebarStatus { color: #91A4B3; font-size: 12px; }
            #navButton { text-align: left; color: #C9D5DE; background: transparent; border: 0;
                         padding: 11px 13px; border-radius: 8px; font-weight: 600; }
            #navButton:hover { background: #1B303E; color: white; }
            #navButton:checked { background: #245C4A; color: #D9FFF0; }
            #projectBar, #panel, QGroupBox, #metricCard { background: white; border: 1px solid #DCE3E8; border-radius: 10px; }
            #projectBar QLabel { font-weight: 700; }
            #pageTitle { font-size: 26px; font-weight: 750; color: #10202C; }
            #pageSubtitle, #muted, #cardDetail { color: #667784; }
            #cardLabel { color: #667784; font-weight: 650; }
            #cardValue { font-size: 22px; font-weight: 750; color: #153D31; }
            #largeSummary { font-size: 20px; font-weight: 700; }
            #callout { background: #EAF7F1; border: 1px solid #BEE7D5; border-radius: 8px;
                       padding: 12px; color: #245C4A; }
            #footer { color: #63727C; padding-top: 4px; }
            QGroupBox { margin-top: 12px; padding: 18px 14px 12px 14px; font-weight: 700; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget {
                background: white; border: 1px solid #CAD4DB; border-radius: 7px; padding: 7px;
                selection-background-color: #2F8064;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border: 1px solid #2F8064; }
            QPushButton { background: white; border: 1px solid #BAC7CF; border-radius: 7px; padding: 7px 14px; font-weight: 650; }
            QPushButton:hover { border-color: #2F8064; color: #245C4A; }
            QPushButton[primary="true"] { background: #236B53; border-color: #236B53; color: white; }
            QPushButton[primary="true"]:hover { background: #195440; }
            QHeaderView::section { background: #EDF1F4; color: #4C5E69; border: 0; border-bottom: 1px solid #D8E0E5; padding: 8px; font-weight: 700; }
            QTableWidget { gridline-color: #E3E8EC; }
            """
        )

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
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
    ) -> None:
        self.footer.setText(message)
        worker = _Worker(call)

        def failure(value: object) -> None:
            assert isinstance(value, Exception)
            self.footer.setText("操作失败")
            if on_failure is not None:
                on_failure(value)
            else:
                self._show_error(value)

        worker.signals.success.connect(on_success)
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
            self.footer.setText(f"任务已提交：{task_id or '-'}")
            self._show_page(2)
            self.refresh_tasks()

        self._capture_settings_from_ui()
        self.settings_store.save(self.settings)
        self._run(submit, done, message="正在提交预检…" if dry_run else "正在提交蒸馏任务…")

    def refresh_tasks(self) -> None:
        if self._tasks_busy or not self.supervisor.api.running:
            return
        self._tasks_busy = True

        def done(value: object) -> None:
            self._tasks_busy = False
            tasks = value if isinstance(value, list) else []
            self.tasks_table.setRowCount(len(tasks))
            for row, task in enumerate(tasks):
                progress = task.get("progress")
                progress_text = (
                    f"{float(progress) * 100:.0f}%" if isinstance(progress, int | float) else "-"
                )
                values = [
                    task.get("status"),
                    task.get("task_type"),
                    task.get("stage"),
                    progress_text,
                    task.get("message"),
                    task.get("updated_at"),
                    task.get("task_id"),
                ]
                for column, text in enumerate(values):
                    self.tasks_table.setItem(row, column, QTableWidgetItem(str(text or "")))
            self.footer.setText(f"已刷新 {len(tasks)} 个任务")
            if any(task.get("status") == "completed" for task in tasks[:3]):
                self.refresh_bundles()

        def failed(exc: Exception) -> None:
            self._tasks_busy = False
            self.sidebar_status.setText("● 本地 API 未连接")
            self.footer.setText(str(exc))

        self._run(
            lambda: self.client.list_tasks(limit=80),
            done,
            message="正在刷新任务…",
            on_failure=failed,
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
                    labels[1].setText(f"{status.message}\n{status.endpoint}")
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
            self.footer.setText("服务状态已刷新")

        def failed(exc: Exception) -> None:
            self._service_busy = False
            self.sidebar_status.setText("● 服务异常")
            self.footer.setText(str(exc))

        self._run(check, done, message="正在检查服务…", on_failure=failed)

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
