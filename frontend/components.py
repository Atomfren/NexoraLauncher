"""Переиспользуемые компоненты: запуск инстанса, карточка инстанса."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QVBoxLayout, QWidget

from frontend.services.api_client import ApiError
from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    Card,
    ask_text,
    badge,
    button,
    confirm,
    format_date,
    format_duration,
    label,
    open_path,
    set_variant,
    show_error,
    show_info,
)
from shared.i18n import t

LOADER_TITLES = {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt", "forge": "Forge",
                 "neoforge": "NeoForge"}


def loader_title(instance: dict) -> str:
    return LOADER_TITLES.get(instance.get("mod_loader", "vanilla"), instance.get("mod_loader", ""))


def launch_instance(ctx: AppContext, parent: QWidget, name: str, on_finished=None,
                    server: str = "", port: int = 25565) -> None:
    """Запуск инстанса; при отсутствии аккаунта предлагает его добавить."""

    def finish(ok: bool) -> None:
        ctx.instances_changed.emit()
        if on_finished:
            on_finished(ok)

    def fail_task(message: str) -> None:
        finish(False)
        show_error(parent, message, t("launch.failed"))

    def call():
        try:
            return ctx.api.launch_instance(name, server, port)
        except ApiError as e:
            if e.status_code == 401:
                return {"auth_required": str(e)}
            raise

    def started(task: dict) -> None:
        if "auth_required" in task:
            if on_finished:
                on_finished(False)
            ask_add_account(ctx, parent, task["auth_required"])
            return
        ctx.tracker.track(task, lambda _t: finish(True), fail_task)

    def fail(message: str) -> None:
        if on_finished:
            on_finished(False)
        show_error(parent, message, t("launch.failed"))

    run_async(call, started, fail, owner=parent)


def ask_add_account(ctx: AppContext, parent: QWidget, message: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(t("launch.failed"))
    box.setText(message)
    go = box.addButton(t("launch.add_account"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(t("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is go:
        ctx.navigate.emit("accounts", {})


def stop_instance(ctx: AppContext, parent: QWidget, pid: int) -> None:
    run_async(lambda: ctx.api.stop_process(pid), lambda _r: ctx.instances_changed.emit(),
              lambda msg: show_error(parent, msg), owner=parent)


class InstanceCard(Card):
    """Карточка инстанса с кнопкой «Играть/Остановить» и меню действий."""

    def __init__(self, ctx: AppContext, instance: dict, parent: QWidget | None = None, compact: bool = False):
        super().__init__(parent)
        self.ctx = ctx
        self.instance = instance
        self.name = instance["name"]

        icon = QLabel(loader_title(instance)[:1])
        icon.setObjectName("Badge")
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.layout_.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(label(self.name, "CardTitle"))
        if instance.get("running_pid"):
            title_row.addWidget(badge(t("instance.running"), "success"))
        elif not instance.get("installed"):
            title_row.addWidget(badge(t("instance.not_installed")))
        title_row.addStretch()
        info.addLayout(title_row)
        meta = f"{loader_title(instance)} {instance['version']}"
        if instance.get("mod_loader") != "vanilla" and instance.get("loader_version"):
            meta += f" ({instance['loader_version']})"
        if instance.get("optifine"):
            meta += " + OptiFine"
        if not compact:
            meta += "  ·  " + t("instance.played", time=format_duration(instance.get("total_play_seconds", 0)))
            meta += "  ·  " + t("instance.last_played", date=format_date(instance.get("last_played", "")))
        info.addWidget(label(meta, muted=True, shrink=True))
        self.layout_.addLayout(info, 1)

        self.play_btn = button("", self._on_play)
        self.play_btn.setMinimumWidth(110)
        self._update_play_button()
        self.layout_.addWidget(self.play_btn)

        if not compact:
            self.layout_.addWidget(button("⚙", self._open_settings, "ghost", t("instance.settings")))
            more = button("⋯", None, "ghost", t("instance.more"))
            more.setMenu(self._build_menu())
            self.layout_.addWidget(more)

    def _update_play_button(self) -> None:
        if self.instance.get("running_pid"):
            self.play_btn.setText(t("instance.stop"))
            set_variant(self.play_btn, "stop")
        else:
            self.play_btn.setText(t("instance.play"))
            set_variant(self.play_btn, "play")

    def _on_play(self) -> None:
        pid = self.instance.get("running_pid")
        if pid:
            if confirm(self, t("instance.stop_confirm", name=self.name)):
                stop_instance(self.ctx, self, pid)
            return
        self.play_btn.setEnabled(False)
        self.play_btn.setText(t("instance.launching"))

        def finished(_ok: bool) -> None:
            import shiboken6
            if shiboken6.isValid(self.play_btn):
                self.play_btn.setEnabled(True)
                self._update_play_button()

        launch_instance(self.ctx, self, self.name, finished)

    def _open_settings(self, initial_tab: str = "settings") -> None:
        from frontend.dialogs.instance_dialog import InstanceDialog
        InstanceDialog(self.ctx, self.name, self.window(), initial_tab=initial_tab).exec()
        self.ctx.instances_changed.emit()

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(t("instance.open_folder"), lambda: open_path(self.instance["game_dir"]))
        menu.addAction(t("instance.mods"), lambda: self._open_settings("mod"))
        menu.addAction(t("instance.logs"), lambda: self._open_settings("logs"))
        menu.addSeparator()
        menu.addAction(t("friends.menu"), self._play_with_friends)
        menu.addAction(t("instance.doctor"), lambda: self._open_settings("doctor"))
        menu.addAction(t("instance.turbo"), self._turbo)
        menu.addAction("OptiFine", self._optifine)
        menu.addAction(t("instance.updates"), self._updates)
        menu.addAction(t("instance.snapshots"), lambda: self._open_settings("snapshots"))
        menu.addAction(t("instance.share"), self._share)
        menu.addSeparator()
        menu.addAction(t("instance.rename"), self._rename)
        menu.addAction(t("instance.duplicate"), self._duplicate)
        menu.addAction(t("instance.export"), self._export)
        menu.addAction(t("instance.repair"), self._repair)
        menu.addSeparator()
        menu.addAction(t("instance.delete"), self._delete)
        return menu

    def _api_call(self, fn, on_done=None) -> None:
        def done(result):
            self.ctx.instances_changed.emit()
            if on_done:
                on_done(result)

        run_async(fn, done, lambda msg: show_error(self.window(), msg), owner=self.ctx)

    def _rename(self) -> None:
        new_name = ask_text(self, t("instance.rename"), t("instance.new_name"), self.name)
        if new_name and new_name != self.name:
            self._api_call(lambda: self.ctx.api.rename_instance(self.name, new_name))

    def _duplicate(self) -> None:
        new_name = ask_text(self, t("instance.duplicate"), t("instance.new_name"), f"{self.name} (2)")
        if new_name:
            self._api_call(lambda: self.ctx.api.duplicate_instance(self.name, new_name))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("instance.export"), f"{self.name}.zip", "ZIP (*.zip)")
        if not path:
            return
        window, ctx = self.window(), self.ctx

        def started(task: dict) -> None:
            ctx.tracker.track(task, lambda _t: show_info(window, t("instance.exported", path=path)),
                              lambda msg: show_error(window, msg))

        run_async(lambda: ctx.api.export_instance(self.name, path), started,
                  lambda msg: show_error(window, msg), owner=ctx)

    def _play_with_friends(self) -> None:
        """Ставит туннель e4mc и запускает игру; адрес появится после «Открыть для сети»."""
        window, ctx, name = self.window(), self.ctx, self.name

        def ready(_task: dict) -> None:
            show_info(window, t("friends.instructions"), t("friends.title"))
            launch_instance(ctx, window, name)

        run_async(lambda: ctx.api.prepare_friends(name),
                  lambda task: ctx.tracker.track(task, ready, lambda msg: show_error(window, msg)),
                  lambda msg: show_error(window, msg), owner=ctx)

    def _optifine(self) -> None:
        from frontend.dialogs.optifine_dialog import OptiFineDialog
        OptiFineDialog(self.ctx, self.instance, self.window()).exec()

    def _turbo(self) -> None:
        from frontend.dialogs.smart_dialogs import TurboDialog
        TurboDialog(self.ctx, self.name, self.window()).exec()

    def _updates(self) -> None:
        from frontend.dialogs.smart_dialogs import UpdatesDialog
        UpdatesDialog(self.ctx, self.name, self.window()).exec()

    def _share(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("instance.share"), f"{self.name}.mrpack",
                                              "Modrinth (*.mrpack)")
        if not path:
            return
        window, ctx = self.window(), self.ctx

        def done(task: dict) -> None:
            result = task.get("result") or {}
            show_info(window, t("instance.shared", path=path, linked=result.get("linked", 0),
                                embedded=result.get("embedded", 0)))

        run_async(lambda: ctx.api.export_mrpack(self.name, path),
                  lambda task: ctx.tracker.track(task, done, lambda msg: show_error(window, msg)),
                  lambda msg: show_error(window, msg), owner=ctx)

    def _repair(self) -> None:
        window, ctx = self.window(), self.ctx

        def started(task: dict) -> None:
            ctx.tracker.track(task, lambda _t: show_info(window, t("instance.repaired")),
                              lambda msg: show_error(window, msg))

        run_async(lambda: ctx.api.prepare_instance(self.name, force=True), started,
                  lambda msg: show_error(window, msg), owner=ctx)

    def _delete(self) -> None:
        if confirm(self, t("instance.delete_confirm", name=self.name)):
            self._api_call(lambda: self.ctx.api.delete_instance(self.name))

