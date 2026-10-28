"""Отпечаток вылета в интерфейсе: показать, спросить согласие, отправить.

Порядок шагов нарушать нельзя: сначала человек видит ровно тот текст, который уйдёт
(``report.text``), и только нажатие «Отправить» действительно отправляет его.
Согласие спрашивается каждый раз, никакой настройки «отправлять всегда» нет,
а по умолчанию не уходит ничего.

Состояния ``report.state``:

``idle``     — ничего не готовится (исходное);
``ask``      — применено исправление, спрашиваем «помогло?»;
``loading``  — собираем отпечаток, чтобы показать;
``ready``    — отпечаток показан, ждём решения человека;
``sending``  — человек согласился, отправляем;
``error``    — отпечаток собрать не удалось (например, в логе нет ошибки).
"""

from PySide6.QtCore import Property, QObject, Signal, Slot

from frontend.quick.bridge import Shell
from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.worker import run_async
from shared.i18n import t

# «Помогло?»: -1 — не спрашивали, 0 — не помогло, 1 — помогло (в QML удобнее числом)
UNKNOWN, NO, YES = -1, 0, 1


def helped_value(helped: int) -> bool | None:
    return None if helped < 0 else bool(helped)


class CrashReport(QObject):
    """Мост для отпечатка вылета. Сам ничего не отправляет без нажатия «Отправить»."""

    changed = Signal()

    def __init__(self, api: ApiClient, shell: Shell, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self.library = library
        self._state: dict = {"state": "idle"}
        library.selectedChanged.connect(self._reset)

    @Property("QVariantMap", notify=changed)
    def report(self) -> dict:
        return self._state

    def _set(self, **values) -> None:
        self._state = values
        self.changed.emit()

    def _reset(self) -> None:
        self._set(state="idle")

    @Slot(str)
    def askHelped(self, fix_action: str) -> None:
        """После применённого исправления — показать полоску «Исправление помогло?».
        Ответ сам по себе никуда не уходит: он только попадёт в отпечаток, если человек
        потом согласится его отправить."""
        self._set(state="ask", fix=fix_action, helped=UNKNOWN)

    @Slot()
    @Slot(int)
    def prepare(self, helped: int = UNKNOWN) -> None:
        """Собирает отпечаток и показывает человеку, что именно уйдёт."""
        name = self.library.selected
        fix = str(self._state.get("fix", ""))
        self._set(state="loading", helped=helped, fix=fix)

        def done(data: dict) -> None:
            self._set(state="ready", text=(data or {}).get("text", ""), helped=helped, fix=fix)

        def failed(message: str) -> None:
            self._set(state="error", error=message, helped=helped, fix=fix)

        run_async(lambda: self.api.crash_signature(name, helped_value(helped), fix), done, failed, owner=self)

    @Slot()
    def send(self) -> None:
        """Отправляет показанный отпечаток. Вызывается только из окна согласия."""
        name = self.library.selected
        helped = int(self._state.get("helped", UNKNOWN))
        fix = str(self._state.get("fix", ""))
        if self._state.get("state") != "ready":
            return   # отправлять можно только то, что человек уже увидел
        self._set(state="sending", helped=helped, fix=fix)

        def done(_result) -> None:
            self._reset()
            self.shell.toast(t("q.crash_sent"))

        def failed(message: str) -> None:
            self._reset()
            self.shell.toast(message, "err")

        run_async(lambda: self.api.send_crash_signature(name, helped_value(helped), fix), done, failed,
                  owner=self)

    @Slot()
    def dismiss(self) -> None:
        """Отказ: отпечаток забывается и никуда не уходит."""
        self._reset()
