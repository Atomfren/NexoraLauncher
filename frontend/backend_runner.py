"""Встроенный backend: uvicorn в фоновом потоке того же процесса.

Порт выбирается свободный, токен доступа генерируется случайно — так лаунчер
не конфликтует с другими программами на 8000 порту, а сторонние сайты
не могут обращаться к API.

Поднимается он не мгновенно: импорт FastAPI и клиентов занимает секунды, причём
сам uvicorn стартует за сотню миллисекунд. Поэтому вся эта работа делается **в потоке**,
а ``start_async()`` возвращает управление сразу — окно открывается, не дожидаясь backend.
Адрес и токен известны заранее, так что клиента можно создать до того, как сервер ответит.
"""

import secrets
import socket
import threading
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import uvicorn


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
        self._error: BaseException | None = None
        self._stopping = False
        self._lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/api/v1"

    def start(self, timeout: float = 20.0) -> None:
        """Поднимает backend и дожидается готовности (самопроверка, тесты)."""
        self.start_async()
        self.wait_ready(timeout)

    def start_async(self) -> None:
        """Запускает backend в фоне и сразу возвращает управление."""
        self._thread = threading.Thread(target=self._serve, name="nexora-backend", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        """Тело потока: импорт приложения, настройка uvicorn и обслуживание запросов."""
        try:
            # Всё тяжёлое импортируется здесь, в фоновом потоке: uvicorn — четверть секунды,
            # backend.main с роутерами — полторы. Окно в это время уже рисуется.
            import uvicorn

            from backend.config import settings
            settings.api_token = self.token
            from backend.main import app

            # Зависшие соединения закрываются через 3 с: остановка должна завершаться внутри stop(),
            # иначе запоздалое завершение backend отменяло задачи уже следующего запуска (и тестов)
            config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning",
                                    access_log=False, log_config=None, timeout_graceful_shutdown=3)
            server = uvicorn.Server(config)
            with self._lock:
                if self._stopping:
                    return
                self._server = server
            server.run()
        except BaseException as e:  # noqa: BLE001 — иначе поток умрёт молча, а окно будет ждать вечно
            self._error = e
            logger.exception(f"Backend не поднялся: {e}")

    @property
    def ready(self) -> bool:
        return bool(self._server and self._server.started)

    @property
    def error(self) -> BaseException | None:
        """Ошибка, с которой backend не смог подняться."""
        return self._error

    def wait_ready(self, timeout: float = 20.0) -> None:
        """Ждёт готовности backend. Бросает ``RuntimeError``, если он не поднялся."""
        deadline = time.time() + timeout
        while not self.ready:
            if self._error is not None:
                raise RuntimeError(f"Backend завершился при запуске: {self._error}")
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Backend завершился при запуске (см. backend.log)")
            if time.time() > deadline:
                raise RuntimeError("Backend не запустился вовремя")
            time.sleep(0.02)
        logger.info(f"Встроенный backend запущен на порту {self.port}")

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            server = self._server
        if server:
            server.should_exit = True
        if self._thread:
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                logger.warning("Встроенный backend не остановился за 20 с")
