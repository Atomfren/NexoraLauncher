"""Запуск: окно не ждёт backend, а первые запросы его дожидаются."""

import threading
import time

import httpx
import pytest

from frontend.backend_runner import EmbeddedBackend
from frontend.services.api_client import ApiClient, ApiError


def test_start_async_returns_immediately():
    """Главный поток не должен стоять, пока поднимается backend: на импорты уходят секунды."""
    backend = EmbeddedBackend()
    started = time.perf_counter()
    backend.start_async()
    handed_back = time.perf_counter() - started
    try:
        assert handed_back < 0.2, f"start_async задержал поток на {handed_back:.2f} с"
        assert backend.base_url.startswith("http://127.0.0.1:")  # адрес известен сразу
        assert backend.token
        backend.wait_ready(30)
        assert backend.ready
    finally:
        backend.stop()


def test_wait_ready_reports_failure(monkeypatch):
    """Если backend не поднялся, ждущий получает ошибку, а не висит вечно."""
    backend = EmbeddedBackend()
    monkeypatch.setattr(backend, "_serve", lambda: setattr(backend, "_error", RuntimeError("не собрался")))
    backend.start_async()
    with pytest.raises(RuntimeError, match="не собрался"):
        backend.wait_ready(5)
    assert backend.error is not None


def test_stop_before_server_exists():
    """Закрыли окно, пока backend ещё поднимался — остановка не должна зависнуть."""
    backend = EmbeddedBackend()
    backend.start_async()
    started = time.perf_counter()
    backend.stop()  # почти наверняка раньше, чем поднялся uvicorn
    assert time.perf_counter() - started < 25, "stop() завис"


def test_client_waits_for_late_backend():
    """Первые запросы уходят раньше, чем backend ответит, и должны его дождаться."""
    backend = EmbeddedBackend()
    api = ApiClient(backend.base_url, backend.token)
    result: dict = {}

    def ask() -> None:
        try:
            result["health"] = api.health()
        except ApiError as e:  # pragma: no cover — сюда мы не должны попадать
            result["error"] = str(e)

    asking = threading.Thread(target=ask)
    asking.start()
    time.sleep(0.3)          # запрос уже в пути, backend ещё не поднят
    backend.start_async()
    asking.join(timeout=40)
    try:
        assert result.get("health", {}).get("status") == "healthy", result
    finally:
        api.close()
        backend.stop()


def test_client_reports_error_when_backend_never_comes(monkeypatch):
    """Когда ждать уже бессмысленно, ошибка всё-таки показывается."""
    import frontend.services.api_client as client_module

    monkeypatch.setattr(client_module, "_STARTUP_GRACE", 0.3)
    api = ApiClient("http://127.0.0.1:9", "token")  # порт 9 — discard, никто не ответит
    try:
        with pytest.raises(ApiError, match="Нет связи с backend"):
            api.health()
    finally:
        api.close()


def test_connection_error_after_first_success_is_not_retried(monkeypatch):
    """Ожидание действует только на старте: потом обрыв связи — сразу ошибка, а не 30 секунд."""
    backend = EmbeddedBackend()
    backend.start_async()
    backend.wait_ready(30)
    api = ApiClient(backend.base_url, backend.token)
    assert api.health()["status"] == "healthy"
    backend.stop()

    started = time.perf_counter()
    with pytest.raises((ApiError, httpx.HTTPError)):
        api.health()
    assert time.perf_counter() - started < 5
    api.close()
