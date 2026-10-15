"""Отслеживание фоновых задач backend (опрос /tasks)."""

from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from frontend.services.api_client import ApiClient
from frontend.utils.worker import run_async

_POLL_MS = 600


class TaskTracker(QObject):
    """Опрашивает активные задачи и сообщает об их прогрессе/завершении."""

    # Список активных задач (для индикатора в статус-баре)
    tasks_changed = pyqtSignal(list)
    # Завершённая задача (done / failed / cancelled)
    task_finished = pyqtSignal(dict)

    def __init__(self, api: ApiClient, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self._watched: dict[str, list[tuple[Callable | None, Callable | None]]] = {}
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def track(self, task: dict, on_done: Callable[[dict], None] | None = None,
              on_error: Callable[[str], None] | None = None) -> None:
        """Подписывается на завершение задачи. ``task`` — ответ API с полем ``id``."""
        self._watched.setdefault(task["id"], []).append((on_done, on_error))
        self._poll()

    def _poll(self) -> None:
        if self._busy:
            return
        self._busy = True
        watched = list(self._watched)

        def fetch():
            active = self.api.tasks(active=True)
            finished = []
            active_ids = {t["id"] for t in active}
            for task_id in watched:
                if task_id not in active_ids:
                    try:
                        finished.append(self.api.task(task_id))
                    except Exception:  # noqa: BLE001 — задача могла быть удалена
                        finished.append({"id": task_id, "status": "failed", "error": "Задача потеряна",
                                         "result": None, "title": ""})
            return active, finished

        run_async(fetch, self._on_polled, self._on_poll_error, owner=self)

    def _on_poll_error(self, _message: str) -> None:
        self._busy = False

    def _on_polled(self, data: tuple[list[dict], list[dict]]) -> None:
        self._busy = False
        active, finished = data
        self.tasks_changed.emit(active)
        for task in finished:
            if task.get("status") not in ("done", "failed", "cancelled"):
                continue
            callbacks = self._watched.pop(task["id"], [])
            self.task_finished.emit(task)
            for on_done, on_error in callbacks:
                if task["status"] == "done":
                    if on_done:
                        on_done(task)
                elif on_error:
                    on_error(task.get("error") or task.get("status", ""))
