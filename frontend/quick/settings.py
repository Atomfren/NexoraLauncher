"""Глобальные настройки: игра и память, Java, язык, вход Microsoft, обновления лаунчера."""

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from frontend.quick import fmt
from frontend.quick.bridge import Shell
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.i18n import t

_FIRST_CHECK_MS = 4000          # даём окну открыться, прежде чем ходить в сеть
_RETRY_MS = 15 * 60 * 1000      # запасной повтор, если система не сообщает о состоянии сети


class Settings(QObject):
    changed = Signal()
    javaChanged = Signal()
    updateChanged = Signal()
    gpuChanged = Signal()
    languagesChanged = Signal()
    updateOffered = Signal(str)  # найдена новая версия: предлагаем обновиться

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
        self._gpu: dict = {}
        self._gpu_loading = False
        self._languages: dict = {}
        self._languages_loading = False
        self._language_busy = ""     # код языка, который сейчас скачивается
        self._update_seen = False    # обновление уже найдено — больше не опрашиваем
        self._retry: QTimer | None = None
        self._network = None
        self.load()

    @Property("QVariantMap", notify=changed)
    def values(self) -> dict:
        return self._values

    @Property("QVariantMap", notify=changed)
    def system(self) -> dict:
        return self._system

    @Property(int, notify=changed)
    def totalMemoryMb(self) -> int:
        return int(self._system.get("total_memory_mb") or 8192)

    @Property(int, notify=changed)
    def recommendedMemoryMb(self) -> int:
        """Половина ОЗУ, но не больше 8 ГБ и не меньше 2 ГБ."""
        return max(2048, min(8192, (self.totalMemoryMb // 2) // 512 * 512))

    # --- Видеокарта ---------------------------------------------------------------------------
    @Property("QVariantMap", notify=gpuChanged)
    def gpu(self) -> dict:
        """Видеокарты и выбранный режим. Пусто, пока не загружено."""
        return dict(self._gpu, loading=self._gpu_loading)

    @Slot()
    def loadGpu(self) -> None:
        """Спрашивает систему о видеокартах. Делается по открытию раздела, а не при запуске:
        опрос идёт через системную службу и занимает заметное время."""
        if self._gpu or self._gpu_loading:
            return
        self._gpu_loading = True
        self.gpuChanged.emit()

        def done(info: dict) -> None:
            self._gpu, self._gpu_loading = info, False
            self.gpuChanged.emit()

        def failed(message: str) -> None:
            self._gpu_loading = False
            self.gpuChanged.emit()
            logger.warning(f"Видеокарты не определены: {message}")

        run_async(self.api.gpu_info, done, failed, owner=self)

    @Slot()
    def load(self) -> None:
        def done(data) -> None:
            self._values, self._system, self._languages = data
            self.changed.emit()
            self.languagesChanged.emit()

        # Языки берём без обращения к сайту: список установленных нужен сразу, для выбора в «Общих»
        run_async(lambda: (self.api.settings(), self.api.system_info(), self.api.languages(online=False)),
                  done, lambda msg: logger.warning(f"Настройки не загружены: {msg}"), owner=self)

    @Slot("QVariantMap")
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

    @Slot(int, result=str)
    def memoryText(self, mb: int) -> str:
        return fmt.memory(mb)

    # --- Java --------------------------------------------------------------------------------------
    @Property("QVariantList", notify=javaChanged)
    def javas(self) -> list[dict]:
        return self._javas

    @Property(bool, notify=javaChanged)
    def javaLoading(self) -> bool:
        return self._java_loading

    @Slot()
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
    @Property("QVariantMap", notify=updateChanged)
    def update(self) -> dict:
        return dict(self._update, state=self._update_state)

    # --- Языки --------------------------------------------------------------------------------
    @Property("QVariantMap", notify=languagesChanged)
    def languages(self) -> dict:
        """Списки языков и состояние: loading, error, busy (какой язык сейчас ставится)."""
        return dict(self._languages, loading=self._languages_loading, busy=self._language_busy)

    @Slot()
    @Slot(bool)
    def loadLanguages(self, online: bool = True) -> None:
        """Спрашивает список языков. ``online=False`` — только установленные, без похода на сайт."""
        if self._languages_loading:
            return
        self._languages_loading = online
        self.languagesChanged.emit()

        def done(data: dict) -> None:
            self._languages, self._languages_loading = data, False
            self.languagesChanged.emit()

        def failed(message: str) -> None:
            self._languages_loading = False
            self._languages = dict(self._languages, error=message)
            self.languagesChanged.emit()

        run_async(lambda: self.api.languages(online), done, failed, owner=self)

    @Slot(str)
    def installLanguage(self, code: str) -> None:
        """Скачивает язык и сразу переключает на него интерфейс."""
        self._language_busy = code
        self.languagesChanged.emit()

        def finished(message: str = "") -> None:
            self._language_busy = ""
            self.languagesChanged.emit()
            if message:
                self.shell.toast(message, "err")

        def installed(task: dict) -> None:
            result = task.get("result") or {}
            finished()
            self.shell.toast(t("q.lang_installed", name=result.get("name", code)), "ok")
            self.save({"language": code})
            self.loadLanguages()

        run_async(lambda: self.api.install_language(code),
                  lambda task: self.shell.tracker.track(task, installed, finished), finished, owner=self)

    @Slot(str)
    def removeLanguage(self, code: str) -> None:
        def done(_result) -> None:
            self.loadLanguages()
            self.load()  # язык интерфейса мог вернуться к русскому

        run_async(lambda: self.api.remove_language(code), done,
                  lambda message: self.shell.toast(message, "err"), owner=self)

    # --- Проверка обновлений сама по себе -------------------------------------------------------
    def start_auto_check(self) -> None:
        """Проверяет обновления при запуске и каждый раз, когда появляется интернет.

        Лаунчер часто открывают раньше, чем поднимется сеть (Wi-Fi после сна, мобильный модем),
        и единственная проверка при старте в такой момент просто не удаётся. Поэтому слушаем
        состояние сети у системы и, если проверка не прошла, повторяем её при подключении.
        """
        QTimer.singleShot(_FIRST_CHECK_MS, self._auto_check)
        self._retry = QTimer(self)
        self._retry.setInterval(_RETRY_MS)
        self._retry.timeout.connect(self._auto_check)
        self._watch_network()

    def _watch_network(self) -> None:
        try:
            from PySide6.QtNetwork import QNetworkInformation
        except ImportError:  # сборка без QtNetwork — останется повтор по таймеру
            return
        if not QNetworkInformation.loadDefaultBackend():
            logger.debug("Состояние сети системе недоступно — обновления проверяются по таймеру")
            return
        info = QNetworkInformation.instance()
        if info is None:
            return
        self._network = info

        def on_reachability(value) -> None:
            if value == QNetworkInformation.Reachability.Online and not self._update_seen:
                logger.info("Появился интернет — проверяем обновления")
                self._auto_check()

        info.reachabilityChanged.connect(on_reachability)

    def _auto_check(self) -> None:
        """Тихая проверка: пользователь узнаёт о ней, только если обновление действительно есть."""
        if self._update_seen or not self._values.get("check_updates", True):
            self._stop_retry()
            return

        def done(info: dict) -> None:
            self._update_seen = True
            self._stop_retry()
            self._update, self._update_state = info, "ready"
            self.updateChanged.emit()
            if info.get("available"):
                logger.info(f"Доступна версия {info.get('latest')}")
                self.updateOffered.emit(str(info.get("latest", "")))

        def failed(message: str) -> None:
            # Нет сети или канал ещё не настроен — молчим и ждём следующего повода
            logger.debug(f"Обновления не проверены: {message}")
            if self._retry is not None and not self._retry.isActive():
                self._retry.start()

        run_async(self.api.check_update, done, failed, owner=self)

    def _stop_retry(self) -> None:
        if self._retry is not None and self._retry.isActive():
            self._retry.stop()

    @Slot()
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

    @Slot()
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
