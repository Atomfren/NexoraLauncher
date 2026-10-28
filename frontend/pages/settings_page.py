"""Глобальные настройки лаунчера."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from frontend.theme import apply_theme
from frontend.widgets import AppContext, Page, button, label, open_path, open_url, show_info
from shared.i18n import t
from shared.version import APP_NAME, APP_VERSION, SUPPORT_EMAIL, WEBSITE_URL

_AZURE_HELP = "https://learn.microsoft.com/entra/identity-platform/quickstart-register-app"


def _section(title: str) -> tuple[QFrame, QFormLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(18, 14, 18, 16)
    outer.addWidget(label(title, "SectionTitle"))
    form = QFormLayout()
    form.setSpacing(10)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    outer.addLayout(form)
    return frame, form


def _hint(text: str):
    """Пояснение с переносом строк; минимальная ширина — иначе форма резервирует лишнюю высоту."""
    hint = label(text, muted=True, wrap=True)
    hint.setMinimumWidth(360)
    return hint


class SettingsPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("settings.title"))
        self._system: dict = {}
        self._loaded: dict = {}

        general, form = _section(t("settings.general"))
        self.language = QComboBox()
        self.language.addItem("Русский", "ru")
        self.language.addItem("English", "en")
        form.addRow(t("settings.language"), self.language)
        self.theme = QComboBox()
        self.theme.addItem(t("settings.theme_dark"), "dark")
        self.theme.addItem(t("settings.theme_light"), "light")
        form.addRow(t("settings.theme"), self.theme)
        self.hide_on_launch = QCheckBox(t("settings.hide_on_launch"))
        form.addRow("", self.hide_on_launch)
        self.body.addWidget(general)

        java, form = _section(t("settings.java_memory"))
        mem_row = QHBoxLayout()
        self.memory_slider = QSlider(Qt.Orientation.Horizontal)
        self.memory_slider.setRange(1, 32)
        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(512, 65536)
        self.memory_spin.setSingleStep(512)
        self.memory_spin.setSuffix(" MB")
        self.memory_slider.valueChanged.connect(lambda v: self.memory_spin.setValue(v * 512))
        self.memory_spin.valueChanged.connect(self._sync_slider)
        mem_row.addWidget(self.memory_slider, 1)
        mem_row.addWidget(self.memory_spin)
        form.addRow(t("settings.memory"), mem_row)
        self.memory_hint = label("", muted=True)
        form.addRow("", self.memory_hint)
        self.min_memory = QSpinBox()
        self.min_memory.setRange(256, 65536)
        self.min_memory.setSingleStep(256)
        self.min_memory.setSuffix(" MB")
        form.addRow(t("settings.min_memory"), self.min_memory)

        java_row = QHBoxLayout()
        self.java_combo = QComboBox()
        self.java_combo.setEditable(True)
        self.java_combo.lineEdit().setPlaceholderText(t("settings.java_auto"))
        java_row.addWidget(self.java_combo, 1)
        java_row.addWidget(button(t("settings.detect_java"), self._detect_java))
        java_row.addWidget(button(t("common.browse"), self._browse_java))
        form.addRow("Java", java_row)
        form.addRow("", _hint(t("settings.java_hint")))
        self.jvm_args = QLineEdit()
        self.jvm_args.setPlaceholderText("-XX:+UseG1GC")
        form.addRow(t("settings.jvm_args"), self.jvm_args)
        self.body.addWidget(java)

        game, form = _section(t("settings.game"))
        res_row = QHBoxLayout()
        self.game_width = QSpinBox()
        self.game_width.setRange(320, 7680)
        self.game_height = QSpinBox()
        self.game_height.setRange(240, 4320)
        res_row.addWidget(self.game_width)
        res_row.addWidget(label("×"))
        res_row.addWidget(self.game_height)
        res_row.addStretch()
        form.addRow(t("settings.resolution"), res_row)
        self.fullscreen = QCheckBox(t("settings.fullscreen"))
        form.addRow("", self.fullscreen)
        self.body.addWidget(game)

        microsoft, form = _section(t("settings.microsoft"))
        self.ms_client_id = QLineEdit()
        self.ms_client_id.setPlaceholderText("00000000-0000-0000-0000-000000000000")
        form.addRow("Azure Client ID", self.ms_client_id)
        # Пояснение — вне формы: QFormLayout неверно считает высоту текста с переносами
        microsoft.layout().addWidget(label(t("settings.ms_hint"), muted=True, wrap=True))
        help_row = QHBoxLayout()
        help_row.addWidget(button(t("settings.ms_help"), lambda: open_url(_AZURE_HELP), "ghost"))
        help_row.addStretch()
        microsoft.layout().addLayout(help_row)
        self.body.addWidget(microsoft)

        folders, form = _section(t("settings.folders"))
        row = QHBoxLayout()
        row.addWidget(button(t("settings.open_data"), lambda: self._open("data_dir")))
        row.addWidget(button(t("settings.open_instances"), lambda: self._open("instances_dir")))
        row.addWidget(button(t("settings.open_logs"), lambda: self._open("logs_dir")))
        row.addStretch()
        form.addRow(row)
        self.body.addWidget(folders)

        about, form = _section(t("settings.about"))
        form.addRow(label(f"{APP_NAME} {APP_VERSION}", "CardTitle"))
        form.addRow(label(t("settings.about_text"), muted=True, wrap=True))
        self.check_updates = QCheckBox(t("settings.check_updates"))
        form.addRow(self.check_updates)
        links = QHBoxLayout()
        links.addWidget(button(t("update.check_now"), self._check_updates))
        # Не «GitHub»: код закрыт, ссылка на исходники обещала бы то, чего нет
        links.addWidget(button(t("q.website"), lambda: open_url(WEBSITE_URL), "ghost"))
        links.addWidget(button(t("q.support"),
                               lambda: open_url(f"mailto:{SUPPORT_EMAIL}"), "ghost"))
        links.addStretch()
        form.addRow(links)
        self.body.addWidget(about)

        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = button(t("common.save"), self._save, "primary")
        self.save_btn.setMinimumWidth(160)
        save_row.addWidget(self.save_btn)
        self.body.addLayout(save_row)
        self.body.addStretch()

    def on_show(self, first: bool) -> None:
        if first:
            self.run(lambda: (self.api.settings(), self.api.system_info()), self._fill)

    def apply_params(self, params: dict) -> None:
        if params.get("focus") == "ms_client_id":
            QTimer.singleShot(200, self.ms_client_id.setFocus)

    def _fill(self, data) -> None:
        settings, system = data
        self._loaded = settings
        self._system = system
        total = system.get("total_memory_mb", 8192)
        self.memory_slider.setRange(1, max(2, total // 512))
        self.memory_hint.setText(t("settings.memory_hint", total=total))
        self.language.setCurrentIndex(max(0, self.language.findData(settings["language"])))
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings["appearance_mode"])))
        self.hide_on_launch.setChecked(settings["hide_on_launch"])
        self.check_updates.setChecked(settings.get("check_updates", True))
        self.memory_spin.setValue(settings["max_memory"])
        self.min_memory.setValue(settings["min_memory"])
        self.java_combo.setEditText(settings["java_path"])
        self.jvm_args.setText(settings["jvm_args"])
        self.game_width.setValue(settings["game_width"])
        self.game_height.setValue(settings["game_height"])
        self.fullscreen.setChecked(settings["fullscreen"])
        self.ms_client_id.setText(settings["ms_client_id"])

    def _sync_slider(self, value: int) -> None:
        self.memory_slider.blockSignals(True)
        self.memory_slider.setValue(max(1, value // 512))
        self.memory_slider.blockSignals(False)

    def _detect_java(self) -> None:
        self.java_combo.clear()
        self.java_combo.addItem(t("common.loading"))

        def show(found: list[dict]) -> None:
            current = self._loaded.get("java_path", "")
            self.java_combo.clear()
            self.java_combo.addItem(t("settings.java_auto"), "")
            for java in found:
                self.java_combo.addItem(f"Java {java['major']} · {java['vendor']} · {java['path']}", java["path"])
            self.java_combo.setEditText(current)
            if not found:
                show_info(self, t("settings.java_none"))

        self.run(self.api.detect_java, show)

    def _browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Java", "", "Java (java.exe javaw.exe java)")
        if path:
            self.java_combo.setEditText(path)

    def _java_value(self) -> str:
        text = self.java_combo.currentText().strip()
        index = self.java_combo.findText(text)
        if index >= 0 and self.java_combo.itemData(index) is not None:
            return self.java_combo.itemData(index)
        return "" if text == t("settings.java_auto") else text

    def _check_updates(self) -> None:
        from frontend.dialogs.update_dialog import check_for_updates
        check_for_updates(self.ctx, self.window())

    def _open(self, key: str) -> None:
        if self._system.get(key):
            open_path(self._system[key])

    def _save(self) -> None:
        changes = {
            "language": self.language.currentData(),
            "appearance_mode": self.theme.currentData(),
            "hide_on_launch": self.hide_on_launch.isChecked(),
            "check_updates": self.check_updates.isChecked(),
            "max_memory": self.memory_spin.value(),
            "min_memory": min(self.min_memory.value(), self.memory_spin.value()),
            "java_path": self._java_value(),
            "jvm_args": self.jvm_args.text().strip(),
            "game_width": self.game_width.value(),
            "game_height": self.game_height.value(),
            "fullscreen": self.fullscreen.isChecked(),
            "ms_client_id": self.ms_client_id.text().strip(),
        }
        language_changed = self._loaded and changes["language"] != self._loaded.get("language")

        def saved(settings: dict) -> None:
            self._loaded = settings
            self.ctx.settings = settings
            self.ctx.settings_changed.emit(settings)
            apply_theme(QApplication.instance(), settings["appearance_mode"])
            self.save_btn.setText(t("common.saved"))
            QTimer.singleShot(1500, lambda: self.save_btn.setText(t("common.save")))
            if language_changed:
                show_info(self, t("settings.restart_required"))

        self.run(lambda: self.api.update_settings(**changes), saved)
