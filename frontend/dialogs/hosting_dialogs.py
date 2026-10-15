"""Диалоги «Своего сервера»: создание, консоль, настройки, моды."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    button,
    confirm,
    format_date,
    format_size,
    label,
    open_url,
    show_error,
    show_info,
)
from shared.i18n import t

EULA_URL = "https://aka.ms/MinecraftEULA"
CORES = ("fabric", "paper", "purpur", "vanilla")


class CreateServerDialog(QDialog):
    """Новый сервер: имя, версия, память и согласие с EULA."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.result_data: dict | None = None
        self.setWindowTitle(t("hosting.create_title"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(label(t("hosting.create_intro"), muted=True, wrap=True))
        form = QFormLayout()
        self.name = QLineEdit(t("hosting.default_name"))
        self.name.setMaxLength(64)
        form.addRow(t("create.name"), self.name)
        self.core = QComboBox()
        for core in CORES:
            self.core.addItem(t(f"hosting.core_{core}"), core)
        form.addRow(t("hosting.core"), self.core)
        self.core_hint = label("", muted=True, wrap=True)
        form.addRow("", self.core_hint)
        self.core.currentIndexChanged.connect(self._core_changed)
        self._core_changed()
        self.version = QComboBox()
        self.version.addItem(t("common.loading"))
        self.version.setEnabled(False)
        form.addRow(t("create.version"), self.version)
        self.memory = QSpinBox()
        self.memory.setRange(1024, 32768)
        self.memory.setSingleStep(512)
        self.memory.setValue(3072)
        self.memory.setSuffix(" MB")
        form.addRow(t("settings.memory"), self.memory)
        layout.addLayout(form)
        eula_row = QHBoxLayout()
        self.eula = QCheckBox(t("hosting.eula"))
        eula_row.addWidget(self.eula)
        eula_row.addWidget(button(t("hosting.eula_read"), lambda: open_url(EULA_URL), "ghost", small=True))
        eula_row.addStretch()
        layout.addLayout(eula_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText(t("hosting.create_submit"))
        self.ok.setEnabled(False)
        self.eula.toggled.connect(self._update_ok)
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        def fill(versions: list[dict]) -> None:
            self.version.clear()
            for v in versions:
                if v["type"] == "release":
                    self.version.addItem(v["id"], v["id"])
            self.version.setEnabled(True)
            self._update_ok()

        run_async(ctx.api.available_versions, fill, lambda msg: show_error(self, msg), owner=self)

    def _core_changed(self) -> None:
        fabric = self.core.currentData() == "fabric"
        self.core_hint.setText(t("hosting.core_hint_fabric") if fabric else t("hosting.core_hint_other"))

    def _update_ok(self) -> None:
        self.ok.setEnabled(self.eula.isChecked() and self.version.isEnabled())

    def _submit(self) -> None:
        name, version = self.name.text().strip(), self.version.currentData()
        if not name or not version:
            show_error(self, t("create.fill_fields"))
            return
        self.ok.setEnabled(False)

        def done(data: dict) -> None:
            self.result_data = data
            self.accept()

        core = self.core.currentData()
        run_async(lambda: self.ctx.api.create_hosted_server(name, version, self.memory.value(), True, core), done,
                  lambda msg: (show_error(self, msg), self._update_ok()), owner=self)


class ServerConsoleDialog(QDialog):
    """Консоль сервера: живой лог и ввод команд."""

    def __init__(self, ctx: AppContext, name: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.name = name
        self.setWindowTitle(t("hosting.console_title", name=name))
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        self.view = QPlainTextEdit()
        self.view.setObjectName("Log")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        layout.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(t("hosting.command_placeholder"))
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(button(t("hosting.send"), self._send, "primary"))
        layout.addLayout(row)
        quick = QHBoxLayout()
        for title, template in ((t("hosting.quick_op"), "op "), (t("hosting.quick_whitelist"), "whitelist add "),
                                (t("hosting.quick_say"), "say "), (t("hosting.quick_day"), "time set day")):
            quick.addWidget(button(title, lambda tpl=template: self._template(tpl), small=True))
        quick.addStretch()
        layout.addLayout(quick)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _template(self, template: str) -> None:
        if template.endswith(" "):
            self.input.setText(template)
            self.input.setFocus()
        else:
            self.input.setText(template)
            self._send()

    def _refresh(self) -> None:
        def show(lines: list[str]) -> None:
            text = "\n".join(lines)
            if text != self.view.toPlainText():
                bar = self.view.verticalScrollBar()
                at_bottom = bar.value() >= bar.maximum() - 4
                self.view.setPlainText(text)
                if at_bottom:
                    bar.setValue(bar.maximum())

        run_async(lambda: self.ctx.api.server_console(self.name, 2000), show, lambda _m: None, owner=self)

    def _send(self) -> None:
        command = self.input.text().strip()
        if not command:
            return
        self.input.clear()
        run_async(lambda: self.ctx.api.server_command(self.name, command), lambda _r: self._refresh(),
                  lambda msg: show_error(self, msg), owner=self)

    def done(self, result: int) -> None:
        self._timer.stop()
        super().done(result)


class ServerSettingsDialog(QDialog):
    """server.properties и параметры запуска."""

    _CHOICES = {
        "gamemode": ["survival", "creative", "adventure", "spectator"],
        "difficulty": ["peaceful", "easy", "normal", "hard"],
    }
    _BOOLS = ["pvp", "allow-flight", "hardcore", "white-list", "enable-command-block"]

    def __init__(self, ctx: AppContext, name: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.name = name
        self.setWindowTitle(t("hosting.settings_title", name=name))
        self.setMinimumWidth(660)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        game = QWidget()
        self.form = QFormLayout(game)
        tabs.addTab(game, t("hosting.tab_game"))
        launch = QWidget()
        launch_form = QFormLayout(launch)
        tabs.addTab(launch, t("hosting.tab_launch"))

        self.motd = QLineEdit()
        self.form.addRow(t("hosting.prop_motd"), self.motd)
        self.max_players = QSpinBox()
        self.max_players.setRange(1, 200)
        self.form.addRow(t("hosting.prop_max_players"), self.max_players)
        self.combos: dict[str, QComboBox] = {}
        for key, values in self._CHOICES.items():
            combo = QComboBox()
            for value in values:
                combo.addItem(t(f"hosting.{key}_{value}"), value)
            self.combos[key] = combo
            self.form.addRow(t(f"hosting.prop_{key}"), combo)
        self.view_distance = QSpinBox()
        self.view_distance.setRange(3, 32)
        self.form.addRow(t("hosting.prop_view_distance"), self.view_distance)
        self.seed = QLineEdit()
        self.seed.setPlaceholderText(t("hosting.seed_placeholder"))
        self.form.addRow(t("hosting.prop_seed"), self.seed)
        self.checks: dict[str, QCheckBox] = {}
        for key in self._BOOLS:
            box = QCheckBox(t(f"hosting.prop_{key.replace('-', '_')}"))
            self.checks[key] = box
            self.form.addRow("", box)
        self.licensed = QCheckBox(t("hosting.prop_online_mode"))
        self.form.addRow("", self.licensed)
        self.form.addRow("", label(t("hosting.online_mode_hint"), muted=True, wrap=True))

        self.memory = QSpinBox()
        self.memory.setRange(1024, 65536)
        self.memory.setSingleStep(512)
        self.memory.setSuffix(" MB")
        launch_form.addRow(t("settings.memory"), self.memory)
        self.tunnel = QCheckBox(t("hosting.tunnel"))
        launch_form.addRow("", self.tunnel)
        self.tunnel_hint = label(t("hosting.tunnel_hint"), muted=True, wrap=True)
        launch_form.addRow("", self.tunnel_hint)
        self.jvm = QLineEdit()
        launch_form.addRow(t("settings.jvm_args"), self.jvm)
        self.auto_backup = QCheckBox(t("hosting.auto_backup"))
        launch_form.addRow("", self.auto_backup)
        self.backups_keep = QSpinBox()
        self.backups_keep.setRange(1, 100)
        launch_form.addRow(t("hosting.backups_keep"), self.backups_keep)
        layout.addWidget(label(t("hosting.restart_hint"), muted=True, wrap=True))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        run_async(lambda: (ctx.api.server_properties(name), ctx.api.hosted_server(name)), self._fill,
                  lambda msg: show_error(self, msg), owner=self)

    def _fill(self, data) -> None:
        props, server = data
        self.motd.setText(props.get("motd", ""))
        self.max_players.setValue(int(props.get("max-players", "10") or 10))
        for key, combo in self.combos.items():
            combo.setCurrentIndex(max(0, combo.findData(props.get(key, ""))))
        self.view_distance.setValue(int(props.get("view-distance", "10") or 10))
        self.seed.setText(props.get("level-seed", ""))
        for key, box in self.checks.items():
            box.setChecked(props.get(key, "false") == "true")
        self.licensed.setChecked(props.get("online-mode", "false") == "true")
        self.memory.setValue(server["max_memory"])
        self.tunnel.setChecked(server["tunnel"] and server["tunnel_supported"])
        self.tunnel.setEnabled(server["tunnel_supported"])
        if not server["tunnel_supported"]:
            self.tunnel_hint.setText(t("hosting.no_tunnel_hint"))
        self.jvm.setText(server["jvm_args"])
        self.auto_backup.setChecked(server["auto_backup"])
        self.backups_keep.setValue(server["backups_keep"])

    def _save(self) -> None:
        props = {
            "motd": self.motd.text().strip(),
            "max-players": self.max_players.value(),
            "view-distance": self.view_distance.value(),
            "simulation-distance": min(self.view_distance.value(), 12),
            "level-seed": self.seed.text().strip(),
            "online-mode": self.licensed.isChecked(),
            **{key: combo.currentData() for key, combo in self.combos.items()},
            **{key: box.isChecked() for key, box in self.checks.items()},
        }
        props["enforce-whitelist"] = props["white-list"]
        api, name = self.ctx.api, self.name

        def save():
            api.update_server_properties(name, props)
            return api.update_hosted_server(name, max_memory=self.memory.value(), tunnel=self.tunnel.isChecked(),
                                            jvm_args=self.jvm.text().strip(),
                                            auto_backup=self.auto_backup.isChecked(),
                                            backups_keep=self.backups_keep.value())

        run_async(save, lambda _r: self.accept(), lambda msg: show_error(self, msg), owner=self)


class ServerModsDialog(QDialog):
    """Моды сервера: установленные и поиск на Modrinth (только серверные/универсальные)."""

    def __init__(self, ctx: AppContext, server: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.server = server
        self.name = server["name"]
        plugins = server.get("content_type") == "plugin"
        self.setWindowTitle(t("hosting.plugins_title" if plugins else "hosting.mods_title", name=self.name))
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(label(t("hosting.plugins_intro" if plugins else "hosting.mods_intro"), muted=True, wrap=True))
        columns = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(label(t("hosting.installed_plugins" if plugins else "hosting.installed_mods"), "SectionTitle"))
        self.installed = QListWidget()
        left.addWidget(self.installed, 1)
        left.addWidget(button(t("common.delete"), self._remove, "danger", small=True))
        columns.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(label(t("hosting.find_plugins" if plugins else "hosting.find_mods"), "SectionTitle"))
        self.query = QLineEdit()
        self.query.setPlaceholderText(t("browse.search"))
        self.query.returnPressed.connect(self._search)
        right.addWidget(self.query)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _i: self._install())
        right.addWidget(self.results, 1)
        right.addWidget(button(t("browse.install"), self._install, "primary", small=True))
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)
        self._reload()
        self._search()

    def _reload(self) -> None:
        def show(mods: list[dict]) -> None:
            self.installed.clear()
            for mod in mods:
                suffix = "  🌐" if mod["tunnel"] else ""
                item = QListWidgetItem(f"{mod['name']}  {mod['version']}  ({format_size(mod['size'])}){suffix}")
                item.setData(Qt.ItemDataRole.UserRole, mod["filename"])
                self.installed.addItem(item)

        run_async(lambda: self.ctx.api.server_mods(self.name), show, lambda msg: show_error(self, msg), owner=self)

    def _search(self) -> None:
        query = self.query.text().strip()

        def show(data: dict) -> None:
            self.results.clear()
            for project in data["results"]:
                item = QListWidgetItem(f"{project['title']} — {project['description'][:80]}")
                item.setData(Qt.ItemDataRole.UserRole, project["project_id"])
                self.results.addItem(item)

        core = self.server.get("core", "fabric")
        run_async(lambda: self.ctx.api.search_server_mods(query, self.server["version"], core=core), show,
                  lambda msg: show_error(self, msg), owner=self)

    def _install(self) -> None:
        item = self.results.currentItem()
        if not item:
            return
        project_id = item.data(Qt.ItemDataRole.UserRole)
        run_async(lambda: self.ctx.api.install_server_mod(self.name, project_id),
                  lambda task: self.ctx.tracker.track(task, lambda _t: self._reload(),
                                                      lambda msg: show_error(self, msg)),
                  lambda msg: show_error(self, msg), owner=self)

    def _remove(self) -> None:
        item = self.installed.currentItem()
        if not item:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)
        if filename.lower().startswith("e4mc") and not confirm(self, t("hosting.remove_tunnel_confirm")):
            return
        run_async(lambda: self.ctx.api.remove_server_mod(self.name, filename), lambda _r: self._reload(),
                  lambda msg: show_error(self, msg), owner=self)


class ServerBackupsDialog(QDialog):
    """Резервные копии мира: список, создание, восстановление, удаление."""

    def __init__(self, ctx: AppContext, name: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.name = name
        self.setWindowTitle(t("hosting.backups_title", name=name))
        self.resize(620, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(label(t("hosting.backups_intro"), muted=True, wrap=True))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._restore())
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(t("hosting.backup_now"), self._create, "primary", small=True))
        row.addWidget(button(t("hosting.backup_restore"), self._restore, small=True))
        row.addWidget(button(t("common.delete"), self._delete, "danger", small=True))
        row.addStretch()
        row.addWidget(button(t("common.close"), self.accept, small=True))
        layout.addLayout(row)
        self._reload()

    def _reload(self) -> None:
        def show(backups: list[dict]) -> None:
            self.list.clear()
            if not backups:
                item = QListWidgetItem(t("hosting.backups_empty"))
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(item)
            for backup in backups:
                reason = t(f"hosting.backup_reason_{backup['reason'].replace('-', '_')}")
                item = QListWidgetItem(f"{format_date(backup['created_at'])}   ·   {reason}   ·   "
                                       f"{format_size(backup['size'])}")
                item.setData(Qt.ItemDataRole.UserRole, backup)
                self.list.addItem(item)

        run_async(lambda: self.ctx.api.server_backups(self.name), show, lambda msg: show_error(self, msg),
                  owner=self)

    def _selected(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _track(self, call, message: str) -> None:
        run_async(call, lambda task: self.ctx.tracker.track(
            task, lambda _t: (self._reload(), show_info(self, message)), lambda msg: show_error(self, msg)),
            lambda msg: show_error(self, msg), owner=self)

    def _create(self) -> None:
        self._track(lambda: self.ctx.api.create_server_backup(self.name), t("hosting.backup_done"))

    def _restore(self) -> None:
        backup = self._selected()
        if not backup or not confirm(self, t("hosting.backup_restore_confirm", name=self.name,
                                             date=format_date(backup["created_at"]))):
            return
        filename = backup["filename"]
        self._track(lambda: self.ctx.api.restore_server_backup(self.name, filename), t("hosting.restored"))

    def _delete(self) -> None:
        backup = self._selected()
        if not backup or not confirm(self, t("hosting.backup_delete_confirm", date=format_date(backup["created_at"]))):
            return
        filename = backup["filename"]
        run_async(lambda: self.ctx.api.delete_server_backup(self.name, filename), lambda _r: self._reload(),
                  lambda msg: show_error(self, msg), owner=self)


def show_address_dialog(parent, title: str, address: str, text: str) -> None:
    """Окно с публичным адресом и кнопкой копирования."""
    from PyQt6.QtGui import QGuiApplication

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(460)
    layout = QVBoxLayout(dialog)
    layout.addWidget(label(text, wrap=True))
    code = QLabel(address)
    code.setObjectName("Code")
    code.setAlignment(Qt.AlignmentFlag.AlignCenter)
    code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(code)
    row = QHBoxLayout()
    copy_btn = button(t("hosting.copy"), None, "primary")

    def copy() -> None:
        QGuiApplication.clipboard().setText(address)
        copy_btn.setText(t("accounts.ms_copied"))

    copy_btn.clicked.connect(copy)
    row.addStretch()
    row.addWidget(copy_btn)
    row.addWidget(button(t("common.close"), dialog.accept))
    layout.addLayout(row)
    dialog.exec()

