"""Выполнение блокирующих вызовов API в пуле потоков Qt.

Пример::

    run_async(lambda: api.instances(), on_done=self._show, on_error=self._fail, owner=self)

Колбэки вызываются в GUI-потоке. Если ``owner`` (QObject) уже уничтожен,
колбэки не вызываются — это защищает от падений при закрытии страниц.
"""

import traceback
from collections.abc import Callable
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from frontend.utils.logger import logger

_pending: set["_Signals"] = set()
_MAIN_THREADS = 16
_BACKGROUND_THREADS = 4
_background_pool: QThreadPool | None = None


def _pool(background: bool) -> QThreadPool:
    """Основной пул — для вызовов API; фоновый — для второстепенной загрузки (иконки),
    чтобы медленная сеть не задерживала отклик интерфейса."""
    global _background_pool
    if background:
        # Пул без родителя может быть удалён на стороне C++ (например, вместе с прежним окном) — создаём заново
        if _background_pool is None or sip.isdeleted(_background_pool):
            _background_pool = QThreadPool()
            _background_pool.setMaxThreadCount(_BACKGROUND_THREADS)
        return _background_pool
    pool = QThreadPool.globalInstance()
    if pool.maxThreadCount() < _MAIN_THREADS:
        pool.setMaxThreadCount(_MAIN_THREADS)
    return pool


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals):
        super().__init__()
        self.fn = fn
        self.signals = signals

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 — ошибка уходит в колбэк on_error
            message = str(e) or type(e).__name__
            logger.debug(f"Фоновая операция завершилась ошибкой: {message}\n{traceback.format_exc()}")
            self.signals.failed.emit(message)
        else:
            self.signals.done.emit(result)


def _alive(owner: QObject | None) -> bool:
    return owner is None or not sip.isdeleted(owner)


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    owner: QObject | None = None,
    background: bool = False,
) -> None:
    """Запускает ``fn`` в фоне; результат/ошибка передаются в GUI-поток."""
    signals = _Signals()
    _pending.add(signals)

    def finish() -> None:
        _pending.discard(signals)
        signals.deleteLater()

    def handle_done(result: Any) -> None:
        try:
            if on_done and _alive(owner):
                on_done(result)
        finally:
            finish()

    def handle_error(message: str) -> None:
        try:
            if _alive(owner):
                if on_error:
                    on_error(message)
                else:
                    logger.error(message)
        finally:
            finish()

    signals.done.connect(handle_done)
    signals.failed.connect(handle_error)
    _pool(background).start(_Job(fn, signals))
