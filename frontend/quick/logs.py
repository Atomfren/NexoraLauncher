"""Умные логи выбранной сборки: сеансы, фильтр по уровню, скрытие шума, поиск."""

from datetime import datetime
from typing import Any

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.worker import run_async
from shared.i18n import t

_LEVELS = {"ERROR": "error", "WARN": "warn", "INFO": "info", "DEBUG": "info"}
_MAX_LINES = 2000


def source_label(source: dict) -> str:
    kind = source.get("kind", "")
    try:
        stamp = datetime.fromisoformat(source.get("modified", "")).strftime("%d.%m %H:%M")
    except ValueError:
        stamp = ""
    title = {"session": t("q.log_session"), "crash": t("q.log_crash"), "game": "latest.log"}.get(kind, kind)
    live = " · " + t("q.log_live") if source.get("live") else ""
    return f"{title} · {stamp}{live}" if stamp and kind != "game" else title + live


def entry_row(entry: dict, mod_names: dict[str, str]) -> dict[str, Any]:
    mod = entry.get("mod", "")
    tag = mod_names.get(mod, mod) if mod else entry.get("source", "") or entry.get("thread", "")
    return {"index": entry.get("index", 0), "time": entry.get("time", ""),
            "level": _LEVELS.get(entry.get("level", ""), ""), "tag": tag, "message": entry.get("message", ""),
            "stack": entry.get("extra") or [], "count": int(entry.get("count") or 1), "hint": entry.get("hint", ""),
            "noise": bool(entry.get("noise")), "mod": bool(mod)}


def filter_rows(rows: list[dict], level: str, hide_noise: bool, query: str) -> tuple[list[dict], int]:
    """Строки под фильтр и число скрытых строк шума."""
    q = query.strip().lower()
    out, hidden = [], 0
    for row in rows:
        if level != "all" and row["level"] != level:
            continue
        if hide_noise and row["noise"]:
            hidden += 1
            continue
        if q and q not in (row["message"] + " " + row["tag"]).lower():
            continue
        out.append(row)
    return out[-_MAX_LINES:], hidden


class LogView(QObject):
    changed = pyqtSignal()
    linesChanged = pyqtSignal()

    def __init__(self, api: ApiClient, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.library = library
        self._name = ""
        self._source = ""
        self._sources: list[dict] = []
        self._summary: dict = {}
        self._problems: list[dict] = []
        self._rows: list[dict] = []
        self._lines: list[dict] = []
        self._hidden = 0
        self._level = "all"
        self._hide_noise = True
        self._query = ""
        self._loading = False
        self._error = ""
        self._gen = 0
        library.selectedChanged.connect(self._reset)
        library.gameExited.connect(lambda name, _code: self.reload() if name == self._name else None)

    # --- Свойства -------------------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=changed)
    def sources(self) -> list[dict]:
        return self._sources

    @pyqtProperty(str, notify=changed)
    def source(self) -> str:
        return self._source

    @pyqtProperty("QVariantMap", notify=changed)
    def summary(self) -> dict:
        return self._summary

    @pyqtProperty("QVariantList", notify=changed)
    def problems(self) -> list[dict]:
        return self._problems

    @pyqtProperty(bool, notify=changed)
    def loading(self) -> bool:
        return self._loading

    @pyqtProperty(str, notify=changed)
    def error(self) -> str:
        return self._error

    @pyqtProperty("QVariantList", notify=linesChanged)
    def lines(self) -> list[dict]:
        return self._lines

    @pyqtProperty(int, notify=linesChanged)
    def hiddenNoise(self) -> int:
        return self._hidden

    @pyqtProperty(str, notify=linesChanged)
    def level(self) -> str:
        return self._level

    @pyqtProperty(bool, notify=linesChanged)
    def hideNoise(self) -> bool:
        return self._hide_noise

    # --- Загрузка -------------------------------------------------------------------------------
    def _reset(self) -> None:
        self._name = ""
        self._source = ""
        self._sources, self._problems, self._rows, self._lines, self._summary = [], [], [], [], {}
        self.changed.emit()
        self.linesChanged.emit()

    @pyqtSlot()
    def ensure(self) -> None:
        """Вкладка открыта: загрузить логи, если ещё не загружены для этой сборки."""
        if self._name != self.library.selected and not self._loading:
            self.reload()

    @pyqtSlot()
    @pyqtSlot(str)
    def reload(self, source: str | None = None) -> None:
        name = self.library.selected
        if not name:
            return
        if source is not None:
            self._source = source
        elif name != self._name:
            self._source = ""
        self._name = name
        self._gen += 1
        gen = self._gen
        self._loading = True
        self._error = ""
        self.changed.emit()
        source_id = self._source

        def done(data: dict) -> None:
            if gen != self._gen:
                return
            self._loading = False
            self._sources = [{"value": s["id"], "label": source_label(s)} for s in data.get("sources", [])]
            self._source = (data.get("source") or {}).get("id", "") or source_id
            self._summary = data.get("summary") or {}
            self._problems = data.get("problems") or []
            names = data.get("mod_names") or {}
            self._rows = [entry_row(e, names) for e in data.get("entries", [])]
            self.changed.emit()
            self._apply()

        def failed(message: str) -> None:
            if gen != self._gen:
                return
            self._loading = False
            self._error = message
            self.changed.emit()

        run_async(lambda: self.api.analyze_logs(name, source_id), done, failed, owner=self)

    # --- Фильтры --------------------------------------------------------------------------------
    def _apply(self) -> None:
        self._lines, self._hidden = filter_rows(self._rows, self._level, self._hide_noise, self._query)
        self.linesChanged.emit()

    @pyqtSlot(str)
    def setLevel(self, level: str) -> None:
        self._level = level
        self._apply()

    @pyqtSlot(bool)
    def setHideNoise(self, value: bool) -> None:
        self._hide_noise = value
        self._apply()

    @pyqtSlot(str)
    def setQuery(self, query: str) -> None:
        self._query = query
        self._apply()

    @pyqtSlot(result=int)
    def firstErrorRow(self) -> int:
        return next((i for i, row in enumerate(self._lines) if row["level"] == "error"), -1)
