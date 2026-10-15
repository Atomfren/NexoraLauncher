"""Панели контента инстанса: установленные моды/паки и миры."""

from html import escape
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    IconCache,
    button,
    confirm,
    format_date,
    format_size,
    label,
    open_path,
    show_error,
    show_info,
)
from shared.i18n import t

CONTENT_FOLDERS = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks"}
BROWSE_PAGES = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaders"}


def _fit_buttons(widget: QWidget) -> None:
    """Кнопки в ячейках таблицы: фиксированная высота, иначе отступы ячейки их обрезают."""
    for btn in ([widget] if isinstance(widget, QPushButton) else widget.findChildren(QPushButton)):
        btn.setFixedHeight(30)


class ContentPanel(QWidget):
    """Установленный контент одного типа в инстансе."""

    def __init__(self, ctx: AppContext, instance: dict, content_type: str, parent: QWidget | None = None,
                 on_browse=None):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self.instance = instance
        self.content_type = content_type
        self.on_browse = on_browse
        self._items: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("common.filter"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._render)
        bar.addWidget(self.filter, 1)
        bar.addWidget(button(t("content.browse"), self._browse, "primary"))
        if content_type == "mod":
            bar.addWidget(button(t("updates.button"), self._updates))
        bar.addWidget(button(t("content.add_file"), self._add_file))
        bar.addWidget(button("📂", self._open_folder, "ghost", t("common.open_folder")))
        bar.addWidget(button("⟳", self.reload, "ghost", t("common.refresh")))
        layout.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", t("content.name"), t("content.version"),
                                              t("content.size"), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (0, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        self.summary = label("", muted=True)
        layout.addWidget(self.summary)
        self.reload()

    def reload(self) -> None:
        run_async(lambda: self.api.installed_content(self.instance["name"], self.content_type),
                  self._on_loaded, lambda msg: show_error(self, msg), owner=self)

    def _on_loaded(self, items: list[dict]) -> None:
        self._items = items
        self._render()

    def _render(self) -> None:
        query = self.filter.text().strip().lower()
        items = [i for i in self._items if query in i["name"].lower() or query in i["filename"].lower()]
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            check = QCheckBox()
            check.setChecked(item["enabled"])
            check.setToolTip(t("content.enabled"))
            check.toggled.connect(lambda on, it=item: self._toggle(it, on))
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(8, 0, 4, 0)
            hl.addWidget(check)
            self.table.setCellWidget(row, 0, holder)

            name_widget = QWidget()
            nl = QHBoxLayout(name_widget)
            nl.setContentsMargins(4, 2, 4, 2)
            icon = QLabel()
            IconCache.load_into(icon, item.get("icon_url"), 28)
            nl.addWidget(icon)
            text = QLabel(f"<b>{escape(item['name'])}</b><br>"
                          f"<span style='font-size:11px'>{escape(item['filename'])}</span>")
            text.setTextFormat(Qt.TextFormat.RichText)
            nl.addWidget(text, 1)
            self.table.setCellWidget(row, 1, name_widget)
            self.table.setItem(row, 2, QTableWidgetItem(item.get("version_number") or "—"))
            self.table.setItem(row, 3, QTableWidgetItem(format_size(item["size"])))
            self.table.setCellWidget(row, 4, button("🗑", lambda _=False, it=item: self._remove(it),
                                                    "ghost", t("common.delete"), small=True))
            _fit_buttons(self.table.cellWidget(row, 4))
            self.table.setRowHeight(row, 50)
        enabled = sum(1 for i in self._items if i["enabled"])
        self.summary.setText(t("content.summary", total=len(self._items), enabled=enabled))

    def _toggle(self, item: dict, enabled: bool) -> None:
        run_async(lambda: self.api.toggle_content(self.instance["name"], self.content_type,
                                                  item["filename"], enabled),
                  lambda _r: self.reload(), lambda msg: (show_error(self, msg), self.reload()), owner=self)

    def _remove(self, item: dict) -> None:
        if confirm(self, t("content.remove_confirm", name=item["name"])):
            run_async(lambda: self.api.remove_content(self.instance["name"], self.content_type,
                                                      item["filename"]),
                      lambda _r: self.reload(), lambda msg: show_error(self, msg), owner=self)

    def _add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, t("content.add_file"), "", "Minecraft (*.jar *.zip)")
        for path in paths:
            run_async(lambda p=path: self.api.add_local_content(self.instance["name"], self.content_type, p),
                      lambda _r: self.reload(), lambda msg: show_error(self, msg), owner=self)

    def _open_folder(self) -> None:
        open_path(Path(self.instance["game_dir"]) / CONTENT_FOLDERS[self.content_type])

    def _updates(self) -> None:
        from frontend.dialogs.smart_dialogs import UpdatesDialog
        UpdatesDialog(self.ctx, self.instance["name"], self).exec()
        self.reload()

    def _browse(self) -> None:
        if self.on_browse:
            self.on_browse()
        self.ctx.navigate.emit(BROWSE_PAGES[self.content_type], {"instance": self.instance["name"]})


class WorldsPanel(QWidget):
    """Миры инстанса: импорт, экспорт, удаление."""

    def __init__(self, ctx: AppContext, instance: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self.instance = instance
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(button(t("worlds.import"), self._import, "primary"))
        bar.addWidget(button("📂", self._open_folder, "ghost", t("common.open_folder")))
        bar.addWidget(button("⟳", self.reload, "ghost", t("common.refresh")))
        layout.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t("worlds.name"), t("worlds.last_played"),
                                              t("content.size"), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        if instance:
            self.reload()

    def set_instance(self, instance: dict | None) -> None:
        self.instance = instance
        self.reload()

    def reload(self) -> None:
        if not self.instance:
            self.table.setRowCount(0)
            return
        name = self.instance["name"]
        run_async(lambda: self.api.worlds(name), self._render, lambda msg: show_error(self, msg), owner=self)

    def _render(self, worlds: list[dict]) -> None:
        self.table.setRowCount(len(worlds))
        for row, world in enumerate(worlds):
            self.table.setItem(row, 0, QTableWidgetItem(world["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(format_date(world["last_played"])))
            self.table.setItem(row, 2, QTableWidgetItem(format_size(world["size"])))
            actions = QWidget()
            al = QHBoxLayout(actions)
            al.setContentsMargins(4, 0, 4, 0)
            al.addWidget(button("📂", lambda _=False, w=world: open_path(w["path"]), "ghost",
                                t("common.open_folder"), small=True))
            al.addWidget(button("⬆", lambda _=False, w=world: self._export(w), "ghost", t("worlds.export"), small=True))
            al.addWidget(button("🗑", lambda _=False, w=world: self._delete(w), "ghost", t("common.delete"), small=True))
            self.table.setCellWidget(row, 3, actions)
            _fit_buttons(actions)
            self.table.setRowHeight(row, 48)

    def _import(self) -> None:
        if not self.instance:
            return
        path, _ = QFileDialog.getOpenFileName(self, t("worlds.import"), "", "ZIP (*.zip)")
        if path:
            name = self.instance["name"]
            run_async(lambda: self.api.import_world(name, path),
                      lambda r: (show_info(self, t("worlds.imported", name=r["name"])), self.reload()),
                      lambda msg: show_error(self, msg), owner=self)

    def _export(self, world: dict) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("worlds.export"), f"{world['name']}.zip", "ZIP (*.zip)")
        if path:
            name = self.instance["name"]
            run_async(lambda: self.api.export_world(name, world["name"], path),
                      lambda r: show_info(self, t("worlds.exported", path=r["path"])),
                      lambda msg: show_error(self, msg), owner=self)

    def _delete(self, world: dict) -> None:
        if confirm(self, t("worlds.delete_confirm", name=world["name"])):
            name = self.instance["name"]
            run_async(lambda: self.api.delete_world(name, world["name"]), lambda _r: self.reload(),
                      lambda msg: show_error(self, msg), owner=self)

    def _open_folder(self) -> None:
        if self.instance:
            open_path(Path(self.instance["game_dir"]) / "saves")
