"""Диалог инстанса: настройки, контент, миры, логи."""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.components import loader_title
from frontend.dialogs.create_instance_dialog import LOADERS
from frontend.panels import ContentPanel, WorldsPanel
from frontend.smart_panels import DoctorPanel, SnapshotsPanel
from frontend.utils.worker import run_async
from frontend.widgets import AppContext, button, label, open_path, show_error
from shared.i18n import t

_TABS = ["settings", "doctor", "mod", "resourcepack", "shader", "worlds", "snapshots", "logs"]


class InstanceDialog(QDialog):
    """Все действия с одним инстансом."""

    def __init__(self, ctx: AppContext, name: str, parent=None, initial_tab: str = "settings"):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self.name = name
        self.instance: dict | None = None
        self._initial_tab = initial_tab
        self.setWindowTitle(name)
        self.resize(1000, 680)
        layout = QVBoxLayout(self)
        self.header = label(name, "PageTitle")
        self.subheader = label("", muted=True, shrink=True)
        layout.addWidget(self.header)
        layout.addWidget(self.subheader)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.log_view = None
        run_async(lambda: self.api.instance(name), self._build, lambda msg: (show_error(self, msg), self.reject()),
                  owner=self)

    def _build(self, instance: dict) -> None:
        self.instance = instance
        self.subheader.setText(f"{loader_title(instance)} {instance['version']}  ·  {instance['game_dir']}")
        self.tabs.addTab(self._settings_tab(), t("instance.tab_settings"))
        self.tabs.addTab(DoctorPanel(self.ctx, instance), t("instance.tab_doctor"))
        if instance["mod_loader"] != "vanilla":
            self.tabs.addTab(ContentPanel(self.ctx, instance, "mod", on_browse=self.accept), t("instance.tab_mods"))
        else:
            self.tabs.addTab(self._vanilla_mods_hint(), t("instance.tab_mods"))
        self.tabs.addTab(ContentPanel(self.ctx, instance, "resourcepack", on_browse=self.accept),
                         t("instance.tab_resourcepacks"))
        self.tabs.addTab(ContentPanel(self.ctx, instance, "shader", on_browse=self.accept),
                         t("instance.tab_shaders"))
        self.tabs.addTab(WorldsPanel(self.ctx, instance), t("instance.tab_worlds"))
        self.tabs.addTab(SnapshotsPanel(self.ctx, instance), t("instance.tab_snapshots"))
        self.tabs.addTab(self._logs_tab(), t("instance.tab_logs"))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        if self._initial_tab in _TABS:
            self.tabs.setCurrentIndex(_TABS.index(self._initial_tab))
        self._on_tab_changed(self.tabs.currentIndex())

    # --- Настройки --------------------------------------------------------------
    def _settings_tab(self) -> QWidget:
        inst = self.instance
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        self.version_edit = QLineEdit(inst["version"])
        form.addRow(t("create.version"), self.version_edit)
        self.loader_combo = QComboBox()
        for key, title in LOADERS:
            self.loader_combo.addItem(title, key)
        self.loader_combo.setCurrentIndex(self.loader_combo.findData(inst["mod_loader"]))
        form.addRow(t("create.loader"), self.loader_combo)
        self.loader_version_edit = QLineEdit(inst.get("loader_version", ""))
        self.loader_version_edit.setPlaceholderText(t("instance.loader_latest"))
        form.addRow(t("create.loader_version"), self.loader_version_edit)
        form.addRow("", label(t("instance.version_hint"), muted=True, wrap=True))

        self.memory_override = QCheckBox(t("instance.override_memory"))
        self.max_memory = QSpinBox()
        self.max_memory.setRange(512, 65536)
        self.max_memory.setSingleStep(512)
        self.max_memory.setSuffix(" MB")
        self.max_memory.setValue(inst["max_memory"] or self.ctx.settings.get("max_memory", 4096))
        self.memory_override.setChecked(bool(inst["max_memory"]))
        self.max_memory.setEnabled(bool(inst["max_memory"]))
        self.memory_override.toggled.connect(self.max_memory.setEnabled)
        row = QHBoxLayout()
        row.addWidget(self.memory_override)
        row.addWidget(self.max_memory)
        row.addStretch()
        form.addRow(t("settings.memory"), row)

        java_row = QHBoxLayout()
        self.java_edit = QLineEdit(inst["java_path"])
        self.java_edit.setPlaceholderText(t("instance.java_default"))
        java_row.addWidget(self.java_edit, 1)
        java_row.addWidget(button(t("common.browse"), self._browse_java))
        form.addRow("Java", java_row)

        self.jvm_args = QLineEdit(inst["jvm_args"])
        self.jvm_args.setPlaceholderText(t("instance.jvm_args_default"))
        form.addRow(t("settings.jvm_args"), self.jvm_args)

        res_row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(0, 7680)
        self.width_spin.setSpecialValueText(t("instance.default"))
        self.width_spin.setValue(inst["width"])
        self.height_spin = QSpinBox()
        self.height_spin.setRange(0, 4320)
        self.height_spin.setSpecialValueText(t("instance.default"))
        self.height_spin.setValue(inst["height"])
        self.fullscreen = QCheckBox(t("settings.fullscreen"))
        self.fullscreen.setChecked(inst["fullscreen"])
        res_row.addWidget(self.width_spin)
        res_row.addWidget(label("×"))
        res_row.addWidget(self.height_spin)
        res_row.addWidget(self.fullscreen)
        res_row.addStretch()
        form.addRow(t("settings.resolution"), res_row)

        buttons = QHBoxLayout()
        buttons.addWidget(button(t("common.open_folder"), lambda: open_path(inst["game_dir"])))
        buttons.addStretch()
        self.save_btn = button(t("common.save"), self._save, "primary")
        buttons.addWidget(self.save_btn)
        form.addRow(buttons)
        return page

    def _browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Java", "", "Java (java.exe javaw.exe java)")
        if path:
            self.java_edit.setText(path)

    def _save(self) -> None:
        changes = {
            "version": self.version_edit.text().strip() or self.instance["version"],
            "mod_loader": self.loader_combo.currentData(),
            "loader_version": self.loader_version_edit.text().strip(),
            "max_memory": self.max_memory.value() if self.memory_override.isChecked() else 0,
            "java_path": self.java_edit.text().strip(),
            "jvm_args": self.jvm_args.text().strip(),
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "fullscreen": self.fullscreen.isChecked(),
        }
        self.save_btn.setEnabled(False)

        def saved(instance: dict) -> None:
            self.save_btn.setEnabled(True)
            self.instance = instance
            self.subheader.setText(f"{loader_title(instance)} {instance['version']}  ·  {instance['game_dir']}")
            self.ctx.instances_changed.emit()
            self.save_btn.setText(t("common.saved"))
            QTimer.singleShot(1500, lambda: self.save_btn.setText(t("common.save")))

        def failed(message: str) -> None:
            self.save_btn.setEnabled(True)
            show_error(self, message)

        run_async(lambda: self.api.update_instance(self.name, **changes), saved, failed, owner=self)

    def _vanilla_mods_hint(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = label(t("instance.vanilla_mods_hint"), "Empty", wrap=True)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    # --- Логи ----------------------------------------------------------------------
    def _logs_tab(self) -> QWidget:
        from frontend.smart_log import SmartLogView
        self.log_view = SmartLogView(self.ctx, self.instance, self)
        return self.log_view

    def _on_tab_changed(self, index: int) -> None:
        if self.log_view is None:
            return
        if 0 <= index < len(_TABS) and _TABS[index] == "logs":
            self.log_view.activate()
        else:
            self.log_view.deactivate()

    def done(self, result: int) -> None:  # noqa: D401 — остановка таймера при закрытии
        if self.log_view is not None:
            self.log_view.deactivate()
        super().done(result)
