"""Избранные серверы: статус, подключение."""

import base64

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    Card,
    Page,
    button,
    clear_layout,
    confirm,
    fill_instance_combo,
    instance_combo,
    label,
    show_error,
)
from shared.i18n import t


def parse_address(address: str) -> tuple[str, int]:
    """'play.example.com:25566' → ('play.example.com', 25566)."""
    address = address.strip()
    if address.count(":") == 1:
        host, _, port = address.partition(":")
        if port.isdigit() and 0 < int(port) < 65536:
            return host.strip(), int(port)
    return address, 25565


class ServerDialog(QDialog):
    """Добавление/редактирование сервера."""

    def __init__(self, ctx: AppContext, parent=None, server: dict | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.server = server
        self.setWindowTitle(t("servers.edit") if server else t("servers.add"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(server["name"] if server else "")
        self.name.setPlaceholderText(t("servers.name_placeholder"))
        form.addRow(t("servers.name"), self.name)
        address = ""
        if server:
            address = server["host"] if server["port"] == 25565 else f"{server['host']}:{server['port']}"
        self.address = QLineEdit(address)
        self.address.setPlaceholderText("play.example.com:25565")
        form.addRow(t("servers.address"), self.address)
        self.instance = instance_combo()
        form.addRow(t("servers.instance"), self.instance)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        run_async(ctx.api.instances,
                  lambda items: fill_instance_combo(self.instance, items,
                                                    server["instance_name"] if server else None,
                                                    include_empty=t("servers.last_instance")),
                  owner=self)

    def _save(self) -> None:
        name = self.name.text().strip()
        host, port = parse_address(self.address.text())
        if not name or not host:
            show_error(self, t("create.fill_fields"))
            return
        instance_name = (self.instance.currentData() or {}).get("name", "")
        api = self.ctx.api
        if self.server:
            server_id = self.server["id"]
            call = lambda: api.update_server(server_id, name=name, host=host, port=port,  # noqa: E731
                                             instance_name=instance_name)
        else:
            call = lambda: api.create_server(name, host, port, instance_name)  # noqa: E731
        run_async(call, lambda _r: self.accept(), lambda msg: show_error(self, msg), owner=self)


class ServersPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("servers.title"), t("servers.subtitle"))
        self.actions.addWidget(button(t("servers.refresh"), self.reload))
        self.actions.addWidget(button(t("servers.add"), self._add, "primary"))

    def on_show(self, first: bool) -> None:
        self.reload()

    def reload(self) -> None:
        self.run(self.api.servers, self._render)

    def _render(self, servers: list[dict]) -> None:
        if not servers:
            self.set_empty(t("servers.empty"))
            return
        clear_layout(self.body)
        for server in servers:
            self.body.addWidget(self._card(server))
        self.body.addStretch()

    def _card(self, server: dict) -> Card:
        card = Card()
        icon = QLabel("🌐")
        icon.setObjectName("Badge")
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.layout_.addWidget(icon)
        info = QVBoxLayout()
        info.setSpacing(3)
        info.addWidget(label(server["name"], "CardTitle"))
        address = server["host"] if server["port"] == 25565 else f"{server['host']}:{server['port']}"
        info.addWidget(label(address, muted=True))
        status = label(t("servers.pinging"), muted=True, wrap=True)
        info.addWidget(status)
        card.layout_.addLayout(info, 1)
        players = label("", "Badge")
        card.layout_.addWidget(players)
        card.layout_.addWidget(button(t("servers.play"), lambda: self._connect(server), "play"))
        card.layout_.addWidget(button("✎", lambda: self._edit(server), "ghost", t("servers.edit")))
        card.layout_.addWidget(button("🗑", lambda: self._delete(server), "ghost", t("common.delete")))

        def pinged(result: dict) -> None:
            if result["online"]:
                motd = (result.get("motd") or "").replace("\n", " ")
                status.setText(f"{motd}\n{result.get('version') or ''} · {result.get('latency_ms')} ms")
                players.setText(f"{result.get('player_count')}/{result.get('max_players')}")
                if result.get("icon") and "," in result["icon"]:
                    pixmap = QPixmap()
                    pixmap.loadFromData(base64.b64decode(result["icon"].split(",", 1)[1]))
                    if not pixmap.isNull():
                        icon.setPixmap(pixmap.scaled(52, 52, Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
            else:
                status.setText(t("servers.offline"))
                players.setText("—")

        run_async(lambda: self.api.ping_server(server["id"]), pinged,
                  lambda _m: status.setText(t("servers.offline")), owner=card)
        return card

    def _connect(self, server: dict) -> None:
        def started(task: dict) -> None:
            self.track(task, lambda _t: self.ctx.instances_changed.emit())

        def call():
            return self.api.connect_server(server["id"])

        run_async(call, started, lambda msg: show_error(self, msg), owner=self)

    def _add(self) -> None:
        if ServerDialog(self.ctx, self).exec():
            self.reload()

    def _edit(self, server: dict) -> None:
        if ServerDialog(self.ctx, self, server).exec():
            self.reload()

    def _delete(self, server: dict) -> None:
        if confirm(self, t("servers.delete_confirm", name=server["name"])):
            self.run(lambda: self.api.delete_server(server["id"]), lambda _r: self.reload())

