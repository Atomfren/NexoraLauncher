"""Глобальные настройки: игра и память, Java, язык, вход Microsoft, обновления лаунчера."""

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication

from frontend.quick import fmt
from frontend.quick.bridge import Shell
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.i18n import t


class Settings(QObject):
    changed = pyqtSignal()
    javaChanged = pyqtSignal()
    updateChanged = pyqtSignal()

    def __init__(self, api: ApiClient, shell: Shell, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self._values: dict = {}
        self._system: dict = {}
        self._javas: list[dict] = []
        self._java_loading = False
        self._update: dict = {}
        self._update_state = "idle"  # idle | checking | ready | downloading | error
        self.load()

    @pyqtProperty("QVariantMap", notify=changed)
    def values(self) -> dict:
        return self._values

    @pyqtProperty("QVariantMap", notify=changed)
    def system(self) -> dict:
        return self._system

    @pyqtProperty(int, notify=changed)
    def totalMemoryMb(self) -> int:
        return int(self._system.get("total_memory_mb") or 8192)

    @pyqtProperty(int, notify=changed)
    def recommendedMemoryMb(self) -> int:
        """Половина ОЗУ, но не больше 8 ГБ и не меньше 2 ГБ."""
        return max(2048, min(8192, (self.totalMemoryMb // 2) // 512 * 512))

    @pyqtSlot()
    def load(self) -> None:
        def done(data) -> None:
            self._values, self._system = data
            self.changed.emit()

        run_async(lambda: (self.api.settings(), self.api.system_info()), done,
                  lambda msg: logger.warning(f"Настройки не загружены: {msg}"), owner=self)

    @pyqtSlot("QVariantMap")
    def save(self, changes: dict) -> None:
        changes = {k: v for k, v in changes.items() if self._values.get(k) != v}
        if not changes:
            return
        self._values = dict(self._values, **changes)
        self.changed.emit()

        def done(values: dict) -> None:
            self._values = values
            self.changed.emit()
            if "language" in changes:
                self.shell.toast(t("q.restart_for_language"), "info")

        def failed(message: str) -> None:
            self.shell.toast(message, "err")
            self.load()

        run_async(lambda: self.api.update_settings(**changes), done, failed, owner=self)

    @pyqtSlot(int, result=str)
    def memoryText(self, mb: int) -> str:
        return fmt.memory(mb)

    # --- Java --------------------------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=javaChanged)
    def javas(self) -> list[dict]:
        return self._javas

    @pyqtProperty(bool, notify=javaChanged)
    def javaLoading(self) -> bool:
        return self._java_loading

    @pyqtSlot()
    def detectJava(self) -> None:
        if self._java_loading:
            return
        self._java_loading = True
        self.javaChanged.emit()

        def done(items: list[dict]) -> None:
            self._javas = [{"path": j["path"], "version": j.get("version", ""), "major": j.get("major", 0)}
                           for j in items]
            self._java_loading = False
            self.javaChanged.emit()

        def failed(message: str) -> None:
            self._java_loading = False
            self.javaChanged.emit()
            self.shell.toast(message, "err")

        run_async(self.api.detect_java, done, failed, owner=self)

    # --- Обновления лаунчера ------------------------------------------------------------------------
    @pyqtProperty("QVariantMap", notify=updateChanged)
    def update(self) -> dict:
        return dict(self._update, state=self._update_state)

    @pyqtSlot()
    def checkUpdate(self) -> None:
        self._update_state = "checking"
        self.updateChanged.emit()

        def done(info: dict) -> None:
            self._update = info
            self._update_state = "ready"
            self.updateChanged.emit()

        def failed(message: str) -> None:
            self._update = {"error": message}
            self._update_state = "error"
            self.updateChanged.emit()

        run_async(self.api.check_update, done, failed, owner=self)

    @pyqtSlot()
    def installUpdate(self) -> None:
        """Скачивает релиз и перезапускает лаунчер новой версией."""
        self._update_state = "downloading"
        self.updateChanged.emit()

        def failed(message: str) -> None:
            self._update_state = "ready"
            self.updateChanged.emit()
            self.shell.toast(message, "err")

        def downloaded(task: dict) -> None:
            path = (task.get("result") or {}).get("path", "")

            def applied(result: dict) -> None:
                if (result or {}).get("restart"):
                    QApplication.quit()

            run_async(lambda: self.api.apply_update(path), applied, failed, owner=self)

        run_async(self.api.download_update,
                  lambda task: self.shell.tracker.track(task, downloaded, failed), failed, owner=self)
