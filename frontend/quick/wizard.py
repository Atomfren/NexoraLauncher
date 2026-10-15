"""Мастер «Новая сборка»: чистая игра, с модами, модпак из каталога, перенос из другого лаунчера."""

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from frontend.quick.bridge import Shell
from frontend.quick.build import local_path
from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.fsutil import UnsafePathError, validate_name
from shared.i18n import t

SOURCE_TITLES = {"prism": "Prism Launcher", "multimc": "MultiMC", "curseforge": "CurseForge"}


def name_error(name: str, existing: set[str]) -> str:
    """Пусто, если имя подходит; иначе — понятная причина."""
    name = name.strip()
    if not name:
        return t("q.name_required")
    if len(name) > 64:
        return t("q.name_too_long")
    try:
        validate_name(name)
    except UnsafePathError:
        return t("q.name_bad_chars")
    if name.lower() in {n.lower() for n in existing}:
        return t("q.name_taken")
    return ""


class Wizard(QObject):
    versionsChanged = pyqtSignal()
    loaderVersionsChanged = pyqtSignal()
    foreignChanged = pyqtSignal()
    packsChanged = pyqtSignal()
    # Сборка создана и начала ставиться: имя
    created = pyqtSignal(str)

    def __init__(self, api: ApiClient, shell: Shell, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self.library = library
        self._versions: list[dict] = []
        self._versions_loading = False
        self._versions_error = ""
        self._loader_versions: list[str] = []
        self._loader_loading = False
        self._foreign: list[dict] = []
        self._foreign_loading = False
        self._busy = False
        self._packs: list[dict] = []
        self._packs_loading = False
        self._packs_gen = 0

    # --- Версии Minecraft ----------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=versionsChanged)
    def versions(self) -> list[dict]:
        return self._versions

    @pyqtProperty(bool, notify=versionsChanged)
    def versionsLoading(self) -> bool:
        return self._versions_loading

    @pyqtProperty(str, notify=versionsChanged)
    def versionsError(self) -> str:
        return self._versions_error

    @pyqtProperty(bool, notify=versionsChanged)
    def busy(self) -> bool:
        return self._busy

    @pyqtSlot()
    def loadVersions(self) -> None:
        if self._versions or self._versions_loading:
            return
        self._versions_loading = True
        self._versions_error = ""
        self.versionsChanged.emit()

        def done(items: list[dict]) -> None:
            self._versions = [{"id": v["id"], "type": v.get("type", "")} for v in items]
            self._versions_loading = False
            self.versionsChanged.emit()

        def failed(message: str) -> None:
            self._versions_loading = False
            self._versions_error = message
            self.versionsChanged.emit()

        run_async(self.api.available_versions, done, failed, owner=self)

    @pyqtSlot(bool, result="QVariantList")
    def versionOptions(self, snapshots: bool) -> list[dict]:
        kinds = ("release", "snapshot") if snapshots else ("release",)
        return [{"value": v["id"], "label": v["id"]} for v in self._versions if v["type"] in kinds]

    # --- Версии загрузчика ---------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=loaderVersionsChanged)
    def loaderVersions(self) -> list[dict]:
        out = []
        for i, v in enumerate(self._loader_versions[:30]):
            label = t("q.loader_recommended", v=v) if i == 0 else v
            out.append({"value": v, "label": label})
        return out

    @pyqtProperty(bool, notify=loaderVersionsChanged)
    def loaderLoading(self) -> bool:
        return self._loader_loading

    @pyqtSlot(str, str)
    def loadLoaderVersions(self, loader: str, mc: str) -> None:
        self._loader_versions = []
        if loader == "vanilla" or not mc:
            self.loaderVersionsChanged.emit()
            return
        self._loader_loading = True
        self.loaderVersionsChanged.emit()
        key = (loader, mc)
        self._loader_key = key

        def done(items: list[str]) -> None:
            if self._loader_key == key:
                self._loader_versions = list(items)
                self._loader_loading = False
                self.loaderVersionsChanged.emit()

        def failed(message: str) -> None:
            if self._loader_key == key:
                self._loader_loading = False
                self.loaderVersionsChanged.emit()
                logger.warning(f"Версии загрузчика не загружены: {message}")

        run_async(lambda: self.api.loader_versions(loader, mc), done, failed, owner=self)

    # --- Другие лаунчеры ---------------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=foreignChanged)
    def foreign(self) -> list[dict]:
        return self._foreign

    @pyqtProperty(bool, notify=foreignChanged)
    def foreignLoading(self) -> bool:
        return self._foreign_loading

    @pyqtSlot()
    def loadForeign(self) -> None:
        if self._foreign_loading:
            return
        self._foreign_loading = True
        self.foreignChanged.emit()

        def done(items: list[dict]) -> None:
            self._foreign = [{"name": i["name"], "path": i["path"], "source": i["source"],
                              "sourceTitle": SOURCE_TITLES.get(i["source"], i["source"]),
                              "version": i.get("version", ""), "loader": i.get("mod_loader", "vanilla")}
                             for i in items]
            self._foreign_loading = False
            self.foreignChanged.emit()

        def failed(message: str) -> None:
            self._foreign_loading = False
            self.foreignChanged.emit()
            logger.warning(f"Сборки других лаунчеров не найдены: {message}")

        run_async(self.api.foreign_instances, done, failed, owner=self)

    # --- Модпаки ------------------------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=packsChanged)
    def packs(self) -> list[dict]:
        return self._packs

    @pyqtProperty(bool, notify=packsChanged)
    def packsLoading(self) -> bool:
        return self._packs_loading

    @pyqtSlot(str)
    def searchPacks(self, query: str) -> None:
        from frontend.quick.catalog import project_row
        self._packs_gen += 1
        gen = self._packs_gen
        self._packs_loading = True
        self.packsChanged.emit()

        def done(data: dict) -> None:
            if gen == self._packs_gen:
                self._packs = [project_row(h) for h in data.get("results", [])]
                self._packs_loading = False
                self.packsChanged.emit()

        def failed(message: str) -> None:
            if gen == self._packs_gen:
                self._packs_loading = False
                self.packsChanged.emit()
                self.shell.toast(message, "err")

        run_async(lambda: self.api.search("modpack", query.strip(), index="relevance" if query.strip() else "downloads",
                                          limit=20), done, failed, owner=self)

    @pyqtSlot(str, str)
    def installPack(self, project_id: str, title: str) -> None:
        def finished(task: dict) -> None:
            name = (task.get("result") or {}).get("name", title)
            self.shell.toast(t("q.pack_installed", name=name))
            self.library.refresh()
            self.library.select(name)

        run_async(lambda: self.api.install_modpack(project_id),
                  lambda task: self.shell.tracker.track(task, finished, lambda msg: self.shell.toast(msg, "err")),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)
        self.created.emit("")

    # --- Создание --------------------------------------------------------------------------------
    @pyqtSlot(str, result=str)
    def nameError(self, name: str) -> str:
        return name_error(name, {e["name"] for e in self.library.entries()})

    @pyqtSlot(str, str, str, str)
    def create(self, name: str, version: str, loader: str, loader_version: str) -> None:
        name = name.strip()
        self._set_busy(True)

        def done(_instance: dict) -> None:
            self._set_busy(False)
            self.library.select(name)
            self.library.refresh()
            self.library.install(name)
            self.created.emit(name)

        def failed(message: str) -> None:
            self._set_busy(False)
            self.shell.toast(message, "err")

        run_async(lambda: self.api.create_instance(name, version, loader, loader_version, install=False),
                  done, failed, owner=self)

    @pyqtSlot("QVariantList")
    def importForeign(self, paths: list) -> None:
        """Перенос выбранных сборок; каждая — отдельная задача в «Загрузках»."""
        for path in paths:
            self._import(str(path))
        if paths:
            self.created.emit("")

    @pyqtSlot(str)
    def importFile(self, url: str) -> None:
        """Импорт .zip / .mrpack с диска."""
        self._import(local_path(url))
        self.created.emit("")

    def _import(self, path: str) -> None:
        def finished(task: dict) -> None:
            name = (task.get("result") or {}).get("name", "")
            self.shell.toast(t("q.imported", name=name))
            self.library.refresh()
            if name:
                self.library.select(name)

        run_async(lambda: self.api.import_instance(path),
                  lambda task: self.shell.tracker.track(task, finished, lambda msg: self.shell.toast(msg, "err")),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        self.versionsChanged.emit()
