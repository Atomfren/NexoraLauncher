"""Версии Minecraft: список от Mojang, установка, создание инстанса."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from frontend.widgets import AppContext, Page, button, format_date, show_info
from shared.i18n import t

_TYPES = [("release", "versions.releases"), ("snapshot", "versions.snapshots"),
          ("old", "versions.old"), ("all", "versions.all")]


class VersionsPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("versions.title"), t("versions.subtitle"), scroll=False)
        self._versions: list[dict] = []
        self._installed: set[str] = set()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(t("versions.search"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._render)
        self.toolbar.addWidget(self.filter, 1)
        self.type_combo = QComboBox()
        for key, title in _TYPES:
            self.type_combo.addItem(t(title), key)
        self.type_combo.currentIndexChanged.connect(self._render)
        self.toolbar.addWidget(self.type_combo)
        self.actions.addWidget(button(t("common.refresh"), lambda: self.reload(True)))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([t("versions.version"), t("versions.type"),
                                              t("versions.released"), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        # Колонка с кнопками: таблица не учитывает размер встроенных виджетов
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 300)
        self.body.addWidget(self.table, 1)

    def on_show(self, first: bool) -> None:
        if first:
            self.reload()

    def reload(self, refresh: bool = False) -> None:
        def fetch():
            return self.api.available_versions(refresh), self.api.installed_versions()

        def done(data) -> None:
            available, installed = data
            self._versions = available
            self._installed = {v["id"] for v in installed}
            self._render()

        self.run(fetch, done)

    def _render(self) -> None:
        query = self.filter.text().strip().lower()
        kind = self.type_combo.currentData()
        rows = []
        for v in self._versions:
            if query and query not in v["id"].lower():
                continue
            if kind == "old" and v["type"] not in ("old_beta", "old_alpha"):
                continue
            if kind in ("release", "snapshot") and v["type"] != kind:
                continue
            rows.append(v)
        self.table.setRowCount(len(rows))
        for row, version in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(version["id"]))
            self.table.setItem(row, 1, QTableWidgetItem(version["type"]))
            self.table.setItem(row, 2, QTableWidgetItem(format_date(version["release_time"])[:10]))
            cell = QWidget()
            layout = QHBoxLayout(cell)
            layout.setContentsMargins(4, 0, 4, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignRight)
            if version["id"] in self._installed:
                layout.addWidget(button(t("versions.installed"), None, "ghost", small=True))
            else:
                layout.addWidget(button(t("versions.install"), lambda _=False, v=version["id"]: self._install(v),
                                        small=True))
            layout.addWidget(button(t("versions.create_instance"),
                                    lambda _=False, v=version["id"]: self.ctx.navigate.emit(
                                        "instances", {"create": True, "version": v}), "primary", small=True))
            self.table.setCellWidget(row, 3, cell)
            for btn in cell.findChildren(QPushButton):
                btn.setFixedHeight(30)
            self.table.setRowHeight(row, 48)

    def _install(self, version_id: str) -> None:
        def done(_task: dict) -> None:
            self._installed.add(version_id)
            self._render()
            show_info(self, t("versions.install_done", version=version_id))

        self.run(lambda: self.api.install_version(version_id), lambda task: self.track(task, done))
