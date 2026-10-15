"""Аккаунты: офлайн и Microsoft."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    Card,
    Page,
    ask_text,
    badge,
    button,
    clear_layout,
    confirm,
    label,
    open_url,
)
from shared.i18n import t


class MicrosoftLoginDialog(QDialog):
    """Показывает код устройства и ждёт подтверждения входа в браузере."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.task_id: str | None = None
        self.setWindowTitle(t("accounts.ms_title"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.info = label(t("accounts.ms_starting"), wrap=True)
        layout.addWidget(self.info)
        self.code = label("", "Code")
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code.hide()
        layout.addWidget(self.code)
        row = QHBoxLayout()
        self.copy_btn = button(t("accounts.ms_copy"), self._copy)
        self.open_btn = button(t("accounts.ms_open"), self._open, "primary")
        row.addWidget(self.copy_btn)
        row.addWidget(self.open_btn)
        self.copy_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.status = label(t("accounts.ms_waiting"), muted=True, wrap=True)
        layout.addWidget(self.status)
        cancel = button(t("common.cancel"), self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)
        self._uri = ""
        run_async(ctx.api.microsoft_login_start, self._on_started, self._on_start_failed, owner=self)

    def _on_started(self, data: dict) -> None:
        self.task_id = data["task_id"]
        self._uri = data["verification_uri"]
        self.info.setText(t("accounts.ms_instructions", url=self._uri))
        self.code.setText(data["user_code"])
        self.code.show()
        self.copy_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self.ctx.tracker.track({"id": self.task_id}, self._on_done, self._on_failed)

    def _on_start_failed(self, message: str) -> None:
        self.progress.hide()
        self.info.setText(message)
        if not self.ctx.settings.get("ms_client_id"):
            go = button(t("accounts.ms_open_settings"), self._go_settings, "primary")
            self.layout().insertWidget(1, go)

    def _go_settings(self) -> None:
        self.reject()
        self.ctx.navigate.emit("settings", {"focus": "ms_client_id"})

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.code.text())
        self.copy_btn.setText(t("accounts.ms_copied"))

    def _open(self) -> None:
        self._copy()
        open_url(self._uri)

    def _on_done(self, _task: dict) -> None:
        self.ctx.accounts_changed.emit()
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.progress.hide()
        self.status.setText(message)

    def reject(self) -> None:
        if self.task_id:
            task_id = self.task_id
            run_async(lambda: self.ctx.api.cancel_task(task_id), owner=None, on_error=lambda _m: None)
        super().reject()


class AccountsPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("accounts.title"), t("accounts.subtitle"))
        self.actions.addWidget(button(t("accounts.add_offline"), self._add_offline))
        self.actions.addWidget(button(t("accounts.add_microsoft"), self._add_microsoft, "primary"))
        ctx.accounts_changed.connect(self.reload)

    def on_show(self, first: bool) -> None:
        self.reload()

    def reload(self) -> None:
        self.run(self.api.accounts, self._render)

    def _render(self, accounts: list[dict]) -> None:
        if not accounts:
            self.set_empty(t("accounts.empty"))
            return
        clear_layout(self.body)
        for account in accounts:
            self.body.addWidget(self._card(account))
        self.body.addStretch()

    def _card(self, account: dict) -> Card:
        card = Card()
        avatar = QLabel(account["username"][:1].upper())
        avatar.setObjectName("Badge")
        avatar.setFixedSize(44, 44)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet("font-size: 18px; font-weight: 700;")
        card.layout_.addWidget(avatar)
        info = QVBoxLayout()
        title = QHBoxLayout()
        title.addWidget(label(account["username"], "CardTitle"))
        if account["active"]:
            title.addWidget(badge(t("accounts.active"), "success"))
        if account.get("expired"):
            title.addWidget(badge(t("accounts.expired")))
        title.addStretch()
        info.addLayout(title)
        kind = t("accounts.microsoft") if account["auth_type"] == "microsoft" else t("accounts.offline")
        info.addWidget(label(f"{kind}  ·  {account['uuid']}", muted=True))
        card.layout_.addLayout(info, 1)
        if not account["active"]:
            card.layout_.addWidget(button(t("accounts.make_active"),
                                          lambda: self._call(lambda: self.api.activate_account(account["id"]))))
        card.layout_.addWidget(button(t("common.delete"), lambda: self._remove(account), "danger"))
        return card

    def _call(self, fn) -> None:
        self.run(fn, lambda _r: self.ctx.accounts_changed.emit())

    def _add_offline(self) -> None:
        name = ask_text(self, t("accounts.add_offline"), t("accounts.offline_prompt"))
        if name:
            self._call(lambda: self.api.offline_login(name))

    def _add_microsoft(self) -> None:
        MicrosoftLoginDialog(self.ctx, self).exec()

    def _remove(self, account: dict) -> None:
        if confirm(self, t("accounts.remove_confirm", name=account["username"])):
            self._call(lambda: self.api.remove_account(account["id"]))

