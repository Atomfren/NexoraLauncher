"""Объекты, которые QML видит как глобальные: ``I18n`` и ``Shell``.

``Shell`` — состояние оболочки: тема, ширина боковой панели, уведомления, загрузки
(фоновые задачи backend) и аккаунты.
"""

import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QSettings, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication

from frontend.quick import art, fmt
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.task_tracker import TaskTracker
from frontend.utils.worker import run_async
from shared.i18n import t
from shared.version import APP_VERSION

_RECENT_TASKS = 8
_FONT_DIR = Path(__file__).resolve().parents[2] / "resources" / "fonts"
_UI_FALLBACKS = ("Onest", "Segoe UI Variable Text", "Segoe UI", "Arial")
_MONO_FALLBACKS = ("JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New")


def load_fonts() -> tuple[str, str]:
    """Подключает шрифты из resources/fonts и выбирает семейства для интерфейса и моноширинного текста."""
    if _FONT_DIR.is_dir():
        for path in sorted(_FONT_DIR.glob("*.[ot]tf")):
            if QFontDatabase.addApplicationFont(str(path)) < 0:
                logger.warning(f"Шрифт не загружен: {path.name}")
    families = set(QFontDatabase.families())

    def pick(options: tuple[str, ...]) -> str:
        return next((f for f in options if f in families), options[-1])

    return pick(_UI_FALLBACKS), pick(_MONO_FALLBACKS)


# Где может стоять боковая панель (выбор в «Настройки → Общие»)
SIDEBAR_POSITIONS = ("left", "right", "top", "bottom")

# Подпись под ником в списке аккаунтов
_ACCOUNT_KINDS = {"microsoft": "q.account_microsoft", "nexora": "q.account_nexora"}


class I18nBridge(QObject):
    @Slot(str, result=str)
    def t(self, key: str) -> str:
        return t(key)

    @Slot(str, "QVariantMap", result=str)
    def tf(self, key: str, params: dict) -> str:
        return t(key, **params)

    @Slot(int, str, result=str)
    def count(self, n: int, base: str) -> str:
        """``I18n.count(48, "q.mods")`` → «48 модов»."""
        return fmt.count(n, base)

    @Slot(int, result=str)
    def memory(self, mb: int) -> str:
        return fmt.memory(mb)


class Shell(QObject):
    darkChanged = Signal()
    sidebarWideChanged = Signal()
    sidebarPositionChanged = Signal()
    pageChanged = Signal()
    tasksChanged = Signal()
    accountsChanged = Signal()
    skinChanged = Signal()
    toastRequested = Signal(str, str)  # текст, вид: ok | err | info
    # Просьба открыть раздел; второй аргумент — подраздел (например, вкладка сборки)
    navigateRequested = Signal(str, str)
    addAccountRequested = Signal()
    microsoftChanged = Signal()
    nexoraChanged = Signal()

    def __init__(self, api: ApiClient, dark: bool, fonts: tuple[str, str], parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self._dark = dark
        self._fonts = fonts
        self._settings = QSettings("Atomfren", "NexoraLauncher")
        self._wide = self._settings.value("quick/sidebarWide", False, type=bool)
        position = self._settings.value("quick/sidebarPosition", "left", type=str)
        self._position = position if position in SIDEBAR_POSITIONS else "left"
        self._page = "library"
        self._active: list[dict] = []
        self._recent: list[dict] = []
        self._accounts: list[dict] = []
        self._skin: dict = {}
        self._skin_for = ""
        # available=True по умолчанию: если спросить не удалось, лучше показать кнопку,
        # чем спрятать рабочий вход из-за сетевой заминки
        self._ms: dict = {"state": "idle", "available": True}
        self._nexora: dict = {"state": "idle"}
        self.tracker = TaskTracker(api, self)
        self.tracker.tasks_changed.connect(self._on_tasks)
        self.tracker.task_finished.connect(self._on_task_finished)
        self.refreshAccounts()

    # --- Тема, шрифты, навигация --------------------------------------------------------
    @Property(bool, notify=darkChanged)
    def dark(self) -> bool:
        return self._dark

    @Slot(bool)
    def setDark(self, value: bool) -> None:
        if value == self._dark:
            return
        self._dark = value
        self.darkChanged.emit()
        mode = "dark" if value else "light"
        run_async(lambda: self.api.update_settings(appearance_mode=mode), None,
                  lambda msg: logger.warning(f"Тема не сохранена: {msg}"), owner=self)

    @Property(bool, notify=sidebarWideChanged)
    def sidebarWide(self) -> bool:
        return self._wide

    @Slot()
    def toggleSidebar(self) -> None:
        self._wide = not self._wide
        self._settings.setValue("quick/sidebarWide", self._wide)
        self.sidebarWideChanged.emit()

    @Property(str, notify=sidebarPositionChanged)
    def sidebarPosition(self) -> str:
        """Где боковая панель: left, right, top или bottom."""
        return self._position

    @Slot(str)
    def setSidebarPosition(self, position: str) -> None:
        if position not in SIDEBAR_POSITIONS or position == self._position:
            return
        self._position = position
        self._settings.setValue("quick/sidebarPosition", position)
        self.sidebarPositionChanged.emit()

    @Property(str, notify=pageChanged)
    def page(self) -> str:
        return self._page

    @Slot(str)
    @Slot(str, str)
    def navigate(self, page: str, sub: str = "") -> None:
        if page != self._page:
            self._page = page
            self.pageChanged.emit()
        self.navigateRequested.emit(page, sub)

    @Property(str, constant=True)
    def fontUi(self) -> str:
        return self._fonts[0]

    @Property(str, constant=True)
    def fontMono(self) -> str:
        return self._fonts[1]

    @Property(str, constant=True)
    def website(self) -> str:
        from shared.version import WEBSITE_URL
        return WEBSITE_URL

    @Property(str, constant=True)
    def supportEmail(self) -> str:
        from shared.version import SUPPORT_EMAIL
        return SUPPORT_EMAIL

    @Property(str, constant=True)
    def version(self) -> str:
        return APP_VERSION

    # --- Мелкие действия ------------------------------------------------------------------------
    @Slot(str)
    @Slot(str, str)
    def toast(self, text: str, kind: str = "ok") -> None:
        self.toastRequested.emit(text, kind)

    @Slot(str)
    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.toast(t("q.copied"))

    @Slot(str)
    def openPath(self, path: str) -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openUrl(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    # --- Загрузки (фоновые задачи) --------------------------------------------------------------
    @Property("QVariantList", notify=tasksChanged)
    def tasks(self) -> list[dict]:
        return self._active + self._recent

    @Property(int, notify=tasksChanged)
    def activeTasks(self) -> int:
        return len(self._active)

    @Property(float, notify=tasksChanged)
    def tasksProgress(self) -> float:
        if not self._active:
            return 100.0
        return sum(task["progress"] for task in self._active) / len(self._active)

    @staticmethod
    def _task_row(task: dict) -> dict:
        return {"id": task.get("id", ""), "title": task.get("title", ""), "message": task.get("message", ""),
                "progress": float(task.get("progress") or 0), "status": task.get("status", ""),
                "error": task.get("error") or ""}

    def _on_tasks(self, active: list[dict]) -> None:
        self._active = [self._task_row(task) for task in active]
        self.tasksChanged.emit()

    def _on_task_finished(self, task: dict) -> None:
        row = self._task_row(task)
        row["finishedAt"] = time.time()
        self._recent = [row] + [r for r in self._recent if r["id"] != row["id"]][: _RECENT_TASKS - 1]
        self._active = [r for r in self._active if r["id"] != row["id"]]
        self.tasksChanged.emit()

    @Slot()
    def clearFinishedTasks(self) -> None:
        self._recent = []
        self.tasksChanged.emit()

    # --- Аккаунты -------------------------------------------------------------------------------
    @Property("QVariantList", notify=accountsChanged)
    def accounts(self) -> list[dict]:
        return self._accounts

    @Property("QVariantMap", notify=accountsChanged)
    def account(self) -> dict:
        return next((a for a in self._accounts if a["active"]), self._accounts[0] if self._accounts else {})

    @Slot()
    def refreshAccounts(self) -> None:
        def done(items: list[dict]) -> None:
            self._accounts = [{
                "id": a["id"], "name": a["username"], "active": bool(a.get("active")),
                "kind": t(_ACCOUNT_KINDS.get(str(a.get("auth_type", "")), "q.account_offline")),
                "seed": art.seed_of(a["username"]), "expired": bool(a.get("expired")),
            } for a in items]
            self.accountsChanged.emit()
            active = self.account.get("id", "")
            if active != self._skin_for:
                self.loadSkin()

        run_async(self.api.accounts, done, lambda msg: logger.warning(f"Аккаунты не загружены: {msg}"), owner=self)

    # --- Скин активного аккаунта (3D-модель в библиотеке) ------------------------------------------
    @Property("QVariantMap", notify=skinChanged)
    def skin(self) -> dict:
        """{skin, cape, slim, source} — пути к png для NxSkinView."""
        return self._skin

    @Slot()
    def loadSkin(self) -> None:
        account_id = self.account.get("id", "")
        changed = account_id != self._skin_for
        self._skin_for = account_id
        if changed or not account_id:
            # Не показываем скин прежнего аккаунта под новым ником, пока грузится новый
            self._skin = {}
            self.skinChanged.emit()
        if not account_id:
            return

        def done(info: dict) -> None:
            if self._skin_for == account_id:
                self._skin = info
                self.skinChanged.emit()

        run_async(lambda: self.api.account_skin(account_id), done,
                  lambda msg: logger.warning(f"Скин не загружен: {msg}"), owner=self)

    @Slot(int)
    def stepAccount(self, step: int) -> None:
        """Стрелки у ника: следующий/предыдущий аккаунт."""
        if len(self._accounts) < 2:
            return
        index = next((i for i, a in enumerate(self._accounts) if a["active"]), 0)
        self.activateAccount(self._accounts[(index + step) % len(self._accounts)]["id"])

    def _skin_call(self, call, done_text: str) -> None:
        account_id = self.account.get("id", "")
        if not account_id:
            return

        def done(info: dict) -> None:
            self._skin = info
            self.skinChanged.emit()
            # У аккаунта Nexora скин уходит на сервер, и это меняет ответ на вопрос «где его видно»
            self.toast(t("q.skin_set_nexora") if done_text == t("q.skin_set") and info.get("source") == "nexora"
                       else done_text)

        run_async(lambda: call(account_id), done, lambda msg: self.toast(msg, "err"), owner=self)

    @Slot(str, bool)
    def chooseSkin(self, url: str, slim: bool) -> None:
        path = QUrl(url).toLocalFile() or url
        self._skin_call(lambda a: self.api.set_account_skin(a, path, slim), t("q.skin_set"))

    @Slot(str)
    def chooseCape(self, url: str) -> None:
        path = QUrl(url).toLocalFile() or url
        self._skin_call(lambda a: self.api.set_account_cape(a, path), t("q.cape_set"))

    @Slot()
    def resetSkin(self) -> None:
        self._skin_call(self.api.reset_account_skin, t("q.skin_reset"))

    @Slot(str)
    def activateAccount(self, account_id: str) -> None:
        run_async(lambda: self.api.activate_account(account_id), lambda _r: self.refreshAccounts(),
                  lambda msg: self.toast(msg, "err"), owner=self)

    @Slot(str)
    def removeAccount(self, account_id: str) -> None:
        run_async(lambda: self.api.remove_account(account_id), lambda _r: self.refreshAccounts(),
                  lambda msg: self.toast(msg, "err"), owner=self)

    # --- Вход Microsoft (код устройства) ---------------------------------------------------------
    @Property("QVariantMap", notify=microsoftChanged)
    def microsoft(self) -> dict:
        return self._ms

    @Slot()
    def checkMicrosoft(self) -> None:
        """Узнаёт у backend, собран ли лаунчер со своим приложением Azure."""
        def done(values: dict) -> None:
            self._ms = dict(self._ms, available=bool(values.get("ms_available", True)))
            self.microsoftChanged.emit()

        run_async(self.api.settings, done,
                  lambda message: logger.debug(f"Доступность входа Microsoft не выяснена: {message}"),
                  owner=self)

    @Slot()
    def startMicrosoftLogin(self) -> None:
        self._ms = {"state": "starting"}
        self.microsoftChanged.emit()

        def done(_task: dict) -> None:
            self._ms = {"state": "done"}
            self.microsoftChanged.emit()
            self.refreshAccounts()
            self.toast(t("q.ms_signed_in"))

        def failed(message: str) -> None:
            self._ms = {"state": "error", "error": message}
            self.microsoftChanged.emit()

        def started(data: dict) -> None:
            self._ms = {"state": "waiting", "code": data.get("user_code", ""), "url": data.get("verification_uri", "")}
            self.microsoftChanged.emit()
            self.tracker.track({"id": data["task_id"]}, done, failed)

        run_async(self.api.microsoft_login_start, started, failed, owner=self)

    # --- Аккаунт Nexora (свой сервер аккаунтов и скинов) ------------------------------------------
    @Property("QVariantMap", notify=nexoraChanged)
    def nexora(self) -> dict:
        """{state: idle | busy | error | done, error} — состояние окна входа."""
        return self._nexora

    def _nexora_login(self, call, name: str) -> None:
        self._nexora = {"state": "busy"}
        self.nexoraChanged.emit()

        def done(_account: dict) -> None:
            self._nexora = {"state": "done"}
            self.nexoraChanged.emit()
            self.refreshAccounts()
            self.toast(t("q.account_added", name=name))

        def failed(message: str) -> None:
            # Ошибку показываем прямо в окне входа: закрывать его и прятать текст в тост не нужно
            self._nexora = {"state": "error", "error": message}
            self.nexoraChanged.emit()

        run_async(call, done, failed, owner=self)

    @Slot()
    def resetNexora(self) -> None:
        """Окно входа открыли заново — убрать прежнюю ошибку."""
        if self._nexora.get("state") != "idle":
            self._nexora = {"state": "idle"}
            self.nexoraChanged.emit()

    @Slot(str, str)
    def addNexoraAccount(self, login: str, password: str) -> None:
        login = login.strip()
        self._nexora_login(lambda: self.api.nexora_login(login, password), login)

    @Slot(str, str, str)
    def registerNexoraAccount(self, username: str, email: str, password: str) -> None:
        username, email = username.strip(), email.strip()
        self._nexora_login(lambda: self.api.nexora_register(username, email, password), username)

    @Slot()
    def requestAddAccount(self) -> None:
        self.addAccountRequested.emit()

    @Slot(str)
    def addOfflineAccount(self, username: str) -> None:
        def done(_result) -> None:
            self.refreshAccounts()
            self.toast(t("q.account_added", name=username))

        run_async(lambda: self.api.offline_login(username.strip()), done,
                  lambda msg: self.toast(msg, "err"), owner=self)
