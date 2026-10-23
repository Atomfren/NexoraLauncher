"""Диалоги «Турбо» и «Обновления модов»."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import AppContext, button, label, show_error, show_info
from shared.i18n import t


class TurboDialog(QDialog):
    """Показывает план «Турбо» и применяет его."""

    def __init__(self, ctx: AppContext, instance_name: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.name = instance_name
        self.setWindowTitle(t("turbo.title"))
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        layout.setSpacing(10)
        layout.addWidget(label("🚀 " + t("turbo.title"), "PageTitle"))
        self.info = label(t("common.loading"), muted=True, wrap=True)
        layout.addWidget(self.info)
        self.mods = label("", wrap=True)
        layout.addWidget(self.mods)
        self.tune = QCheckBox()
        self.tune.setChecked(True)
        layout.addWidget(self.tune)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button(t("common.cancel"), self.reject))
        self.apply_btn = button(t("turbo.apply"), self._apply, "primary")
        self.apply_btn.setEnabled(False)
        row.addWidget(self.apply_btn)
        layout.addLayout(row)
        run_async(lambda: ctx.api.turbo_plan(instance_name), self._show, self._fail, owner=self)

    def _fail(self, message: str) -> None:
        self.info.setText(message)

    def _show(self, plan: dict) -> None:
        self.info.setText(t("turbo.intro"))
        self.mods.setText(t("turbo.mods", mods=", ".join(plan["mods"])) if plan["mods"] else t("turbo.no_mods"))
        self.tune.setText(t("turbo.tune", memory=plan["max_memory"]))
        self.apply_btn.setEnabled(True)
        self.adjustSize()

    def _apply(self) -> None:
        self.apply_btn.setEnabled(False)
        self.apply_btn.setText(t("browse.installing"))
        tune = self.tune.isChecked()

        def done(task: dict) -> None:
            result = task.get("result") or {}
            self.ctx.instances_changed.emit()
            installed = ", ".join(result.get("installed", [])) or "—"
            show_info(self.parentWidget(), t("turbo.done", installed=installed))

        def started(task: dict) -> None:
            self.ctx.tracker.track(task, done, lambda msg: show_error(self.parentWidget(), msg))
            self.accept()

        run_async(lambda: self.ctx.api.apply_turbo(self.name, tune), started,
                  lambda msg: (show_error(self, msg), self.apply_btn.setEnabled(True)), owner=self)


class UpdatesDialog(QDialog):
    """Проверка и установка обновлений модов."""

    def __init__(self, ctx: AppContext, instance_name: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.name = instance_name
        self.setWindowTitle(t("updates.title"))
        self.resize(560, 480)
        layout = QVBoxLayout(self)
        self.info = label(t("updates.checking"), muted=True, wrap=True)
        layout.addWidget(self.info)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button(t("common.close"), self.reject))
        self.apply_btn = button(t("updates.apply"), self._apply, "primary")
        self.apply_btn.setEnabled(False)
        row.addWidget(self.apply_btn)
        layout.addLayout(row)

        def fetch():
            ctx.api.identify_mods(instance_name)
            return ctx.api.mod_updates(instance_name)

        run_async(fetch, self._show, lambda msg: self.info.setText(msg), owner=self)

    def _show(self, updates: list[dict]) -> None:
        if not updates:
            self.info.setText("✅ " + t("updates.none"))
            return
        self.info.setText(t("updates.found", n=len(updates)))
        for update in updates:
            item = QListWidgetItem(f"{update['name']}:  {update['current_version']}  →  {update['new_version']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, update["version_id"])
            self.list.addItem(item)
        self.apply_btn.setEnabled(True)

    def _apply(self) -> None:
        ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
               if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if not ids:
            return
        self.apply_btn.setEnabled(False)
        parent = self.parentWidget()

        def done(task: dict) -> None:
            result = task.get("result") or {}
            failed = result.get("failed") or []
            message = t("updates.done", n=len(result.get("updated", [])))
            if failed:
                message += "\n" + t("updates.failed", names=", ".join(f["name"] for f in failed))
            self.ctx.instances_changed.emit()
            show_info(parent, message)

        def started(task: dict) -> None:
            self.ctx.tracker.track(task, done, lambda msg: show_error(parent, msg))
            self.accept()

        run_async(lambda: self.ctx.api.apply_mod_updates(self.name, ids), started,
                  lambda msg: show_error(self, msg), owner=self)
