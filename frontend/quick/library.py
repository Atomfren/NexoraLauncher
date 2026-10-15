"""Библиотека: список сборок, выбор, запуск и остановка.

Состояние кнопки «Играть» для каждой сборки:
    none       — игра не установлена → «Установить»
    installing — идёт установка (прогресс задачи backend)
    launching  — запуск: докачка файлов и старт процесса
    ready      — можно играть
    running    — игра запущена → «Остановить» и таймер
"""

from pathlib import Path
from typing import Any

from PyQt6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    QUrl,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)

from frontend.quick import art, fmt
from frontend.quick.bridge import Shell
from frontend.quick.images import file_ref
from frontend.services.api_client import ApiClient, ApiError
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.i18n import t

_FAST_POLL_MS = 2000
_SLOW_POLL_MS = 15000
_IMAGE_EXT = (".png", ".jpg", ".jpeg")

ROLES = ("name", "version", "loader", "loaderVersion", "optifine", "installed", "state", "progress",
         "playtime", "lastPlayed", "lastPlayedRaw", "seed", "palette", "cover", "background", "gameDir", "path",
         "startedAt", "pid", "maxMemory", "minMemory", "javaPath", "jvmArgs", "width", "height", "fullscreen")


def latest_screenshot(game_dir: str) -> str:
    """Путь к самому свежему скриншоту сборки или пустая строка."""
    folder = Path(game_dir) / "screenshots"
    try:
        shots = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXT]
    except OSError:
        return ""
    return str(max(shots, key=lambda p: p.stat().st_mtime)) if shots else ""


def build_row(instance: dict, process: dict | None, runtime: dict | None) -> dict[str, Any]:
    """Строка модели из ответа API (/instances/) и данных о процессе."""
    name = instance["name"]
    seed = art.seed_of(name)
    palette = art.palette_for(name)
    shot = instance.get("_screenshot", "")
    if runtime:
        state = runtime["state"]
    elif instance.get("running_pid"):
        state = "running"
    elif not instance.get("installed"):
        state = "none"
    else:
        state = "ready"
    return {
        "name": name,
        "version": instance.get("version", ""),
        "loader": instance.get("mod_loader", "vanilla"),
        "loaderVersion": instance.get("loader_version", ""),
        "optifine": instance.get("optifine", ""),
        "installed": bool(instance.get("installed")),
        "state": state,
        "progress": float(runtime["progress"]) if runtime else 0.0,
        "playtime": fmt.duration(instance.get("total_play_seconds", 0)),
        "lastPlayed": fmt.when(instance.get("last_played")),
        "lastPlayedRaw": instance.get("last_played", ""),
        "seed": seed,
        "palette": palette,
        "cover": file_ref(shot) if shot else f"image://nx/scene/{palette}/{seed}/20/20",
        "background": QUrl.fromLocalFile(shot).toString() if shot else "",
        "gameDir": instance.get("game_dir", ""),
        "path": instance.get("path", ""),
        "startedAt": float(process["started_at"]) if process else 0.0,
        "pid": int(instance.get("running_pid") or 0),
        "maxMemory": int(instance.get("max_memory") or 0),
        "minMemory": int(instance.get("min_memory") or 0),
        "javaPath": instance.get("java_path", ""),
        "jvmArgs": instance.get("jvm_args", ""),
        "width": int(instance.get("width") or 0),
        "height": int(instance.get("height") or 0),
        "fullscreen": bool(instance.get("fullscreen")),
    }


class InstancesModel(QAbstractListModel):
    countChanged = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key_index = role - Qt.ItemDataRole.UserRole - 1
        if 0 <= key_index < len(ROLES):
            return self._rows[index.row()].get(ROLES[key_index])
        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {Qt.ItemDataRole.UserRole + 1 + i: QByteArray(name.encode()) for i, name in enumerate(ROLES)}

    @pyqtProperty(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)

    def rows(self) -> list[dict]:
        return self._rows

    def set_rows(self, rows: list[dict]) -> None:
        if [r["name"] for r in rows] == [r["name"] for r in self._rows]:
            for i, row in enumerate(rows):
                if row != self._rows[i]:
                    self._rows[i] = row
                    idx = self.index(i)
                    self.dataChanged.emit(idx, idx)
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    @pyqtSlot(str, result=int)
    def indexOf(self, name: str) -> int:
        return next((i for i, r in enumerate(self._rows) if r["name"] == name), -1)


class Library(QObject):
    selectedChanged = pyqtSignal()
    currentChanged = pyqtSignal()
    totalChanged = pyqtSignal()
    loadedChanged = pyqtSignal()
    # Игра закрылась (имя сборки, код выхода или -1, если неизвестен)
    gameExited = pyqtSignal(str, int)
    # Для запуска нужен аккаунт
    accountRequired = pyqtSignal(str)
    # В сборку поставили контент (из каталога, мастера) — вкладкам пора перечитать
    contentInstalled = pyqtSignal(str)

    def __init__(self, api: ApiClient, shell: Shell, last_instance: str = "", parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self._model = InstancesModel(self)
        self._instances: list[dict] = []
        self._processes: dict[str, dict] = {}
        self._runtime: dict[str, dict] = {}  # имя → {state, progress, task}
        self._query = ""
        self._selected = last_instance
        self._loaded = False
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(_SLOW_POLL_MS)
        shell.tracker.tasks_changed.connect(self._on_tasks)
        self.refresh()

    # --- Свойства -------------------------------------------------------------------------------
    @pyqtProperty(QObject, constant=True)
    def model(self) -> InstancesModel:
        return self._model

    @pyqtProperty(str, notify=selectedChanged)
    def selected(self) -> str:
        return self._selected

    @pyqtProperty("QVariantMap", notify=currentChanged)
    def current(self) -> dict:
        return self._row(self._selected) or {}

    @pyqtProperty(int, notify=totalChanged)
    def total(self) -> int:
        return len(self._instances)

    @pyqtProperty(bool, notify=loadedChanged)
    def loaded(self) -> bool:
        return self._loaded

    def _row(self, name: str) -> dict | None:
        instance = next((i for i in self._instances if i["name"] == name), None)
        if instance is None:
            return None
        return build_row(instance, self._processes.get(name), self._runtime.get(name))

    # --- Загрузка -------------------------------------------------------------------------------
    def stop_polling(self) -> None:
        self._timer.stop()
        self._busy = True  # новые запросы больше не уходят

    @pyqtSlot()
    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def fetch():
            instances = self.api.instances()
            for instance in instances:
                instance["_screenshot"] = latest_screenshot(instance.get("game_dir", ""))
            processes = [p for p in self.api.processes() if p.get("exit_code") is None]
            return instances, processes

        run_async(fetch, self._on_loaded, self._on_load_error, owner=self)

    def _on_load_error(self, message: str) -> None:
        self._busy = False
        logger.warning(f"Сборки не загружены: {message}")

    def _on_loaded(self, data: tuple[list[dict], list[dict]]) -> None:
        self._busy = False
        instances, processes = data
        was_running = {n for n, p in self._processes.items()}
        self._processes = {p["instance"]: p for p in processes}
        for name in was_running - set(self._processes):
            if name not in self._runtime:
                self.gameExited.emit(name, -1)
        instances.sort(key=lambda i: (i.get("last_played") or "", i["name"].lower()), reverse=True)
        count_changed = len(instances) != len(self._instances)
        self._instances = instances
        names = [i["name"] for i in instances]
        if self._selected not in names:
            self._selected = names[0] if names else ""
            self.selectedChanged.emit()
        self._apply()
        if count_changed:
            self.totalChanged.emit()
        if not self._loaded:
            self._loaded = True
            self.loadedChanged.emit()
        busy = self._runtime or self._processes
        self._timer.setInterval(_FAST_POLL_MS if busy else _SLOW_POLL_MS)

    def _apply(self) -> None:
        q = self._query.lower()
        rows = [build_row(i, self._processes.get(i["name"]), self._runtime.get(i["name"]))
                for i in self._instances if not q or q in i["name"].lower()]
        self._model.set_rows(rows)
        self.currentChanged.emit()

    @pyqtSlot(result="QVariantList")
    def entries(self) -> list[dict]:
        """Все сборки без фильтра — для палитры команд."""
        return [{"name": i["name"], "loader": i.get("mod_loader", "vanilla"), "version": i.get("version", "")}
                for i in self._instances]

    @pyqtSlot(str)
    def setQuery(self, query: str) -> None:
        self._query = query.strip()
        self._apply()

    @pyqtSlot(str)
    def select(self, name: str) -> None:
        if name != self._selected:
            self._selected = name
            self.selectedChanged.emit()
            self.currentChanged.emit()

    # --- Задачи установки/запуска ------------------------------------------------------------
    def _on_tasks(self, active: list[dict]) -> None:
        by_id = {task["id"]: task for task in active}
        changed = False
        for runtime in self._runtime.values():
            task = by_id.get(runtime.get("task", ""))
            if task and float(task.get("progress") or 0) != runtime["progress"]:
                runtime["progress"] = float(task.get("progress") or 0)
                changed = True
        if changed:
            self._apply()

    def _start_task(self, name: str, state: str, call, on_done) -> None:
        self._runtime[name] = {"state": state, "progress": 0.0, "task": ""}
        self._apply()
        self._timer.setInterval(_FAST_POLL_MS)

        def failed(message: str) -> None:
            self._runtime.pop(name, None)
            self._apply()
            self.refresh()
            self.shell.toast(message, "err")

        def finished(task: dict) -> None:
            self._runtime.pop(name, None)
            on_done(task)
            self.refresh()

        def started(task: dict) -> None:
            if "auth_required" in task:
                self._runtime.pop(name, None)
                self._apply()
                self.accountRequired.emit(task["auth_required"])
                return
            self._runtime[name]["task"] = task["id"]
            self.shell.tracker.track(task, finished, failed)

        def call_checked():
            try:
                return call()
            except ApiError as e:
                if e.status_code == 401:
                    return {"auth_required": str(e)}
                raise

        run_async(call_checked, started, failed, owner=self)

    @pyqtSlot(str)
    @pyqtSlot(str, str)
    def play(self, name: str, server: str = "") -> None:
        host, _, port = server.strip().rpartition(":") if ":" in server else (server.strip(), "", "")
        port_num = int(port) if port.isdigit() else 25565

        def done(_task: dict) -> None:
            self.shell.toast(t("q.game_started", name=name), "info")

        self._start_task(name, "launching", lambda: self.api.launch_instance(name, host, port_num), done)

    @pyqtSlot(str)
    def playWithFriends(self, name: str) -> None:
        """Туннель e4mc для мира и запуск: адрес появится после «Открыть для сети» в игре."""
        def ready(_task: dict) -> None:
            self.shell.toast(t("q.friends_hint"), "info")
            self.play(name)

        self._start_task(name, "launching", lambda: self.api.prepare_friends(name), ready)

    @pyqtSlot(str)
    def install(self, name: str) -> None:
        self._start_task(name, "installing", lambda: self.api.prepare_instance(name),
                         lambda _task: self.shell.toast(t("q.installed", name=name)))

    @pyqtSlot(str)
    def repair(self, name: str) -> None:
        self._start_task(name, "installing", lambda: self.api.prepare_instance(name, force=True),
                         lambda _task: self.shell.toast(t("q.repaired")))

    @pyqtSlot(str)
    def stop(self, name: str) -> None:
        row = self._row(name)
        if not row or not row["pid"]:
            return
        run_async(lambda: self.api.stop_process(row["pid"]), lambda _r: self.refresh(),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- Управление сборкой ------------------------------------------------------------------
    def _mutate(self, call, done_text: str = "", select: str = "") -> None:
        def done(_result) -> None:
            if select:
                self._selected = select
                self.selectedChanged.emit()
            if done_text:
                self.shell.toast(done_text)
            self.refresh()

        run_async(call, done, lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, str)
    def rename(self, name: str, new_name: str) -> None:
        new_name = new_name.strip()
        if new_name and new_name != name:
            self._mutate(lambda: self.api.rename_instance(name, new_name), t("q.renamed"), new_name)

    @pyqtSlot(str)
    def duplicate(self, name: str) -> None:
        names = {i["name"] for i in self._instances}
        new_name = next(f"{name} ({n})" for n in range(2, 1000) if f"{name} ({n})" not in names)
        self._mutate(lambda: self.api.duplicate_instance(name, new_name), t("q.duplicated", name=new_name),
                     new_name)

    @pyqtSlot(str)
    def remove(self, name: str) -> None:
        self._mutate(lambda: self.api.delete_instance(name), t("q.deleted", name=name))

    @pyqtSlot(str, str)
    def export(self, name: str, url: str) -> None:
        """Экспорт в .zip (вся сборка) или .mrpack (для Modrinth и друзей) — по расширению файла."""
        from frontend.quick.build import local_path
        path = local_path(url)
        call = self.api.export_mrpack if path.lower().endswith(".mrpack") else self.api.export_instance

        def finished(_task: dict) -> None:
            self.shell.toast(t("q.exported", path=path))

        run_async(lambda: call(name, path),
                  lambda task: self.shell.tracker.track(task, finished, lambda msg: self.shell.toast(msg, "err")),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot("QVariantList")
    def dropFiles(self, urls: list) -> None:
        """Файлы, брошенные на окно: .jar — в моды выбранной сборки, .zip/.mrpack — импорт новой сборки."""
        from frontend.quick.build import local_path
        paths = [local_path(u) for u in urls]
        jars = [p for p in paths if p.lower().endswith(".jar")]
        packs = [p for p in paths if p.lower().endswith((".zip", ".mrpack"))]
        if jars and self._selected:
            name = self._selected

            def add_all():
                for path in jars:
                    self.api.add_local_content(name, "mod", path)

            def added(_r) -> None:
                self.shell.toast(fmt.count(len(jars), "q.added_files"))
                self.contentInstalled.emit(name)

            run_async(add_all, added, lambda msg: self.shell.toast(msg, "err"), owner=self)
        for path in packs:
            def imported(task: dict) -> None:
                new_name = (task.get("result") or {}).get("name", "")
                self.shell.toast(t("q.imported", name=new_name))
                self.refresh()

            run_async(lambda path=path: self.api.import_instance(path),
                      lambda task: self.shell.tracker.track(task, imported, lambda msg: self.shell.toast(msg, "err")),
                      lambda msg: self.shell.toast(msg, "err"), owner=self)
        if not jars and not packs:
            self.shell.toast(t("q.drop_unknown"), "err")

    @pyqtSlot(str, "QVariantMap")
    def update(self, name: str, changes: dict) -> None:
        self._mutate(lambda: self.api.update_instance(name, **changes))
