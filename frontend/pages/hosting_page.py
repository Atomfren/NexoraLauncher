"""«Свой сервер»: бесплатный сервер для игры с друзьями без белого IP."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMenu, QSizePolicy, QVBoxLayout

from frontend.components import launch_instance
from frontend.dialogs.hosting_dialogs import (
    CreateServerDialog,
    ServerBackupsDialog,
    ServerConsoleDialog,
    ServerModsDialog,
    ServerSettingsDialog,
)
from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    Card,
    Page,
    badge,
    button,
    clear_layout,
    confirm,
    format_duration,
    label,
    open_path,
    set_variant,
    show_error,
    show_info,
)
from shared.i18n import t

_POLL_MS = 2000
_STATE_BADGE = {"running": "success", "crashed": "danger"}
_CORE_TITLES = {"fabric": "Fabric", "vanilla": "Vanilla", "paper": "Paper", "purpur": "Purpur"}


class ServerCard(Card):
    """Карточка сервера. Обновляется на месте, без пересоздания."""

    def __init__(self, page: "HostingPage", server: dict):
        super().__init__()
        self.page = page
        self.name = server["name"]
        self.server = server
        icon = QLabel("🌍")
        icon.setObjectName("Badge")
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 24px;")
        self.layout_.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(4)
        title = QHBoxLayout()
        title.addWidget(label(self.name, "CardTitle"))
        self.state_badge = badge("")
        title.addWidget(self.state_badge)
        title.addStretch()
        info.addLayout(title)
        self.meta = label("", muted=True, shrink=True)
        info.addWidget(self.meta)
        address_row = QHBoxLayout()
        self.address = label("", "CardTitle", shrink=True)
        self.address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        address_row.addWidget(self.address, 1)
        self.copy_btn = button(t("hosting.copy"), self._copy, "primary", small=True)
        address_row.addWidget(self.copy_btn)
        info.addLayout(address_row)
        self.hint = label("", muted=True, wrap=True)
        self.hint.setMinimumWidth(320)  # иначе Qt считает высоту переноса по минимальной ширине
        info.addWidget(self.hint)
        info.addStretch()
        self.layout_.addLayout(info, 1)

        side = QVBoxLayout()
        self.power = button("", self._toggle)
        self.power.setMinimumWidth(140)
        side.addWidget(self.power)
        row = QHBoxLayout()
        row.addWidget(button(t("hosting.console"), lambda: ServerConsoleDialog(page.ctx, self.name,
                                                                              page.window()).exec(), small=True))
        row.addWidget(button(t("hosting.join"), self._join, small=True))
        more = button("⋯", None, "ghost", t("instance.more"), small=True)
        more.setMenu(self._menu())
        row.addWidget(more)
        side.addLayout(row)
        side.addStretch()
        self.layout_.addLayout(side)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.update_status(server)

    def update_status(self, server: dict) -> None:
        self.server = server
        state = server["state"] if server["installed"] else "not_installed"
        self.state_badge.setText(t(f"hosting.state_{state}"))
        self.state_badge.setObjectName({"success": "BadgeSuccess", "danger": "BadgeDanger"}.get(
            _STATE_BADGE.get(state, ""), "Badge"))
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)
        players = ", ".join(server["players"]) if server["players"] else "—"
        meta = _CORE_TITLES.get(server.get("core", "fabric"), "") + "  ·  " + t(
            "hosting.meta", version=server["version"], memory=server["max_memory"], players=players)
        if server["uptime_seconds"]:
            meta += "  ·  " + t("hosting.uptime", time=format_duration(server["uptime_seconds"]))
        self.meta.setText(meta)

        running = state in ("starting", "running", "stopping")
        public = server["public_address"]
        if public:
            self.address.setText("🌐 " + public)
            self.hint.setText(t("hosting.share_hint", lan=server["lan_address"]))
        elif state == "starting" and server["tunnel"]:
            self.address.setText(t("hosting.getting_address"))
            self.hint.setText("")
        elif running:
            self.address.setText("🏠 " + server["lan_address"])
            if not server.get("tunnel_supported", True):
                self.hint.setText(t("hosting.no_tunnel_hint"))
            else:
                self.hint.setText(t("hosting.tunnel_off_hint") if not server["tunnel"] else "")
        else:
            self.address.setText("")
            stopped = "hosting.stopped_hint" if server["tunnel"] else "hosting.stopped_hint_lan"
            self.hint.setText(t(stopped) if server["installed"] else t("hosting.installing_hint"))
        self.copy_btn.setVisible(bool(public) or (running and not server["tunnel"]))
        self.address.setVisible(bool(self.address.text()))

        self.power.setEnabled(server["installed"] and state != "stopping")
        if running:
            self.power.setText(t("hosting.stop"))
            set_variant(self.power, "stop")
        else:
            self.power.setText(t("hosting.start"))
            set_variant(self.power, "play")

    def _copy(self) -> None:
        address = self.server["public_address"] or self.server["lan_address"]
        QGuiApplication.clipboard().setText(address)
        self.copy_btn.setText(t("accounts.ms_copied"))
        QTimer.singleShot(1500, lambda: self.copy_btn.setText(t("hosting.copy")))

    def _toggle(self) -> None:
        api = self.page.api
        running = self.server["state"] in ("starting", "running")
        if running and not confirm(self, t("hosting.stop_confirm", name=self.name)):
            return
        call = (lambda: api.stop_hosted_server(self.name)) if running else (lambda: api.start_hosted_server(self.name))
        self.power.setEnabled(False)
        run_async(call, self.update_status, lambda msg: (show_error(self.window(), msg), self.page.reload()),
                  owner=self)

    def _join(self) -> None:
        """Зайти на свой сервер с подходящего инстанса (ванильный клиент тоже подходит)."""
        version = self.server["version"]

        def pick(instances: list[dict]) -> None:
            matching = [i for i in instances if i["version"] == version]
            if not matching:
                if confirm(self, t("hosting.no_instance", version=version)):
                    self.page.ctx.navigate.emit("instances", {"create": True, "version": version})
                return
            target = next((i for i in matching if i["mod_loader"] == "vanilla"), matching[0])
            launch_instance(self.page.ctx, self.window(), target["name"], server="127.0.0.1",
                            port=self.server["port"])

        run_async(self.page.api.instances, pick, lambda msg: show_error(self.window(), msg), owner=self)

    def _menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(t("hosting.settings"), self._settings)
        content_type = self.server.get("content_type", "mod")
        if content_type:
            title = t("hosting.plugins") if content_type == "plugin" else t("hosting.mods")
            menu.addAction(title, lambda: ServerModsDialog(self.page.ctx, self.server, self.window()).exec())
        if content_type == "mod":
            menu.addAction(t("hosting.friends_pack"), self._client_pack)
        menu.addAction(t("hosting.backups"), lambda: ServerBackupsDialog(self.page.ctx, self.name,
                                                                          self.window()).exec())
        menu.addAction(t("common.open_folder"), lambda: open_path(self._path()))
        menu.addSeparator()
        menu.addAction(t("hosting.reinstall"), self._reinstall)
        menu.addAction(t("common.delete"), self._delete)
        return menu

    def _path(self) -> str:
        from shared.paths import get_data_dir
        return str(get_data_dir() / "servers" / self.name)

    def _settings(self) -> None:
        if ServerSettingsDialog(self.page.ctx, self.name, self.window()).exec():
            self.page.reload()

    def _client_pack(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("hosting.friends_pack"), f"{self.name}.mrpack",
                                              "Modrinth (*.mrpack)")
        if not path:
            return
        window, ctx = self.window(), self.page.ctx

        def done(task: dict) -> None:
            result = task.get("result") or {}
            show_info(window, t("hosting.friends_pack_done", path=path, mods=result.get("mods", 0)))

        run_async(lambda: ctx.api.server_client_pack(self.name, path),
                  lambda task: ctx.tracker.track(task, done, lambda msg: show_error(window, msg)),
                  lambda msg: show_error(window, msg), owner=ctx)

    def _reinstall(self) -> None:
        ctx = self.page.ctx
        run_async(lambda: ctx.api.reinstall_hosted_server(self.name),
                  lambda task: ctx.tracker.track(task, lambda _t: self.page.reload(),
                                                 lambda msg: show_error(self.window(), msg)),
                  lambda msg: show_error(self.window(), msg), owner=ctx)

    def _delete(self) -> None:
        if confirm(self, t("hosting.delete_confirm", name=self.name)):
            run_async(lambda: self.page.api.delete_hosted_server(self.name), lambda _r: self.page.reload(),
                      lambda msg: show_error(self.window(), msg), owner=self.page)


class HostingPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("hosting.title"), t("hosting.subtitle"))
        self.actions.addWidget(button(t("hosting.create"), self._create, "primary"))
        self._cards: dict[str, ServerCard] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)

    def on_show(self, first: bool) -> None:
        self.reload()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def reload(self) -> None:
        self.run(self.api.hosted_servers, self._render)

    def _render(self, servers: list[dict]) -> None:
        self._cards.clear()
        clear_layout(self.body)
        how = label(t("hosting.how_it_works"), muted=True, wrap=True)
        self.body.addWidget(how)
        if not servers:
            empty = label(t("hosting.empty"), "Empty", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(empty)
        for server in servers:
            card = ServerCard(self, server)
            self._cards[server["name"]] = card
            self.body.addWidget(card)
        self.body.addStretch()

    def _poll(self) -> None:
        def update(servers: list[dict]) -> None:
            if {s["name"] for s in servers} != set(self._cards):
                self._render(servers)
                return
            for server in servers:
                self._cards[server["name"]].update_status(server)

        run_async(self.api.hosted_servers, update, lambda _m: None, owner=self)

    def _create(self) -> None:
        dialog = CreateServerDialog(self.ctx, self)
        if dialog.exec() and dialog.result_data:
            self.track(dialog.result_data["task"],
                       lambda _t: (self.reload(), show_info(self, t("hosting.created"))))
            self.reload()
