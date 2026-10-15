"""Диалог создания инстанса."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from frontend.utils.worker import run_async
from frontend.widgets import AppContext, label, show_error
from shared.i18n import t

LOADERS = [("vanilla", "Vanilla"), ("fabric", "Fabric"), ("quilt", "Quilt"),
           ("forge", "Forge"), ("neoforge", "NeoForge")]


class CreateInstanceDialog(QDialog):
    """Название, версия игры, загрузчик и его версия."""

    def __init__(self, ctx: AppContext, parent=None, version: str = "", loader: str = "vanilla"):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self._versions: list[dict] = []
        self._preset_version = version
        self.result_instance: dict | None = None
        self.setWindowTitle(t("create.title"))
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("create.name_placeholder"))
        self.name_edit.setMaxLength(64)
        form.addRow(t("create.name"), self.name_edit)

        self.version_combo = QComboBox()
        self.version_combo.addItem(t("common.loading"))
        self.version_combo.setEnabled(False)
        form.addRow(t("create.version"), self.version_combo)
        self.snapshots = QCheckBox(t("create.show_snapshots"))
        self.snapshots.toggled.connect(self._fill_versions)
        form.addRow("", self.snapshots)

        self.loader_combo = QComboBox()
        for key, title in LOADERS:
            self.loader_combo.addItem(title, key)
        self.loader_combo.setCurrentIndex(max(0, [k for k, _ in LOADERS].index(loader)))
        form.addRow(t("create.loader"), self.loader_combo)

        self.loader_version_combo = QComboBox()
        form.addRow(t("create.loader_version"), self.loader_version_combo)
        self.loader_hint = label("", muted=True, wrap=True)
        form.addRow("", self.loader_hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(t("create.submit"))
        self.ok_button.setProperty("variant", "primary")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.version_combo.currentIndexChanged.connect(self._on_target_changed)
        self.loader_combo.currentIndexChanged.connect(self._on_target_changed)
        run_async(self.api.available_versions, self._on_versions,
                  lambda msg: show_error(self, msg), owner=self)

    def _on_versions(self, versions: list[dict]) -> None:
        self._versions = versions
        if self._preset_version and any(v["id"] == self._preset_version and v["type"] != "release"
                                        for v in versions):
            self.snapshots.setChecked(True)
        self._fill_versions()

    def _fill_versions(self) -> None:
        if not self._versions:
            return
        current = self.version_combo.currentData() or self._preset_version
        show_all = self.snapshots.isChecked()
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for v in self._versions:
            if show_all or v["type"] == "release":
                suffix = "" if v["type"] == "release" else f"  ({v['type']})"
                self.version_combo.addItem(v["id"] + suffix, v["id"])
        index = self.version_combo.findData(current) if current else 0
        self.version_combo.setCurrentIndex(max(index, 0))
        self.version_combo.setEnabled(True)
        self.version_combo.blockSignals(False)
        self._on_target_changed()

    def _on_target_changed(self) -> None:
        loader = self.loader_combo.currentData()
        version = self.version_combo.currentData()
        self.loader_version_combo.clear()
        self.loader_hint.setText("")
        if not self.name_edit.isModified():
            if version:
                title = dict(LOADERS)[loader]
                self.name_edit.setText(f"{title} {version}" if loader != "vanilla" else version)
        if loader == "vanilla" or not version:
            self.loader_version_combo.setEnabled(False)
            self.ok_button.setEnabled(bool(version))
            return
        self.loader_version_combo.addItem(t("common.loading"))
        self.loader_version_combo.setEnabled(False)
        self.ok_button.setEnabled(False)

        def show(versions: list[str]) -> None:
            if self.loader_combo.currentData() != loader or self.version_combo.currentData() != version:
                return
            self.loader_version_combo.clear()
            if not versions:
                self.loader_hint.setText(t("create.loader_unsupported", loader=dict(LOADERS)[loader],
                                           version=version))
                return
            self.loader_version_combo.addItem(t("create.latest", version=versions[0]), "")
            for v in versions:
                self.loader_version_combo.addItem(v, v)
            self.loader_version_combo.setEnabled(True)
            self.ok_button.setEnabled(True)

        def fail(message: str) -> None:
            self.loader_version_combo.clear()
            self.loader_hint.setText(message)

        run_async(lambda: self.api.loader_versions(loader, version), show, fail, owner=self)

    def _submit(self) -> None:
        name = self.name_edit.text().strip()
        version = self.version_combo.currentData()
        if not name or not version:
            show_error(self, t("create.fill_fields"))
            return
        loader = self.loader_combo.currentData()
        loader_version = self.loader_version_combo.currentData() or ""
        self.ok_button.setEnabled(False)

        def created(instance: dict) -> None:
            self.result_instance = instance
            self.accept()

        def failed(message: str) -> None:
            self.ok_button.setEnabled(True)
            show_error(self, message)

        run_async(lambda: self.api.create_instance(name, version, loader, loader_version, install=False),
                  created, failed, owner=self)
