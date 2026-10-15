"""Фоновые задачи с прогрессом (установка версий, модпаков, вход Microsoft).

Долгие операции не блокируют HTTP-запрос: endpoint создаёт задачу и сразу
возвращает её ID, а клиент опрашивает ``GET /tasks/{id}``.
"""

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from backend.core.errors import NexoraError, NotFoundError

_MAX_FINISHED = 100


_STAGE_MESSAGES = {
    "Download Libraries": "Загрузка библиотек…",
    "Download Assets": "Загрузка ресурсов игры…",
    "Install java runtime": "Установка Java…",
    "Download mrpack files": "Загрузка файлов модпака…",
    "Extract overrides": "Распаковка файлов модпака…",
    "Running installer": "Запуск установщика загрузчика…",
    "Running fabric installer": "Установка Fabric…",
    "Running quilt installer": "Установка Quilt…",
    "Installation complete": "Установка завершена",
}


def humanize_status(message: str, previous: str) -> str:
    """Переводит статусы minecraft-launcher-lib; пофайловые «Download x» не меняют этап."""
    message = str(message)
    if message in _STAGE_MESSAGES:
        return _STAGE_MESSAGES[message]
    if message.startswith("Running processor"):
        return "Обработка файлов загрузчика…"
    if message.startswith("Download ") or message.startswith("Extract "):
        return previous or "Загрузка файлов…"
    return message


class TaskCancelled(Exception):  # noqa: N818 — это сигнал отмены, а не ошибка
    """Задача отменена пользователем."""


@dataclass
class Task:
    """Состояние фоновой задачи."""

    id: str
    kind: str
    title: str
    status: str = "pending"  # pending | running | done | failed | cancelled
    message: str = ""
    progress: float | None = None  # 0..1, None — неопределённый прогресс
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    _max: int = 0
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    # --- API для кода внутри задачи -------------------------------------
    def set_status(self, message: str) -> None:
        self.check_cancelled()
        self.message = str(message)

    def set_max(self, value: int) -> None:
        self._max = max(int(value), 0)
        self.progress = 0.0 if self._max else None

    def set_progress(self, value: int) -> None:
        self.check_cancelled()
        if self._max:
            self.progress = max(0.0, min(1.0, int(value) / self._max))

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise TaskCancelled()

    def callback_dict(self) -> dict[str, Callable]:
        """Колбэки в формате minecraft-launcher-lib."""
        return {
            "setStatus": lambda msg: self.set_status(humanize_status(msg, self.message)),
            "setProgress": self.set_progress,
            "setMax": self.set_max,
        }

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "message": self.message,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class TaskManager:
    """Пул фоновых задач."""

    def __init__(self, max_workers: int = 4):
        self._max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, title: str, fn: Callable[[Task], Any]) -> Task:
        """Запускает ``fn(task)`` в фоне. Результат функции попадает в ``task.result``."""
        task = Task(id=uuid.uuid4().hex, kind=kind, title=title)
        with self._lock:
            self._tasks[task.id] = task
            self._trim()
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self._max_workers,
                                                    thread_name_prefix="nexora-task")
            self._executor.submit(self._run, task, fn)
        logger.info(f"Task {task.id[:8]} [{kind}] submitted: {title}")
        return task

    def _run(self, task: Task, fn: Callable[[Task], Any]) -> None:
        task.status = "running"
        try:
            task.result = fn(task)
            task.status = "done"
            task.progress = 1.0
            logger.info(f"Task {task.id[:8]} [{task.kind}] done")
        except TaskCancelled:
            task.status = "cancelled"
            task.message = "Отменено"
            logger.info(f"Task {task.id[:8]} [{task.kind}] cancelled")
        except NexoraError as e:
            task.status = "failed"
            task.error = str(e)
            logger.warning(f"Task {task.id[:8]} [{task.kind}] failed: {e}")
        except Exception as e:  # noqa: BLE001 — ошибка задачи не должна ронять пул
            task.status = "failed"
            task.error = f"{type(e).__name__}: {e}"
            logger.error(f"Task {task.id[:8]} [{task.kind}] crashed:\n{traceback.format_exc()}")
        finally:
            task.finished_at = time.time()

    def _trim(self) -> None:
        finished = sorted((t for t in self._tasks.values() if t.finished), key=lambda t: t.created_at)
        for t in finished[: max(0, len(finished) - _MAX_FINISHED)]:
            self._tasks.pop(t.id, None)

    def get(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise NotFoundError(f"Задача '{task_id}' не найдена")
        return task

    def all(self, active_only: bool = False) -> list[Task]:
        with self._lock:
            tasks = list(self._tasks.values())
        if active_only:
            tasks = [t for t in tasks if not t.finished]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def cancel(self, task_id: str) -> Task:
        task = self.get(task_id)
        if not task.finished:
            task._cancel.set()
        return task

    def wait(self, task_id: str, timeout: float = 30.0) -> Task:
        """Ждёт завершения задачи (используется в тестах)."""
        deadline = time.time() + timeout
        task = self.get(task_id)
        while not task.finished and time.time() < deadline:
            time.sleep(0.02)
        return task

    def shutdown(self) -> None:
        for task in self.all(active_only=True):
            task._cancel.set()
        with self._lock:
            executor, self._executor = self._executor, None
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)


task_manager = TaskManager()
