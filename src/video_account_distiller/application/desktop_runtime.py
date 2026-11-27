"""Lifecycle management for services owned or observed by the native desktop app."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI

from video_account_distiller.api.app import create_app


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    available: bool
    endpoint: str
    message: str
    managed: bool = False


def find_available_port(host: str = "127.0.0.1", *, preferred: int = 8000) -> int:
    for port in range(preferred, preferred + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


class EmbeddedApiServer:
    """Run the existing FastAPI app in a background thread without a browser."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        task_db_path: Path | str | None = None,
        app_factory: Callable[[], FastAPI] | None = None,
    ) -> None:
        self.host = host
        self.port = port or find_available_port(host)
        self.task_db_path = task_db_path
        self._app_factory = app_factory or (lambda: create_app(task_db_path))
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._health_ok()

    def _health_ok(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=0.75)
        except requests.RequestException:
            return False
        return response.ok

    def start(self, *, timeout_seconds: float = 15.0) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            config = uvicorn.Config(
                app=self._app_factory(),
                host=self.host,
                port=self.port,
                log_level="warning",
                # A Windows GUI executable intentionally has no stderr stream.
                # Uvicorn's default logging formatter tries to bind one and
                # fails before the server starts, so the native shell owns
                # user-facing status/error presentation instead.
                log_config=None,
                access_log=False,
                reload=False,
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=self._serve,
                name="distiller-desktop-api",
                daemon=True,
            )
            self._thread.start()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._health_ok():
                return
            if self._thread is not None and not self._thread.is_alive():
                break
            time.sleep(0.05)
        self.stop()
        raise RuntimeError("本地 API 未能在限定时间内启动。")

    def _serve(self) -> None:
        assert self._server is not None
        asyncio.run(self._server.serve())

    def stop(self, *, timeout_seconds: float = 8.0) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            if server is not None:
                server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)
        with self._lock:
            self._server = None
            self._thread = None

    def status(self) -> ServiceStatus:
        available = self._health_ok()
        return ServiceStatus(
            name="蒸馏 API",
            available=available,
            endpoint=self.base_url,
            message="任务服务运行中" if available else "任务服务未启动",
            managed=True,
        )


def _probe(endpoint: str, *, timeout_seconds: float = 1.5) -> tuple[bool, str]:
    try:
        response = requests.get(endpoint, timeout=timeout_seconds)
    except requests.RequestException as exc:
        return False, str(exc)
    if response.status_code < 500:
        return True, f"HTTP {response.status_code}"
    return False, f"HTTP {response.status_code}"


class LocalServiceSupervisor:
    """Own the embedded API and optionally an Ollama process started by the app."""

    def __init__(self, api: EmbeddedApiServer | None = None) -> None:
        self.api = api or EmbeddedApiServer()
        self._ollama: subprocess.Popen[bytes] | None = None

    def start(
        self, *, start_ollama: bool = False, ollama_base_url: str = "http://127.0.0.1:11434"
    ) -> None:
        self.api.start()
        if start_ollama:
            self.start_ollama(ollama_base_url=ollama_base_url)

    def stop(self) -> None:
        self.api.stop()
        if self._ollama is not None and self._ollama.poll() is None:
            self._ollama.terminate()
            try:
                self._ollama.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._ollama.kill()
        self._ollama = None

    def start_ollama(self, *, ollama_base_url: str) -> bool:
        available, _ = _probe(f"{ollama_base_url.rstrip('/')}/api/tags")
        if available:
            return True
        executable = shutil.which("ollama")
        if executable is None:
            return False
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._ollama = subprocess.Popen(  # noqa: S603
            [executable, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            available, _ = _probe(f"{ollama_base_url.rstrip('/')}/api/tags")
            if available:
                return True
            if self._ollama.poll() is not None:
                break
            time.sleep(0.25)
        return False

    def statuses(
        self,
        *,
        ollama_base_url: str = "http://127.0.0.1:11434",
        weknora_base_url: str = "http://127.0.0.1:8080",
    ) -> list[ServiceStatus]:
        ollama_endpoint = f"{ollama_base_url.rstrip('/')}/api/tags"
        ollama_ok, ollama_message = _probe(ollama_endpoint)
        weknora_endpoint = weknora_base_url.rstrip("/")
        weknora_ok, weknora_message = _probe(weknora_endpoint)
        return [
            self.api.status(),
            ServiceStatus(
                name="Ollama",
                available=ollama_ok,
                endpoint=ollama_endpoint,
                message="模型服务可用" if ollama_ok else ollama_message,
                managed=self._ollama is not None,
            ),
            ServiceStatus(
                name="WeKnora",
                available=weknora_ok,
                endpoint=weknora_endpoint,
                message="知识库服务可达" if weknora_ok else weknora_message,
                managed=False,
            ),
        ]
