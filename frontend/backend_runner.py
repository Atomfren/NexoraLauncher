"""Встроенный backend: uvicorn в фоновом потоке того же процесса.

Порт выбирается свободный, токен доступа генерируется случайно — так лаунчер
не конфликтует с другими программами на 8000 порту, а сторонние сайты
не могут обращаться к API.
"""

import secrets
import socket
import threading
import time

import uvicorn
from loguru import logger


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class EmbeddedBackend:
    """Запускает FastAPI-приложение в daemon-потоке."""

    def __init__(self, port: int = 0, token: str | None = None):
        self.port = port or _free_port()
        self.token = token if token is not None else secrets.token_urlsafe(32)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    def start(self, timeout: float = 20.0) -> None:
        from backend.config import settings
        settings.api_token = self.token
        from backend.main import app

        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning",
                                access_log=False, log_config=None)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="nexora-backend", daemon=True)
        self._thread.start()
        deadline = time.time() + timeout
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError("Backend завершился при запуске (см. backend.log)")
            if time.time() > deadline:
                raise RuntimeError("Backend не запустился вовремя")
            time.sleep(0.05)
        logger.info(f"Встроенный backend запущен на порту {self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
