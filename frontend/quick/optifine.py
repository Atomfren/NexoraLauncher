"""OptiFine для сборки: версии с optifine.net, ожидание скачанного файла, установка.

Файл пользователь скачивает сам на официальной странице (автор запрещает распространение).
Для Fabric/Quilt/NeoForge вместо OptiFine предлагаются Sodium + Iris.
"""

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from frontend.quick.bridge import Shell
from frontend.quick.build import local_path
from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.worker import run_async
from shared.i18n import t

_WAIT_MS = 2000
ALTERNATIVE = ("sodium", "iris")


class OptiFine(QObject):
    changed = Signal()

    def __init__(self, api: ApiClient, shell: Shell, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self.library = library
        self._name = ""
        self._status: dict = {}
        self._versions: list[dict] = []
        self._selected = 0
        self._state = "idle"  # idle | loading | wait | found | installing | error
        self._found: dict = {}
        self._error = ""
        self._timer = QTimer(self, interval=_WAIT_MS)
        self._timer.timeout.connect(self._check_downloads)

    @Property("QVariantMap", notify=changed)
    def status(self) -> dict:
        return self._status

    @Property("QVariantList", notify=changed)
    def versions(self) -> list[dict]:
        return self._versions

    @Property(int, notify=changed)
    def selected(self) -> int:
        return self._selected

    @Property(str, notify=changed)
    def state(self) -> str:
        return self._state

    @Property("QVariantMap", notify=changed)
    def found(self) -> dict:
        return self._found

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Slot()
    def open(self) -> None:
        self._name = self.library.selected
        self._state = "loading"
        self._versions, self._found, self._error, self._selected = [], {}, "", 0
        self.changed.emit()
        name = self._name

        def fetch():
            status = self.api.optifine_status(name)
            versions = self.api.optifine_versions(status["mc_version"]) if status.get("supported") else []
            return status, versions

        def done(data) -> None:
            self._status, versions = data
            self._versions = [{"edition": v["edition"].replace("_", " "), "mc": v["mc_version"],
                               "date": v.get("date", ""), "filename": v["filename"], "page": v.get("page_url", ""),
                               "preview": v.get("preview", False), "forge": v.get("forge", "")} for v in versions]
            self._selected = next((i for i, v in enumerate(self._versions) if not v["preview"]), 0)
            self._state = "idle"
            self.changed.emit()
            if self._status.get("supported"):
                self._check_downloads()

        def failed(message: str) -> None:
            self._state = "error"
            self._error = message
            self.changed.emit()

        run_async(fetch, done, failed, owner=self)

    @Slot()
    def close(self) -> None:
        self._timer.stop()

    @Slot(int)
    def select(self, index: int) -> None:
        self._selected = index
        self.changed.emit()

    @Slot()
    def openDownloadPage(self) -> None:
        if not self._versions:
            self.shell.openUrl("https://optifine.net/downloads")
            return
        self.shell.openUrl(self._versions[self._selected]["page"] or "https://optifine.net/downloads")
        if self._state != "found":
            self._state = "wait"
            self.changed.emit()
        self._timer.start()

    def _check_downloads(self) -> None:
        mc = self._status.get("mc_version", "")
        wanted = self._versions[self._selected]["filename"] if self._versions else ""

        def done(items: list[dict]) -> None:
            if not items or self._state == "installing":
                return
            match = next((i for i in items if i["filename"] == wanted), items[0])
            self._found = {"path": match["path"], "filename": match["filename"]}
            self._state = "found"
            self._timer.stop()
            self.changed.emit()

        run_async(lambda: self.api.optifine_downloaded(mc), done, lambda _m: None, owner=self, background=True)

    @Slot(str)
    def installFile(self, url: str) -> None:
        """Выбрать jar вручную."""
        path = local_path(url)
        self._found = {"path": path, "filename": path.replace("\\", "/").rsplit("/", 1)[-1]}
        self.install()

    @Slot()
    def install(self) -> None:
        name, path = self._name, self._found.get("path", "")
        if not path:
            return
        self._state = "installing"
        self.changed.emit()

        def finished(_task: dict) -> None:
            self._state = "done"
            self.changed.emit()
            self.shell.toast(t("q.optifine_installed"))
            self.library.refresh()
            self.library.contentInstalled.emit(name)

        def failed(message: str) -> None:
            self._state = "found"
            self.changed.emit()
            self.shell.toast(message, "err")

        run_async(lambda: self.api.install_optifine(name, path),
                  lambda task: self.shell.tracker.track(task, finished, failed), failed, owner=self)

    @Slot()
    def remove(self) -> None:
        name = self._name

        def done(_r) -> None:
            self.shell.toast(t("q.optifine_removed"))
            self.library.refresh()
            self.open()

        run_async(lambda: self.api.remove_optifine(name), done, lambda msg: self.shell.toast(msg, "err"), owner=self)

    @Slot()
    def installAlternative(self) -> None:
        """Sodium + Iris вместо OptiFine (Fabric, Quilt, NeoForge)."""
        name = self._name

        def install_one(project: str) -> None:
            run_async(lambda: self.api.install_content(name, "mod", project),
                      lambda task: self.shell.tracker.track(
                          task, lambda _t: self.library.contentInstalled.emit(name),
                          lambda msg: self.shell.toast(msg, "err")),
                      lambda msg: self.shell.toast(msg, "err"), owner=self)

        for project in ALTERNATIVE:
            install_one(project)
        self.shell.toast(t("q.alternative_started"), "info")
