"""OptiFine для инстанса: выбор версии на optifine.net, поиск скачанного файла, установка."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import AppContext, button, confirm, label, open_url, show_error, show_info
from shared.i18n import t

_POLL_MS = 2000


class OptiFineDialog(QDialog):
    """Файл OptiFine нельзя скачивать в обход сайта автора, поэтому лаунчер открывает страницу
    загрузки и сам подхватывает скачанный файл из папки «Загрузки»."""

    def __init__(self, ctx: AppContext, instance: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.instance = instance
        self.name = instance["name"]
        self.mc_version = instance["version"]
        self.found: dict | None = None
        self.setWindowTitle(t("optifine.title", name=self.name))
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        self.status = label("", "CardTitle", wrap=True)
        layout.addWidget(self.status)
        self.intro = label("", muted=True, wrap=True)
        layout.addWidget(self.intro)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._open_page())
        layout.addWidget(self.list, 1)
        self.found_label = label(t("optifine.waiting"), muted=True, wrap=True)
        layout.addWidget(self.found_label)

        row = QHBoxLayout()
        self.page_btn = button(t("optifine.open_page"), self._open_page)
        row.addWidget(self.page_btn)
        self.choose_btn = button(t("optifine.choose_file"), self._choose_file, "ghost")
        row.addWidget(self.choose_btn)
        row.addStretch()
        self.remove_btn = button(t("optifine.remove"), self._remove, "danger")
        row.addWidget(self.remove_btn)
        self.install_btn = button(t("optifine.install"), self._install_found, "primary")
        self.install_btn.setEnabled(False)
        row.addWidget(self.install_btn)
        layout.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._scan_downloads)
        run_async(lambda: ctx.api.optifine_status(self.name), self._on_status,
                  lambda msg: show_error(self, msg), owner=self)

    # --- Состояние --------------------------------------------------------------------------
    def _on_status(self, status: dict) -> None:
        self.remove_btn.setVisible(status["installed"])
        if status["installed"]:
            self.status.setText(t("optifine.installed", edition=status["edition"].replace("_", " ")))
        else:
            self.status.setText(t("optifine.not_installed"))
        if not status["supported"]:
            self._show_alternative()
            return
        self.intro.setText(t("optifine.intro", version=self.mc_version))
        self.list.addItem(t("common.loading"))
        run_async(lambda: self.ctx.api.optifine_versions(self.mc_version), self._fill,
                  lambda msg: (self.list.clear(), self.list.addItem(msg)), owner=self)
        self._timer.start()
        self._scan_downloads()

    def _show_alternative(self) -> None:
        """Fabric / Quilt / NeoForge: OptiFine недоступен — предлагаем Sodium + Iris."""
        self.intro.setText(t("optifine.unsupported"))
        self.list.hide()
        self.found_label.hide()
        self.page_btn.hide()
        self.choose_btn.hide()
        self.install_btn.setText(t("optifine.install_alternative"))
        self.install_btn.setEnabled(self.instance["mod_loader"] in ("fabric", "quilt", "neoforge"))
        self.install_btn.clicked.disconnect()
        self.install_btn.clicked.connect(self._install_alternative)
        self.layout().insertStretch(3, 1)
        self.resize(560, 240)

    def _fill(self, versions: list[dict]) -> None:
        self.list.clear()
        if not versions:
            item = QListWidgetItem(t("optifine.no_versions", version=self.mc_version))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
            self.page_btn.setEnabled(False)
            return
        for version in versions:
            text = version["title"]
            if version["preview"]:
                text += "  ·  " + t("optifine.preview")
            if version["forge"] and version["forge"] != "N/A":
                text += "  ·  Forge " + version["forge"]
            text += "  ·  " + version["date"]
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, version)
            self.list.addItem(item)
        stable = next((i for i in range(self.list.count())
                       if not self.list.item(i).data(Qt.ItemDataRole.UserRole)["preview"]), 0)
        self.list.setCurrentRow(stable)

    # --- Скачивание и установка ---------------------------------------------------------------
    def _open_page(self) -> None:
        item = self.list.currentItem()
        version = item.data(Qt.ItemDataRole.UserRole) if item else None
        if version:
            open_url(version["page_url"])
            self.found_label.setText(t("optifine.waiting_file", file=version["filename"]))

    def _scan_downloads(self) -> None:
        def show(files: list[dict]) -> None:
            if not files:
                return
            self.found = files[0]
            self.found_label.setText(t("optifine.found", file=self.found["filename"]))
            self.install_btn.setEnabled(True)

        run_async(lambda: self.ctx.api.optifine_downloaded(self.mc_version), show, lambda _m: None, owner=self)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("optifine.choose_file"), "", "OptiFine (*.jar)")
        if path:
            self._install(path)

    def _install_found(self) -> None:
        if self.found:
            self._install(self.found["path"])

    def _install(self, path: str) -> None:
        self._timer.stop()
        self.install_btn.setEnabled(False)
        ctx, parent = self.ctx, self.parent()

        def done(_task: dict) -> None:
            ctx.instances_changed.emit()
            show_info(parent, t("optifine.done", name=self.name))

        run_async(lambda: ctx.api.install_optifine(self.name, path),
                  lambda task: (ctx.tracker.track(task, done, lambda msg: show_error(parent, msg)), self.accept()),
                  lambda msg: (show_error(self, msg), self.install_btn.setEnabled(True), self._timer.start()),
                  owner=ctx)

    def _install_alternative(self) -> None:
        ctx, parent, name = self.ctx, self.parent(), self.name
        run_async(lambda: ctx.api.install_content(name, "mod", "iris"),
                  lambda task: (ctx.tracker.track(task, lambda _t: (ctx.instances_changed.emit(),
                                                                    show_info(parent, t("optifine.alternative_done"))),
                                                  lambda msg: show_error(parent, msg)), self.accept()),
                  lambda msg: show_error(self, msg), owner=ctx)

    def _remove(self) -> None:
        if confirm(self, t("optifine.remove_confirm", name=self.name)):
            run_async(lambda: self.ctx.api.remove_optifine(self.name),
                      lambda _r: (self.ctx.instances_changed.emit(), self.accept()),
                      lambda msg: show_error(self, msg), owner=self.ctx)

    def done(self, result: int) -> None:
        self._timer.stop()
        super().done(result)
