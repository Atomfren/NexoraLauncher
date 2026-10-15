"""Каталог Modrinth: поиск, фильтры, установка в сборку (или свой сервер для плагинов)."""

from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from frontend.quick import art, fmt
from frontend.quick.bridge import Shell
from frontend.quick.images import remote_ref
from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.i18n import t

PAGE = 30
# Тип каталога → тип контента сборки (None — модпак ставится новой сборкой, plugin — на свой сервер)
CONTENT_TYPE = {"mod": "mod", "resourcepack": "resourcepack", "shader": "shader", "modpack": None, "plugin": None}
CATEGORIES = {
    "mod": ("optimization", "utility", "library", "technology", "adventure", "magic", "storage", "worldgen",
            "decoration", "equipment", "mobs", "transportation", "food"),
    "modpack": ("optimization", "adventure", "technology", "magic", "challenging", "multiplayer", "quests",
                "lightweight", "kitchen-sink"),
    "resourcepack": ("simplistic", "realistic", "decoration", "themed", "combat", "tweaks", "utility", "audio"),
    "shader": ("realistic", "semi-realistic", "cartoon", "fantasy", "vanilla-like", "potato", "low", "high"),
    "plugin": ("utility", "management", "economy", "minigame", "adventure", "social", "transportation"),
}


def compact(n: int) -> str:
    """48 200 000 → «48,2 М», 12 400 → «12,4 К»."""
    if n < 1000:
        return str(n)
    value, key = (n / 1_000_000, "q.compact_m") if n >= 1_000_000 else (n / 1000, "q.compact_k")
    text = f"{value:.0f}" if value >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")
    return t(key, n=text.replace(".", ","))


def project_row(hit: dict, state: str = "none") -> dict[str, Any]:
    seed = art.seed_of(hit["project_id"])
    icon = hit.get("icon_url") or ""
    return {
        "id": hit["project_id"], "slug": hit.get("slug", ""), "title": hit.get("title", ""),
        "author": hit.get("author", ""), "description": hit.get("description", ""),
        "downloads": compact(int(hit.get("downloads") or 0)),
        "categories": hit.get("categories") or [], "versions": (hit.get("game_versions") or [])[-6:][::-1],
        "loaders": hit.get("loaders") or [],
        "icon": remote_ref(icon) if icon else f"image://nx/mod/{seed}/{(seed * 37) % 360}",
        "state": state, "progress": 0.0,
    }


class Catalog(QObject):
    changed = pyqtSignal()
    resultsChanged = pyqtSignal()
    projectChanged = pyqtSignal()

    def __init__(self, api: ApiClient, shell: Shell, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self.library = library
        self._type = "mod"
        self._query = ""
        self._version = ""
        self._loader = ""
        self._category = ""
        self._sort = "relevance"
        self._target = ""
        self._servers: list[dict] = []
        self._results: list[dict] = []
        self._total = 0
        self._loading = False
        self._error = ""
        self._gen = 0
        self._installed: set[str] = set()
        self._busy: dict[str, str] = {}  # project_id → task id
        self._progress: dict[str, float] = {}
        self._project: dict = {}
        self._versions: list[dict] = []
        self._search_timer = QTimer(self, singleShot=True, interval=300)
        self._search_timer.timeout.connect(self.search)
        shell.tracker.tasks_changed.connect(self._on_tasks)
        library.totalChanged.connect(self.changed)
        self._started = False

    # --- Свойства -------------------------------------------------------------------------------
    @pyqtProperty(str, notify=changed)
    def type(self) -> str:
        return self._type

    @pyqtProperty(str, notify=changed)
    def query(self) -> str:
        return self._query

    @pyqtProperty(str, notify=changed)
    def gameVersion(self) -> str:
        return self._version

    @pyqtProperty(str, notify=changed)
    def loader(self) -> str:
        return self._loader

    @pyqtProperty(str, notify=changed)
    def category(self) -> str:
        return self._category

    @pyqtProperty(str, notify=changed)
    def sort(self) -> str:
        return self._sort

    @pyqtProperty(str, notify=changed)
    def target(self) -> str:
        return self._target

    @pyqtProperty("QVariantList", notify=changed)
    def targets(self) -> list[dict]:
        """Куда ставить: сборки (моды, ресурсы) или свои серверы (плагины). У модпака цели нет."""
        if self._type == "plugin":
            return [{"value": s["name"], "label": s["name"], "loader": s.get("core", "paper")} for s in self._servers]
        if self._type == "modpack":
            return []
        return [{"value": e["name"], "label": e["name"], "loader": e["loader"]} for e in self.library.entries()]

    @pyqtProperty("QVariantList", notify=changed)
    def categories(self) -> list[dict]:
        return [{"value": c, "label": t(f"q.cat_{c.replace('-', '_')}")} for c in CATEGORIES[self._type]]

    @pyqtProperty("QVariantList", notify=resultsChanged)
    def results(self) -> list[dict]:
        return self._results

    @pyqtProperty(int, notify=resultsChanged)
    def total(self) -> int:
        return self._total

    @pyqtProperty(bool, notify=resultsChanged)
    def loading(self) -> bool:
        return self._loading

    @pyqtProperty(str, notify=resultsChanged)
    def error(self) -> str:
        return self._error

    @pyqtProperty(bool, notify=resultsChanged)
    def hasMore(self) -> bool:
        return len(self._results) < self._total

    @pyqtProperty("QVariantMap", notify=projectChanged)
    def project(self) -> dict:
        return self._project

    @pyqtProperty("QVariantList", notify=projectChanged)
    def projectVersions(self) -> list[dict]:
        return self._versions

    # --- Фильтры --------------------------------------------------------------------------------
    @pyqtSlot()
    def start(self) -> None:
        """Первое открытие раздела: цель — выбранная сборка, фильтры — её версия и загрузчик."""
        if self._started:
            return
        self._started = True
        self._follow_target(self.library.selected)
        self._load_servers()
        self.search()

    def _follow_target(self, name: str) -> None:
        entry = next((e for e in self.library.entries() if e["name"] == name), None)
        self._target = name if entry else ""
        if entry and self._type in ("mod", "resourcepack", "shader"):
            self._version = entry["version"]
            self._loader = entry["loader"] if self._type == "mod" and entry["loader"] != "vanilla" else ""
        self.changed.emit()
        self._refresh_installed()

    def _load_servers(self) -> None:
        def done(servers: list[dict]) -> None:
            self._servers = servers
            if self._type == "plugin" and not self._target and servers:
                self._target = servers[0]["name"]
            self.changed.emit()

        run_async(self.api.hosted_servers, done, lambda msg: logger.warning(msg), owner=self)

    @pyqtSlot(str)
    def setType(self, value: str) -> None:
        if value == self._type or value not in CONTENT_TYPE:
            return
        self._type = value
        self._category = ""
        if value == "plugin":
            self._target = self._servers[0]["name"] if self._servers else ""
            self._loader = ""
            self._version = ""
            self.changed.emit()
            self._refresh_installed()
        elif value == "modpack":
            self._target, self._loader, self._version = "", "", ""
            self.changed.emit()
        else:
            self._follow_target(self.library.selected if self._target not in {e["name"] for e in self.library.entries()}
                                else self._target)
        self.search()

    @pyqtSlot(str)
    def setQuery(self, value: str) -> None:
        self._query = value.strip()
        self._search_timer.start()

    @pyqtSlot(str, str)
    def setFilter(self, key: str, value: str) -> None:
        if key == "version":
            self._version = value
        elif key == "loader":
            self._loader = value
        elif key == "category":
            self._category = "" if value == self._category else value
        elif key == "sort":
            self._sort = value
        elif key == "target":
            if self._type == "plugin":
                self._target = value
                self._refresh_installed()
            else:
                self._follow_target(value)
        self.changed.emit()
        self.search()

    # --- Поиск ----------------------------------------------------------------------------------
    @pyqtSlot()
    def search(self) -> None:
        self._load(0)

    @pyqtSlot()
    def loadMore(self) -> None:
        if not self._loading and self.hasMore:
            self._load(len(self._results))

    def _load(self, offset: int) -> None:
        self._gen += 1
        gen = self._gen
        self._loading = True
        self._error = ""
        if offset == 0:
            self._results = []
        self.resultsChanged.emit()
        loader = self._loader or None
        if self._type == "plugin":
            server = next((s for s in self._servers if s["name"] == self._target), None)
            loader = server.get("core") if server else "paper"
        params = dict(project_type=self._type, query=self._query, game_version=self._version or None, loader=loader,
                      index=self._sort if not (self._sort == "relevance" and not self._query) else "downloads",
                      limit=PAGE, offset=offset, category=self._category or None)

        def done(data: dict) -> None:
            if gen != self._gen:
                return
            rows = [project_row(h, self._state_of(h["project_id"])) for h in data.get("results", [])]
            self._results = (self._results if offset else []) + rows
            self._total = int(data.get("total") or 0)
            self._loading = False
            self.resultsChanged.emit()

        def failed(message: str) -> None:
            if gen != self._gen:
                return
            self._loading = False
            self._error = message
            self.resultsChanged.emit()

        run_async(lambda: self.api.search(**params), done, failed, owner=self)

    # --- Установка ------------------------------------------------------------------------------
    def _state_of(self, project_id: str) -> str:
        if project_id in self._busy:
            return "busy"
        return "installed" if project_id in self._installed else "none"

    def _restate(self) -> None:
        self._results = [dict(r, state=self._state_of(r["id"]), progress=self._progress.get(r["id"], 0.0))
                         for r in self._results]
        self.resultsChanged.emit()
        if self._project:
            self._project = dict(self._project, state=self._state_of(self._project["id"]),
                                 progress=self._progress.get(self._project["id"], 0.0))
            self.projectChanged.emit()

    def _refresh_installed(self) -> None:
        target, kind = self._target, self._type
        if not target or kind == "modpack":
            self._installed = set()
            self._restate()
            return

        def fetch() -> set[str]:
            if kind == "plugin":
                items = self.api.server_mods(target)
            else:
                items = self.api.installed_content(target, CONTENT_TYPE[kind])
            return {i.get("project_id") for i in items if i.get("project_id")}

        def done(ids: set[str]) -> None:
            if target == self._target:
                self._installed = ids
                self._restate()

        run_async(fetch, done, lambda msg: logger.warning(f"Установленное не загружено: {msg}"), owner=self)

    def _on_tasks(self, active: list[dict]) -> None:
        by_task = {task["id"]: float(task.get("progress") or 0) for task in active}
        changed = False
        for pid, task_id in self._busy.items():
            if task_id in by_task and by_task[task_id] != self._progress.get(pid):
                self._progress[pid] = by_task[task_id]
                changed = True
        if changed:
            self._restate()

    @pyqtSlot(str)
    def install(self, project_id: str) -> None:
        kind, target = self._type, self._target
        row = next((r for r in self._results if r["id"] == project_id), self._project)
        title = row.get("title", project_id) if row else project_id
        if kind != "modpack" and not target:
            self.shell.toast(t("q.pick_target"), "err")
            return
        if kind == "modpack":
            call = lambda: self.api.install_modpack(project_id)  # noqa: E731
        elif kind == "plugin":
            call = lambda: self.api.install_server_mod(target, project_id)  # noqa: E731
        else:
            call = lambda: self.api.install_content(target, CONTENT_TYPE[kind], project_id)  # noqa: E731
        self._busy[project_id] = ""
        self._progress[project_id] = 0.0
        self._restate()

        def finished(task: dict) -> None:
            self._busy.pop(project_id, None)
            self._progress.pop(project_id, None)
            if kind == "modpack":
                name = (task.get("result") or {}).get("name", title)
                self.shell.toast(t("q.pack_installed", name=name))
                self.library.refresh()
            else:
                self._installed.add(project_id)
                self.shell.toast(t("q.installed_into", name=title, target=target))
                self.library.contentInstalled.emit(target)
            self._restate()

        def failed(message: str) -> None:
            self._busy.pop(project_id, None)
            self._progress.pop(project_id, None)
            self._restate()
            self.shell.toast(message, "err")

        def started(task: dict) -> None:
            self._busy[project_id] = task["id"]
            self.shell.tracker.track(task, finished, failed)

        run_async(call, started, failed, owner=self)

    # --- Карточка проекта -------------------------------------------------------------------------
    @pyqtSlot(str)
    def openProject(self, project_id: str) -> None:
        row = next((r for r in self._results if r["id"] == project_id), None)
        self._project = dict(row or {"id": project_id, "title": "", "icon": ""}, gallery=[], loadingDetails=True)
        self._versions = []
        self.projectChanged.emit()
        kind, version, loader = self._type, self._version or None, self._loader or None

        def fetch():
            project = self.api.project(project_id)
            versions = self.api.project_versions(project_id, version, loader if kind == "mod" else None)
            return project, versions

        def done(data) -> None:
            project, versions = data
            if self._project.get("id") != project_id:
                return
            self._project = dict(self._project, gallery=[remote_ref(u) for u in project.get("gallery") or []],
                                 loadingDetails=False,
                                 followers=compact(int(project.get("follows") or 0)),
                                 allVersions=(project.get("game_versions") or [])[-8:][::-1],
                                 allLoaders=project.get("loaders") or [])
            self._versions = [{"id": v["id"], "number": v.get("version_number", ""), "type": v.get("version_type", ""),
                               "mc": ", ".join(v.get("game_versions", [])[-2:]),
                               "date": fmt.when(v.get("date_published", "")[:19])} for v in versions[:8]]
            self.projectChanged.emit()

        def failed(message: str) -> None:
            if self._project.get("id") == project_id:
                self._project = dict(self._project, loadingDetails=False)
                self.projectChanged.emit()
            logger.warning(f"Проект не загружен: {message}")

        run_async(fetch, done, failed, owner=self)

    @pyqtSlot()
    def closeProject(self) -> None:
        self._project = {}
        self._versions = []
        self.projectChanged.emit()
