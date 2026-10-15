"""Главное окно NexoraLauncher."""

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.task_tracker import TaskTracker
from frontend.utils.worker import run_async
from frontend.widgets import AppContext, IconCache, app_icon, confirm, label
from shared.i18n import t
from shared.version import APP_NAME, APP_VERSION

_PROCESS_POLL_MS = 2500


def _page_factories() -> list[tuple[str, str, Callable]]:
    """(id, ключ перевода, фабрика страницы) — страницы создаются лениво."""
    from frontend.pages.accounts_page import AccountsPage
    from frontend.pages.ai_chat_page import AIChatPage
    from frontend.pages.browse_page import BrowsePage
    from frontend.pages.home_page import HomePage
    from frontend.pages.hosting_page import HostingPage
    from frontend.pages.instances_page import InstancesPage
    from frontend.pages.servers_page import ServersPage
    from frontend.pages.settings_page import SettingsPage
    from frontend.pages.versions_page import VersionsPage
    from frontend.pages.worlds_page import WorldsPage

    return [
        ("home", "nav.home", HomePage),
        ("instances", "nav.instances", InstancesPage),
        ("mods", "nav.mods", lambda ctx: BrowsePage(ctx, "mod")),
        ("modpacks", "nav.modpacks", lambda ctx: BrowsePage(ctx, "modpack")),
        ("resourcepacks", "nav.resourcepacks", lambda ctx: BrowsePage(ctx, "resourcepack")),
        ("shaders", "nav.shaders", lambda ctx: BrowsePage(ctx, "shader")),
        ("worlds", "nav.worlds", WorldsPage),
        ("versions", "nav.versions", VersionsPage),
        ("servers", "nav.servers", ServersPage),
        ("hosting", "nav.hosting", HostingPage),
        ("accounts", "nav.accounts", AccountsPage),
        ("ai", "nav.ai", AIChatPage),
        ("settings", "nav.settings", SettingsPage),
    ]


class MainWindow(QMainWindow):
    """Главное окно: боковая навигация, страницы, статус задач и игр."""

    def __init__(self, api: ApiClient):
        super().__init__()
        self.api = api
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1000, 660)
        self.resize(1240, 800)

        IconCache.init(api)
        self.tracker = TaskTracker(api, self)
        self.ctx = AppContext(api, self.tracker, self)
        self.ctx.navigate.connect(self.navigate)
        self._pages: dict[str, QWidget] = {}
        self._factories = {pid: factory for pid, _, factory in _page_factories()}
        self._known_processes: dict[int, str] = {}
        self._announced_addresses: set[str] = set()
        self._active_tasks: list[dict] = []
        self._update_checked = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self._build_status_bar()

        self.tracker.tasks_changed.connect(self._on_tasks_changed)
        self.tracker.task_finished.connect(self._on_task_finished)
        self._process_timer = QTimer(self)
        self._process_timer.setInterval(_PROCESS_POLL_MS)
        self._process_timer.timeout.connect(self._poll_processes)
        self._process_timer.start()

        run_async(api.settings, self._on_settings, owner=self)
        self.navigate("home")

    # --- Построение UI ------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 4, 10, 12)
        layout.setSpacing(2)
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(14, 12, 0, 0)
        logo_row.setSpacing(0)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(30, 30))
        logo_row.addWidget(icon)
        logo = label("Nexora", "Logo")
        logo.setContentsMargins(0, 0, 0, 0)
        logo_row.addWidget(logo, 1)
        layout.addLayout(logo_row)
        layout.addWidget(label(t("app.tagline"), "LogoSub"))

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for page_id, key, _ in _page_factories():
            if page_id in ("versions", "accounts"):
                layout.addSpacing(8)
            btn = QPushButton(t(key))
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, pid=page_id: self.navigate(pid))
            self.nav_group.addButton(btn)
            self.nav_buttons[page_id] = btn
            layout.addWidget(btn)
        layout.addStretch()
        self.account_label = label("", muted=True, wrap=True)
        self.account_label.setContentsMargins(12, 0, 12, 4)
        layout.addWidget(self.account_label)
        version = label(f"v{APP_VERSION}", muted=True)
        version.setContentsMargins(12, 0, 12, 0)
        layout.addWidget(version)
        self.ctx.accounts_changed.connect(self._refresh_account)
        self._refresh_account()
        return sidebar

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.task_label = QLabel(t("status.ready"))
        self.task_progress = QProgressBar()
        self.task_progress.setFixedWidth(180)
        self.task_progress.setTextVisible(False)
        self.task_progress.hide()
        self.games_label = QLabel("")
        bar.addWidget(self.task_label, 1)
        bar.addPermanentWidget(self.task_progress)
        bar.addPermanentWidget(self.games_label)

    # --- Навигация ------------------------------------------------------------------
    def navigate(self, page_id: str, params: dict | None = None) -> None:
        if page_id not in self._factories:
            return
        page = self._pages.get(page_id)
        if page is None:
            page = self._factories[page_id](self.ctx)
            self._pages[page_id] = page
            self.stack.addWidget(page)
        if params and hasattr(page, "apply_params"):
            page.apply_params(params)
        self.stack.setCurrentWidget(page)
        self.nav_buttons[page_id].setChecked(True)

    # --- Состояние ---------------------------------------------------------------------
    def _on_settings(self, settings: dict) -> None:
        self.ctx.settings = settings
        self.ctx.settings_changed.emit(settings)
        if settings.get("check_updates", True) and not self._update_checked:
            self._update_checked = True
            from frontend.dialogs.update_dialog import check_for_updates
            QTimer.singleShot(4000, lambda: check_for_updates(self.ctx, self, silent=True))

    def _refresh_account(self) -> None:
        def show(accounts: list[dict]) -> None:
            active = next((a for a in accounts if a["active"]), None)
            self.account_label.setText(
                t("sidebar.account", name=active["username"]) if active else t("sidebar.no_account")
            )

        run_async(self.api.accounts, show, lambda _m: None, owner=self)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._active_tasks and not confirm(self, t("app.close_with_tasks", n=len(self._active_tasks))):
            event.ignore()
            return
        try:
            running = [s["name"] for s in self.api.hosted_servers() if s["state"] in ("starting", "running")]
        except Exception:  # noqa: BLE001 — backend уже недоступен
            running = []
        if running and not confirm(self, t("app.close_with_servers", names=", ".join(running))):
            event.ignore()
            return
        event.accept()

    def _on_tasks_changed(self, tasks: list[dict]) -> None:
        self._active_tasks = tasks
        if not tasks:
            self.task_label.setText(t("status.ready"))
            self.task_progress.hide()
            return
        task = tasks[0]
        extra = f"  (+{len(tasks) - 1})" if len(tasks) > 1 else ""
        message = task.get("message") or ""
        self.task_label.setText(f"{task['title']}: {message}{extra}" if message else task["title"] + extra)
        self.task_progress.show()
        if task.get("progress") is None:
            self.task_progress.setRange(0, 0)
        else:
            self.task_progress.setRange(0, 1000)
            self.task_progress.setValue(int(task["progress"] * 1000))

    def _on_task_finished(self, task: dict) -> None:
        if task.get("kind") in ("install", "import", "modpack", "launch"):
            self.ctx.instances_changed.emit()
        if task.get("kind") == "microsoft_login":
            self.ctx.accounts_changed.emit()
        if task.get("kind") == "launch" and task.get("status") == "done" \
                and self.ctx.settings.get("hide_on_launch"):
            self.showMinimized()

    def _poll_processes(self) -> None:
        run_async(self.api.processes, self._on_processes, lambda _m: None, owner=self)

    def _on_processes(self, processes: list[dict]) -> None:
        running = [p for p in processes if p["status"] == "running"]
        self.games_label.setText(t("status.games_running", n=len(running)) if running else "")
        changed = False
        for proc in processes:
            previous = self._known_processes.get(proc["pid"])
            if previous == "running" and proc["status"] != "running":
                changed = True
                if proc["status"] == "crashed":
                    self._report_crash(proc)
            elif previous is None and proc["status"] == "running":
                changed = True
            self._known_processes[proc["pid"]] = proc["status"]
            address = proc.get("public_address")
            if address and f"{proc['pid']}|{address}" not in self._announced_addresses:
                self._announced_addresses.add(f"{proc['pid']}|{address}")
                from frontend.dialogs.hosting_dialogs import show_address_dialog
                show_address_dialog(self, t("friends.title"), address, t("friends.address_text"))
        if changed:
            self.ctx.instances_changed.emit()

    def _report_crash(self, proc: dict) -> None:
        logger.warning(f"Игра '{proc['instance']}' завершилась с ошибкой {proc['exit_code']}")
        if self.isMinimized():
            self.showNormal()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(t("crash.title"))
        box.setText(t("crash.text", name=proc["instance"], code=proc["exit_code"]))
        diagnose = box.addButton(t("crash.diagnose"), QMessageBox.ButtonRole.AcceptRole)
        show_log = box.addButton(t("crash.show_log"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(t("common.close"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() in (diagnose, show_log):
            from frontend.dialogs.instance_dialog import InstanceDialog
            tab = "doctor" if box.clickedButton() is diagnose else "logs"
            InstanceDialog(self.ctx, proc["instance"], self, initial_tab=tab).exec()
