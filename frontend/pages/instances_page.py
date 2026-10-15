"""Страница инстансов."""

from PyQt6.QtWidgets import QFileDialog, QLineEdit, QMenu

from frontend.components import InstanceCard
from frontend.dialogs.create_instance_dialog import CreateInstanceDialog
from frontend.widgets import AppContext, Page, button, clear_layout, show_error
from shared.i18n import t


class InstancesPage(Page):
    """Список инстансов, создание и импорт."""

    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("instances.title"), t("instances.subtitle"))
        self._instances: list[dict] = []
        import_btn = button(t("instances.import"))
        menu = QMenu(import_btn)
        menu.addAction(t("instances.import_file"), self._import)
        menu.addAction(t("instances.import_foreign"), self._import_foreign)
        import_btn.setMenu(menu)
        self.actions.addWidget(import_btn)
        self.actions.addWidget(button(t("instances.create"), self.create_instance, "primary"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("instances.search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render)
        self.toolbar.addWidget(self.search)
        ctx.instances_changed.connect(self.reload)

    def on_show(self, first: bool) -> None:
        self.reload()

    def reload(self) -> None:
        self.run(self.api.instances, self._on_loaded)

    def _on_loaded(self, instances: list[dict]) -> None:
        self._instances = instances
        self._render()

    def _render(self) -> None:
        query = self.search.text().strip().lower()
        items = [i for i in self._instances if query in i["name"].lower()]
        if not self._instances:
            self.set_empty(t("instances.empty"))
            return
        if not items:
            self.set_empty(t("common.nothing_found"))
            return
        clear_layout(self.body)
        for instance in items:
            self.body.addWidget(InstanceCard(self.ctx, instance))
        self.body.addStretch()

    def create_instance(self, version: str = "", loader: str = "vanilla") -> None:
        dialog = CreateInstanceDialog(self.ctx, self, version=version, loader=loader)
        if dialog.exec() and dialog.result_instance:
            name = dialog.result_instance["name"]
            self.run(lambda: self.api.prepare_instance(name), lambda task: self.track(task))
            self.reload()

    def apply_params(self, params: dict) -> None:
        if params.get("create"):
            self.create_instance(params.get("version", ""), params.get("loader", "vanilla"))

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("instances.import"), "",
                                              t("instances.import_filter"))
        if path:
            self._start_import(path)

    def _import_foreign(self) -> None:
        from frontend.dialogs.foreign_import_dialog import ForeignImportDialog
        dialog = ForeignImportDialog(self.ctx, self)
        if dialog.exec() and dialog.selected_path:
            self._start_import(dialog.selected_path)

    def _start_import(self, path: str) -> None:
        self.run(lambda: self.api.import_instance(path),
                 lambda task: self.track(task, lambda _t: self.reload(),
                                         lambda msg: show_error(self, msg, t("instances.import_failed"))))
