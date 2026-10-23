"""Импорт сборок из Prism Launcher, MultiMC и CurseForge."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import AppContext, button, label, show_error
from shared.i18n import t

_SOURCES = {"prism": "Prism Launcher", "multimc": "MultiMC", "curseforge": "CurseForge"}
_LOADERS = {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt", "forge": "Forge", "neoforge": "NeoForge"}


class ForeignImportDialog(QDialog):
    """Найденные сборки других лаунчеров + выбор папки вручную. Результат — путь к папке."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.selected_path = ""
        self.setWindowTitle(t("foreign.title"))
        self.resize(640, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(label(t("foreign.intro"), muted=True, wrap=True))
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._accept_selected())
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(t("foreign.browse"), self._browse))
        row.addStretch()
        row.addWidget(button(t("common.cancel"), self.reject))
        self.import_btn = button(t("foreign.import"), self._accept_selected, "primary")
        self.import_btn.setEnabled(False)
        row.addWidget(self.import_btn)
        layout.addLayout(row)
        self.list.currentItemChanged.connect(
            lambda item, _prev: self.import_btn.setEnabled(bool(item and item.data(Qt.ItemDataRole.UserRole))))
        self.list.addItem(t("common.loading"))
        run_async(ctx.api.foreign_instances, self._fill, lambda msg: show_error(self, msg), owner=self)

    def _fill(self, found: list[dict]) -> None:
        self.list.clear()
        if not found:
            item = QListWidgetItem(t("foreign.none"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
            return
        for info in found:
            loader = _LOADERS.get(info["mod_loader"], info["mod_loader"])
            text = f"{info['name']}   ·   {loader} {info['version']}   ·   {_SOURCES.get(info['source'], '')}"
            item = QListWidgetItem(text)
            item.setToolTip(info["path"])
            item.setData(Qt.ItemDataRole.UserRole, info["path"])
            self.list.addItem(item)
        self.list.setCurrentRow(0)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("foreign.browse"))
        if path:
            self.selected_path = path
            self.accept()

    def _accept_selected(self) -> None:
        item = self.list.currentItem()
        path = item.data(Qt.ItemDataRole.UserRole) if item else ""
        if path:
            self.selected_path = path
            self.accept()
