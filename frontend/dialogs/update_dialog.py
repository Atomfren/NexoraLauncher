"""Обновление лаунчера: проверка, окно «Что нового», загрузка и перезапуск."""

from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import AppContext, button, confirm, format_size, label, open_url, show_error, show_info
from shared.i18n import t


class UpdateDialog(QDialog):
    """Новая версия: описание релиза и кнопка установки."""

    def __init__(self, ctx: AppContext, info: dict, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.info = info
        self.setWindowTitle(t("update.title"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(label(t("update.available", latest=info["latest"], current=info["current"]), "CardTitle",
                               wrap=True))
        notes = QPlainTextEdit(info["notes"] or t("update.no_notes"))
        notes.setReadOnly(True)
        layout.addWidget(notes, 1)
        if not info["can_install"]:
            layout.addWidget(label(t("update.manual_hint"), muted=True, wrap=True))
        row = QHBoxLayout()
        row.addWidget(button(t("update.release_page"), lambda: open_url(info["url"]), "ghost"))
        row.addStretch()
        row.addWidget(button(t("update.later"), self.reject))
        if info["can_install"]:
            size = f" ({format_size(info['size'])})" if info["size"] else ""
            self.install_btn = button(t("update.install") + size, self._install, "primary")
            row.addWidget(self.install_btn)
        layout.addLayout(row)

    def _install(self) -> None:
        self.install_btn.setEnabled(False)
        ctx, parent = self.ctx, self.parent()

        def downloaded(task: dict) -> None:
            path = (task.get("result") or {}).get("path", "")
            if not confirm(parent, t("update.ready", version=self.info["latest"])):
                return
            run_async(lambda: ctx.api.apply_update(path), lambda _r: QApplication.instance().quit(),
                      lambda msg: show_error(parent, msg), owner=ctx)

        run_async(ctx.api.download_update,
                  lambda task: ctx.tracker.track(task, downloaded, lambda msg: show_error(parent, msg)),
                  lambda msg: show_error(parent, msg), owner=ctx)
        self.accept()


def check_for_updates(ctx: AppContext, parent, silent: bool = False) -> None:
    """Проверяет канал обновлений. ``silent`` — без сообщений, если обновлений нет или сеть недоступна."""

    def done(info: dict) -> None:
        if info["available"]:
            UpdateDialog(ctx, info, parent).exec()
        elif not silent:
            show_info(parent, t("update.latest", version=info["current"]))

    def failed(message: str) -> None:
        if not silent:
            show_error(parent, message)

    run_async(ctx.api.check_update, done, failed, owner=ctx)
