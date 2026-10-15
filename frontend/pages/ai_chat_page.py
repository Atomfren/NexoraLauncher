"""AI-помощник (локальная LLM, опционально)."""

from html import escape

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QTextBrowser

from frontend.services.api_client import ApiClient
from frontend.widgets import AppContext, Page, button, label, open_path
from shared.i18n import t


class ChatStream(QThread):
    """Читает потоковый ответ AI и отдаёт токены в GUI-поток."""

    token = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, api: ApiClient, text: str, history: list[dict]):
        super().__init__()
        self.api = api
        self.text = text
        self.history = history

    def run(self) -> None:
        try:
            for event in self.api.ai_chat_stream(self.text, self.history):
                if "token" in event:
                    self.token.emit(event["token"])
                elif "error" in event:
                    self.failed.emit(event["error"])
                    return
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class AIChatPage(Page):
    def __init__(self, ctx: AppContext):
        super().__init__(ctx, t("ai.title"), t("ai.subtitle"), scroll=False)
        self.history: list[dict] = []
        self._answer = ""
        self._stream: ChatStream | None = None
        self._status: dict = {}

        self.notice = label("", muted=True, wrap=True)
        self.body.addWidget(self.notice)
        self.models_btn = button(t("ai.open_models"), lambda: open_path(self._status.get("models_dir", "")))
        self.models_btn.hide()
        self.body.addWidget(self.models_btn)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.body.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(t("ai.placeholder"))
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, 1)
        self.send_btn = button(t("ai.send"), self._send, "primary")
        row.addWidget(self.send_btn)
        row.addWidget(button(t("ai.clear"), self._clear, "ghost"))
        self.body.addLayout(row)

    def on_show(self, first: bool) -> None:
        self.run(self.api.ai_status, self._on_status)

    def _on_status(self, status: dict) -> None:
        self._status = status
        if not status["library_installed"]:
            self.notice.setText(t("ai.no_library"))
        elif not status["available"]:
            self.notice.setText(t("ai.no_model", path=status["models_dir"]))
        else:
            self.notice.setText(t("ai.ready", model=status["model_path"]))
        self.models_btn.setVisible(status["library_installed"] and not status["available"])
        self.input.setEnabled(status["available"])
        self.send_btn.setEnabled(status["available"])

    def _render(self) -> None:
        parts = []
        messages = [(m["role"], m["content"]) for m in self.history]
        if self._stream is not None:
            messages.append(("assistant", self._answer or "…"))
        for role, content in messages:
            who = t("ai.you") if role == "user" else t("ai.assistant")
            html = escape(content).replace("\n", "<br>")
            parts.append(f"<p><b>{who}:</b><br>{html}</p>")
        self.view.setHtml("".join(parts))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text or self._stream is not None:
            return
        self.input.clear()
        history = list(self.history)
        self.history.append({"role": "user", "content": text})
        self._answer = ""
        self._stream = ChatStream(self.api, text, history)
        self._stream.token.connect(self._on_token)
        self._stream.failed.connect(self._on_failed)
        self._stream.finished.connect(self._on_finished)
        self.send_btn.setEnabled(False)
        self._stream.start()
        self._render()

    def _on_token(self, token: str) -> None:
        self._answer += token
        self._render()

    def _on_failed(self, message: str) -> None:
        self._answer = f"⚠ {message}"

    def _on_finished(self) -> None:
        self.history.append({"role": "assistant", "content": self._answer.strip()})
        self._stream = None
        self.send_btn.setEnabled(True)
        self._render()

    def _clear(self) -> None:
        if self._stream is None:
            self.history.clear()
            self._render()
