"""Данные выбранной сборки для вкладок: миры, скриншоты, моды, ресурсы, вердикт Доктора."""

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication

from frontend.quick import art, fmt
from frontend.quick.bridge import Shell
from frontend.quick.images import file_ref, remote_ref
from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.i18n import t

_IMAGE_EXT = (".png", ".jpg", ".jpeg")
_MAX_SHOTS = 60
CONTENT_TYPES = ("mod", "resourcepack", "shader")


def local_path(value) -> str:
    """Путь из того, что пришло из QML: QUrl, «file:///…» или обычный путь."""
    if isinstance(value, QUrl):
        return value.toLocalFile()
    text = str(value)
    return QUrl(text).toLocalFile() if text.startswith("file:") else text


def list_screenshots(game_dir: str, limit: int = _MAX_SHOTS) -> list[dict[str, Any]]:
    if not game_dir:  # пустой путь означал бы папку screenshots в текущем каталоге
        return []
    folder = Path(game_dir) / "screenshots"
    try:
        files = [p for p in folder.iterdir() if p.suffix.lower() in _IMAGE_EXT]
    except OSError:
        return []
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"url": file_ref(str(p)), "path": str(p), "name": p.stem,
             "date": fmt.when(p.stat().st_mtime)} for p in files[:limit]]


def world_row(world: dict) -> dict[str, Any]:
    icon = Path(world["path"]) / "icon.png"
    seed = art.seed_of(world["name"])
    return {"name": world["name"], "size": fmt.size(world.get("size", 0)),
            "lastPlayed": fmt.when(world.get("last_played")), "path": world["path"],
            "icon": file_ref(str(icon)) if world.get("has_icon")
            else f"image://nx/scene/{art.palette_for(world['name'])}/{seed}/9/6"}


def content_row(item: dict, update: dict | None = None) -> dict[str, Any]:
    seed = art.seed_of(item.get("project_id") or item["filename"])
    icon = item.get("icon_url", "")
    version = item.get("version_number", "")
    if not version:
        stem = Path(item["filename"].removesuffix(".disabled")).stem
        version = stem.rsplit("-", 1)[-1] if "-" in stem else ""
    return {
        "filename": item["filename"], "name": item.get("name", item["filename"]), "enabled": item["enabled"],
        "version": version, "source": "Modrinth" if item.get("project_id") else t("q.source_local"),
        "size": fmt.size(item.get("size", 0)),
        "icon": remote_ref(icon) if icon
        else f"image://nx/mod/{seed}/{(seed * 37) % 360}",
        "newVersion": (update or {}).get("new_version", ""), "versionId": (update or {}).get("version_id", ""),
    }


def verdict_from(report: dict) -> dict[str, Any]:
    """Короткий вердикт Доктора для карточки «Обзор»: первая проблема и её исправление."""
    issues = report.get("issues") or []
    if not issues:
        return {"state": "ok", "title": t("q.doctor_ok"), "details": t("q.doctor_ok_details"), "count": 0,
                "issues": []}
    first = issues[0]
    fix = (first.get("fixes") or [{}])[0]
    return {
        "state": "error" if first.get("severity") == "error" else "warning",
        "title": first.get("title", ""), "details": first.get("details", ""), "count": len(issues),
        "fixAction": fix.get("action", ""), "fixLabel": fix.get("label", ""), "fixParams": fix.get("params", {}),
        "issues": [{"title": i.get("title", ""), "details": i.get("details", ""), "severity": i.get("severity"),
                    "fixes": i.get("fixes") or []} for i in issues],
    }


class BuildDetails(QObject):
    changed = pyqtSignal()
    contentChanged = pyqtSignal()
    verdictChanged = pyqtSignal()
    extrasChanged = pyqtSignal()

    def __init__(self, api: ApiClient, shell: Shell, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self.library = library
        self._name = ""
        self._gen = 0
        self._worlds: list[dict] = []
        self._shots: list[dict] = []
        self._content: dict[str, list[dict]] = {k: [] for k in CONTENT_TYPES}
        self._updates: dict[str, dict] = {}
        self._checking = False
        self._loading = False
        self._verdict: dict = {"state": "loading"}
        self._server: dict = {}
        self._settings: dict = {}
        self._turbo: dict = {}
        self._snapshots: list[dict] = []
        library.selectedChanged.connect(self._on_selected)
        library.gameExited.connect(self._on_game_exited)
        library.contentInstalled.connect(lambda name: self.reloadContent() if name == self._name else None)
        self._on_selected()

    # --- Свойства -------------------------------------------------------------------------------
    @pyqtProperty(str, notify=changed)
    def name(self) -> str:
        return self._name

    @pyqtProperty(bool, notify=changed)
    def loading(self) -> bool:
        return self._loading

    @pyqtProperty("QVariantList", notify=changed)
    def worlds(self) -> list[dict]:
        return self._worlds

    @pyqtProperty("QVariantList", notify=changed)
    def screenshots(self) -> list[dict]:
        return self._shots

    @pyqtProperty("QVariantList", notify=contentChanged)
    def mods(self) -> list[dict]:
        return self._content["mod"]

    @pyqtProperty("QVariantList", notify=contentChanged)
    def resourcepacks(self) -> list[dict]:
        return self._content["resourcepack"]

    @pyqtProperty("QVariantList", notify=contentChanged)
    def shaders(self) -> list[dict]:
        return self._content["shader"]

    @pyqtProperty(int, notify=contentChanged)
    def updatesCount(self) -> int:
        return len(self._updates)

    @pyqtProperty(bool, notify=contentChanged)
    def checkingUpdates(self) -> bool:
        return self._checking

    @pyqtProperty("QVariantMap", notify=verdictChanged)
    def verdict(self) -> dict:
        return self._verdict

    @pyqtProperty("QVariantMap", notify=changed)
    def server(self) -> dict:
        return self._server

    @pyqtProperty("QVariantMap", notify=changed)
    def globalSettings(self) -> dict:
        return self._settings

    @pyqtProperty("QVariantMap", notify=extrasChanged)
    def turbo(self) -> dict:
        return self._turbo

    @pyqtProperty("QVariantList", notify=extrasChanged)
    def snapshots(self) -> list[dict]:
        return self._snapshots

    # --- Загрузка -------------------------------------------------------------------------------
    def _on_selected(self) -> None:
        self._name = self.library.selected
        self._gen += 1
        self._worlds, self._shots, self._updates = [], [], {}
        self._content = {k: [] for k in CONTENT_TYPES}
        self._verdict = {"state": "loading"}
        self._turbo, self._snapshots = {}, []
        self.extrasChanged.emit()
        self.changed.emit()
        self.contentChanged.emit()
        self.verdictChanged.emit()
        if self._name:
            self.reload()

    def _on_game_exited(self, name: str, _code: int) -> None:
        if name == self._name:
            self.reload()

    def _guard(self, handler):
        gen = self._gen

        def wrapped(result):
            if gen == self._gen:
                handler(result)

        return wrapped

    @pyqtSlot()
    def reload(self) -> None:
        name = self._name
        if not name:
            return
        self._loading = True
        self.changed.emit()

        def fetch_main():
            worlds = [world_row(w) for w in self.api.worlds(name)]
            # Папку берём из API: при запуске список сборок может ещё не загрузиться
            shots = list_screenshots(self.api.instance(name).get("game_dir", ""))
            hosted = self.api.hosted_servers()
            settings = self.api.settings()
            return worlds, shots, hosted, settings

        def main_done(data) -> None:
            worlds, shots, hosted, settings = data
            self._worlds, self._shots, self._settings = worlds, shots, settings
            server = hosted[0] if hosted else None
            self._server = {"name": server["name"], "state": server.get("state", "stopped"),
                            "address": server.get("public_address", "")} if server else {}
            self._loading = False
            self.changed.emit()

        def main_failed(message: str) -> None:
            self._loading = False
            self.changed.emit()
            logger.warning(f"Данные сборки не загружены: {message}")

        run_async(fetch_main, self._guard(main_done), main_failed, owner=self)
        self.reloadContent()
        self.reloadVerdict()

    @pyqtSlot()
    def reloadContent(self) -> None:
        name = self._name

        def fetch():
            return {k: self.api.installed_content(name, k) for k in CONTENT_TYPES}

        def done(data: dict) -> None:
            self._content = {k: [content_row(i, self._updates.get(i["filename"])) for i in v]
                             for k, v in data.items()}
            self.contentChanged.emit()

        run_async(fetch, self._guard(done), lambda msg: logger.warning(f"Контент не загружен: {msg}"), owner=self)

    @pyqtSlot()
    def reloadVerdict(self) -> None:
        name = self._name

        def done(report: dict) -> None:
            self._verdict = verdict_from(report)
            self.verdictChanged.emit()

        def failed(message: str) -> None:
            self._verdict = {"state": "unknown", "title": t("q.doctor_failed"), "details": message, "count": 0}
            self.verdictChanged.emit()

        run_async(lambda: self.api.diagnose(name), self._guard(done), self._guard(failed), owner=self)

    # --- Действия -------------------------------------------------------------------------------
    @pyqtSlot(str, str, bool)
    def setEnabled(self, content_type: str, filename: str, enabled: bool) -> None:
        name = self._name
        run_async(lambda: self.api.toggle_content(name, content_type, filename, enabled),
                  self._guard(lambda _r: self.reloadContent()),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, "QVariantList", bool)
    def setManyEnabled(self, content_type: str, filenames: list, enabled: bool) -> None:
        name = self._name

        def work():
            for filename in filenames:
                if filename.endswith(".disabled") != (not enabled):
                    self.api.toggle_content(name, content_type, filename, enabled)

        run_async(work, self._guard(lambda _r: self.reloadContent()),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, "QVariantList")
    def removeContent(self, content_type: str, filenames: list) -> None:
        name = self._name

        def work():
            for filename in filenames:
                self.api.remove_content(name, content_type, filename)

        def done(_r) -> None:
            self.shell.toast(fmt.count(len(filenames), "q.removed_files"))
            self.reloadContent()

        run_async(work, self._guard(done), lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, "QVariantList")
    def addLocalContent(self, content_type: str, urls: list) -> None:
        name = self._name
        paths = [local_path(u) for u in urls]

        def work():
            for path in paths:
                self.api.add_local_content(name, content_type, path)

        def done(_r) -> None:
            self.shell.toast(fmt.count(len(paths), "q.added_files"))
            self.reloadContent()

        run_async(work, self._guard(done), lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot()
    def checkUpdates(self) -> None:
        name = self._name
        self._checking = True
        self.contentChanged.emit()

        def done(updates: list[dict]) -> None:
            self._checking = False
            self._updates = {u["filename"]: u for u in updates}
            self._content["mod"] = [dict(row, newVersion=self._updates.get(row["filename"], {}).get("new_version", ""))
                                    for row in self._content["mod"]]
            self.contentChanged.emit()
            if not updates:
                self.shell.toast(t("q.mods_up_to_date"), "info")

        def failed(message: str) -> None:
            self._checking = False
            self.contentChanged.emit()
            self.shell.toast(message, "err")

        run_async(lambda: self.api.mod_updates(name), self._guard(done), self._guard(failed), owner=self)

    @pyqtSlot()
    def applyUpdates(self) -> None:
        name = self._name
        ids = [u["version_id"] for u in self._updates.values()]
        if not ids:
            return

        def done(_task) -> None:
            self._updates = {}
            self.shell.toast(t("q.mods_updated"))
            self.reloadContent()

        def started(result) -> None:
            if isinstance(result, dict) and "id" in result and "status" in result:
                self.shell.tracker.track(result, self._guard(done), lambda msg: self.shell.toast(msg, "err"))
            else:
                done(result)

        run_async(lambda: self.api.apply_mod_updates(name, ids), started,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, "QVariantMap")
    def applyFix(self, action: str, params: dict) -> None:
        name = self._name

        def done(result) -> None:
            message = (result or {}).get("message") if isinstance(result, dict) else ""
            self.shell.toast(message or t("q.fixed"))
            self.library.refresh()
            self.reloadContent()
            self.reloadVerdict()

        def started(result) -> None:
            if isinstance(result, dict) and "id" in result and "status" in result:
                self.shell.tracker.track(result, lambda task: done(task.get("result")),
                                         lambda msg: self.shell.toast(msg, "err"))
            else:
                done(result)

        run_async(lambda: self.api.apply_fix(name, action, params), started,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- «Турбо» ---------------------------------------------------------------------------------
    @pyqtSlot()
    def loadTurbo(self) -> None:
        name = self._name
        self._turbo = {"state": "loading"}
        self.extrasChanged.emit()

        def done(plan: dict) -> None:
            self._turbo = {"state": "ready", "mods": plan.get("mods", []),
                           "memory": fmt.memory(plan.get("max_memory", 0)), "jvm": plan.get("jvm_args", "")}
            self.extrasChanged.emit()

        def failed(message: str) -> None:
            self._turbo = {"state": "error", "error": message}
            self.extrasChanged.emit()

        run_async(lambda: self.api.turbo_plan(name), self._guard(done), self._guard(failed), owner=self)

    @pyqtSlot(bool)
    def applyTurbo(self, tune_jvm: bool) -> None:
        name = self._name

        def finished(task: dict) -> None:
            result = task.get("result") or {}
            failed, installed = result.get("failed") or [], result.get("installed") or []
            if failed:
                self.shell.toast(t("q.turbo_partial", mods=", ".join(failed)), "err")
            elif installed:
                self.shell.toast(t("q.turbo_done_mods", n=len(installed)))
            else:
                self.shell.toast(t("q.turbo_done"))
            self.library.refresh()
            self.reloadContent()
            self.loadSnapshots()

        run_async(lambda: self.api.apply_turbo(name, tune_jvm),
                  lambda task: self.shell.tracker.track(task, finished, lambda msg: self.shell.toast(msg, "err")),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- Точки восстановления -----------------------------------------------------------------------
    @pyqtSlot()
    def loadSnapshots(self) -> None:
        name = self._name

        def done(items: list[dict]) -> None:
            self._snapshots = [{"id": s["id"], "label": s.get("label") or t("q.snapshot_manual"),
                                "auto": s.get("auto", False),
                                "date": fmt.when(s.get("created_at")), "size": fmt.size(s.get("size", 0)),
                                "mods": fmt.count(int(s.get("mods") or 0), "q.mods")} for s in items]
            self.extrasChanged.emit()

        run_async(lambda: self.api.snapshots(name), self._guard(done), lambda msg: logger.warning(msg), owner=self)

    @pyqtSlot(str)
    def createSnapshot(self, label: str) -> None:
        name = self._name

        def done(_r) -> None:
            self.shell.toast(t("q.snapshot_created"))
            self.loadSnapshots()

        run_async(lambda: self.api.create_snapshot(name, label.strip()), self._guard(done),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str)
    def restoreSnapshot(self, snap_id: str) -> None:
        name = self._name

        def done(_r) -> None:
            self.shell.toast(t("q.snapshot_restored"))
            self.library.refresh()
            self.reload()
            self.loadSnapshots()

        run_async(lambda: self.api.restore_snapshot(name, snap_id), self._guard(done),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str)
    def deleteSnapshot(self, snap_id: str) -> None:
        name = self._name
        run_async(lambda: self.api.delete_snapshot(name, snap_id), self._guard(lambda _r: self.loadSnapshots()),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot()
    def shareLog(self) -> None:
        """Публикует последний лог на mclo.gs (токены и IP вычищаются backend) и копирует ссылку."""
        name = self._name

        def done(result: dict) -> None:
            url = (result or {}).get("url", "")
            if url:
                QGuiApplication.clipboard().setText(url)
                self.shell.toast(t("q.log_shared"))

        run_async(lambda: self.api.share_log(name), done, lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str)
    def deleteWorld(self, world: str) -> None:
        name = self._name

        def done(_r) -> None:
            self.shell.toast(t("q.world_deleted", name=world))
            self.reload()

        run_async(lambda: self.api.delete_world(name, world), self._guard(done),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, str)
    def exportWorld(self, world: str, url: str) -> None:
        """Мир → .zip (например, чтобы отправить другу или перенести в другую сборку)."""
        name, path = self._name, local_path(url)
        if not path.lower().endswith(".zip"):
            path += ".zip"
        run_async(lambda: self.api.export_world(name, world, path),
                  lambda r: self.shell.toast(t("q.world_exported", path=(r or {}).get("path", path))),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str)
    def importWorld(self, url: str) -> None:
        name = self._name

        def done(result: dict) -> None:
            self.shell.toast(t("q.world_imported", name=(result or {}).get("name", "")))
            self.reload()

        run_async(lambda: self.api.import_world(name, local_path(url)), self._guard(done),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)
