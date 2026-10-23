"""Умные логи: сводка, проблемы с исправлениями, фильтры, подсветка и сворачиваемые стек-трейсы."""

import html

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from frontend.theme import current_colors
from frontend.utils.worker import run_async
from frontend.widgets import AppContext, button, clear_layout, confirm, label, open_path, show_error, show_info
from shared.i18n import t

_LIVE_MS = 2000
_COLLAPSED_FRAMES = 2
_MAX_RENDER = 2500
_LEVELS = ("all", "errors", "warnings", "info")
_LOADERS = {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt", "forge": "Forge", "neoforge": "NeoForge"}


class SmartLogView(QWidget):
    """Экран логов инстанса. ``activate()`` / ``deactivate()`` включают живое обновление."""

    def __init__(self, ctx: AppContext, instance: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self.name = instance["name"]
        self.instance = instance
        self.data: dict | None = None
        self.expanded: set[int] = set()
        self._source_id = ""
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.source = QComboBox()
        self.source.setMinimumWidth(280)
        self.source.currentIndexChanged.connect(self._source_changed)
        top.addWidget(self.source, 1)
        top.addWidget(button(t("logs.share"), self._share, "primary", small=True))
        top.addWidget(button(t("logs.copy"), self._copy, small=True))
        top.addWidget(button(t("instance.logs_folder"), lambda: open_path(self.instance["path"] + "/logs"),
                             "ghost", small=True))
        root.addLayout(top)

        self.summary = label("", wrap=True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.summary)

        self.problems_box = QFrame()
        self.problems_box.setObjectName("Card")
        self.problems = QVBoxLayout(self.problems_box)
        self.problems.setContentsMargins(12, 8, 12, 8)
        self.problems.setSpacing(6)
        root.addWidget(self.problems_box)
        self.problems_box.hide()

        filters = QHBoxLayout()
        self.level_group = QButtonGroup(self)
        self.level_group.setExclusive(True)
        for level in _LEVELS:
            btn = QPushButton(t(f"logs.level_{level}"))
            btn.setCheckable(True)
            btn.setProperty("size", "small")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("level", level)
            self.level_group.addButton(btn)
            filters.addWidget(btn)
            if level == "all":
                btn.setChecked(True)
        self.level_group.buttonClicked.connect(lambda _b: self._render())
        self.hide_noise = QCheckBox(t("logs.hide_noise"))
        self.hide_noise.setChecked(True)
        self.hide_noise.toggled.connect(lambda _c: self._render())
        filters.addWidget(self.hide_noise)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("logs.search"))
        self.search.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._render)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        filters.addWidget(self.search, 1)
        self.first_error_btn = button(t("logs.first_error"), self._jump_first_error, small=True)
        filters.addWidget(self.first_error_btn)
        root.addLayout(filters)

        self.view = QTextBrowser()
        self.view.setObjectName("Log")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._anchor)
        root.addWidget(self.view, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(_LIVE_MS)
        self._timer.timeout.connect(self._refresh_live)

    # --- Жизненный цикл -------------------------------------------------------------------------
    def activate(self) -> None:
        self.reload()
        self._timer.start()

    def deactivate(self) -> None:
        self._timer.stop()

    def reload(self, source_id: str | None = None) -> None:
        if self._loading:
            return
        self._loading = True
        sid = self._source_id if source_id is None else source_id

        def done(data: dict) -> None:
            self._loading = False
            self._apply(data)

        def failed(message: str) -> None:
            self._loading = False
            self.summary.setText(html.escape(message))

        run_async(lambda: self.api.analyze_logs(self.name, sid), done, failed, owner=self)

    def _refresh_live(self) -> None:
        source = (self.data or {}).get("source") or {}
        if source.get("live") or not self.data or not self.data.get("source"):
            self.reload()

    def _source_changed(self, _index: int) -> None:
        sid = self.source.currentData()
        if sid is not None and sid != self._source_id:
            self._source_id = sid
            self.expanded.clear()
            self.reload(sid)

    # --- Данные ---------------------------------------------------------------------------------------
    def _apply(self, data: dict) -> None:
        previous = self.data
        self.data = data
        source = data.get("source")
        self._fill_sources(data.get("sources", []), source["id"] if source else "")
        if source and not self._source_id:
            self._source_id = source["id"]
        self._render_summary(data)
        problems = data.get("problems", [])
        if not previous or previous.get("problems") != problems:
            self._render_problems(problems)
        if not previous or previous.get("entries") != data.get("entries"):
            self._render()

    def _fill_sources(self, sources: list[dict], current: str) -> None:
        items = [(s["id"], self._source_title(s)) for s in sources]
        existing = [(self.source.itemData(i), self.source.itemText(i)) for i in range(self.source.count())]
        if items == existing:
            return
        self.source.blockSignals(True)
        self.source.clear()
        if not items:
            self.source.addItem(t("logs.no_logs"), "")
        for sid, title in items:
            self.source.addItem(title, sid)
        index = self.source.findData(self._source_id or current)
        self.source.setCurrentIndex(max(0, index))
        self.source.blockSignals(False)

    @staticmethod
    def _source_title(source: dict) -> str:
        if source["live"]:
            return "▶ " + t("logs.source_live")
        kind = {"session": t("logs.source_session"), "crash": "💥 " + t("logs.source_crash"),
                "game": t("logs.source_game")}.get(source["kind"], source["kind"])
        return f"{kind}: {source['title']}"

    def _render_summary(self, data: dict) -> None:
        c = current_colors()
        s = data.get("summary") or {}
        if not data.get("source"):
            self.summary.setText(t("logs.empty"))
            self.first_error_btn.setEnabled(False)
            return
        parts = []
        loader = _LOADERS.get(s.get("loader"), s.get("loader") or "")
        game = f"Minecraft {s['minecraft']}" if s.get("minecraft") else ""
        if loader and loader != "Vanilla":
            game += f" · {loader} {s.get('loader_version') or ''}".rstrip()
        if s.get("optifine"):
            game += f" · OptiFine {s['optifine']}"
        parts.append(game)
        if s.get("mods"):
            parts.append(t("logs.mods", n=s["mods"]))
        if s.get("java"):
            parts.append(f"Java {html.escape(s['java'])}")
        if s.get("load_seconds") is not None:
            parts.append(t("logs.load_time", s=s["load_seconds"]))
        outcome_color = {"crashed": c["danger"], "running": c["success"], "loaded": c["success"],
                         "stopped": c["muted"]}.get(s.get("outcome"), c["muted"])
        outcome_text = t(f"logs.outcome_{s.get('outcome', 'unknown')}")
        outcome = f"<span style='color:{outcome_color}; font-weight:600'>{outcome_text}</span>"
        counts = (f"<span style='color:{c['danger']}'>✖ {t('logs.errors', n=s.get('errors', 0))}</span> &nbsp; "
                  f"<span style='color:{c['warning']}'>⚠ {t('logs.warnings', n=s.get('warnings', 0))}</span> &nbsp; "
                  f"<span style='color:{c['muted']}'>{t('logs.noise', n=s.get('noise', 0))}</span>")
        text = f"<b>{html.escape(' · '.join(p for p in parts if p))}</b><br>{outcome} &nbsp;·&nbsp; {counts}"
        if s.get("crash_description"):
            text += f"<br><span style='color:{c['danger']}'>{t('logs.crash_reason')}: " \
                    f"{html.escape(s['crash_description'])}</span>"
        if s.get("suspects"):
            names = ", ".join(html.escape(x["name"]) for x in s["suspects"])
            text += f"<br><span style='color:{c['muted']}'>{t('logs.suspects')}:</span> <b>{names}</b>"
        self.summary.setText(text)
        self.first_error_btn.setEnabled(s.get("first_error") is not None)

    def _render_problems(self, problems: list[dict]) -> None:
        clear_layout(self.problems)
        self.problems_box.setVisible(bool(problems))
        if not problems:
            return
        self.problems.addWidget(label(t("logs.problems", n=len(problems)), "SectionTitle"))
        for issue in problems[:6]:
            row = QHBoxLayout()
            icon = "✖" if issue["severity"] == "error" else "⚠"
            text = label(f"{icon} <b>{html.escape(issue['title'])}</b> — {html.escape(issue['details'])}", wrap=True)
            text.setTextFormat(Qt.TextFormat.RichText)
            text.setMinimumWidth(300)
            row.addWidget(text, 1)
            for fix in issue["fixes"][:2]:
                row.addWidget(button(fix["label"], lambda f=fix: self._apply_fix(f), small=True))
            self.problems.addLayout(row)

    def _apply_fix(self, fix: dict) -> None:
        ctx, window = self.ctx, self.window()

        run_async(lambda: self.api.apply_fix(self.name, fix["action"], fix.get("params") or {}),
                  lambda task: ctx.tracker.track(task, lambda _t: (show_info(window, t("doctor.fixed")),
                                                                   self.reload()),
                                                 lambda msg: show_error(window, msg)),
                  lambda msg: show_error(window, msg), owner=ctx)

    # --- Вывод ----------------------------------------------------------------------------------------
    def _visible_entries(self) -> list[dict]:
        if not self.data:
            return []
        level = self.level_group.checkedButton().property("level") if self.level_group.checkedButton() else "all"
        wanted = {"errors": {"ERROR"}, "warnings": {"ERROR", "WARN"}, "info": {"INFO", ""}}.get(level)
        hide_noise = self.hide_noise.isChecked()
        query = self.search.text().strip().lower()
        result = []
        for entry in self.data.get("entries", []):
            if hide_noise and entry["noise"]:
                continue
            if wanted is not None and entry["level"] not in wanted:
                continue
            if query and query not in entry["message"].lower() and query not in entry["source"].lower() \
                    and not any(query in x.lower() for x in entry["extra"]):
                continue
            result.append(entry)
        return result

    def _render(self) -> None:
        c = current_colors()
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        position = bar.value()
        entries = self._visible_entries()
        hidden = max(0, len(entries) - _MAX_RENDER)
        entries = entries[-_MAX_RENDER:]
        mod_names = (self.data or {}).get("mod_names", {})
        level_colors = {"ERROR": c["danger"], "WARN": c["warning"], "INFO": c["muted"], "DEBUG": c["muted"]}
        out = [f"<html><body style='font-family:Consolas,\"JetBrains Mono\",monospace; font-size:12px; "
               f"color:{c['text']}; white-space:pre-wrap'>"]
        if hidden:
            out.append(f"<div style='color:{c['muted']}'>{t('logs.hidden_older', n=hidden)}</div>")
        if (self.data or {}).get("truncated"):
            out.append(f"<div style='color:{c['muted']}'>{t('logs.truncated')}</div>")
        query = self.search.text().strip()
        for entry in entries:
            color = level_colors.get(entry["level"], c["text"])
            msg_color = c["text"] if entry["level"] in ("INFO", "", "DEBUG") else color
            if entry["noise"]:
                msg_color = c["muted"]
            parts = [f"<a name='e{entry['index']}'></a>"]
            if entry["time"]:
                parts.append(f"<span style='color:{c['muted']}'>{html.escape(entry['time'][-8:])}</span> ")
            if entry["level"]:
                weight = "700" if entry["level"] in ("ERROR", "WARN") else "400"
                parts.append(f"<span style='color:{color}; font-weight:{weight}'>{entry['level']:<5}</span> ")
            if entry["mod"]:
                name = html.escape(mod_names.get(entry["mod"], entry["mod"]))
                parts.append(f"<span style='color:{c['accent']}; font-weight:600'>[{name}]</span> ")
            elif entry["source"]:
                parts.append(f"<span style='color:{c['muted']}'>[{html.escape(entry['source'][-40:])}]</span> ")
            parts.append(f"<span style='color:{msg_color}'>{self._highlight(entry['message'], query)}</span>")
            if entry["count"] > 1:
                parts.append(f" <span style='color:{c['warning']}'>×{entry['count']}</span>")
            if entry["noise"]:
                parts.append(f" <span style='color:{c['muted']}; font-style:italic'>({t('logs.noise_tag')})</span>")
            block = "".join(parts)
            extra = entry["extra"]
            if extra:
                expanded = entry["index"] in self.expanded or len(extra) <= _COLLAPSED_FRAMES + 1
                shown = extra if expanded else extra[:_COLLAPSED_FRAMES]
                block += "<br>" + "<br>".join(f"<span style='color:{c['muted']}'>{self._highlight(x, query)}</span>"
                                              for x in shown)
                if not expanded:
                    block += (f"<br><a href='toggle:{entry['index']}' style='color:{c['accent']}'>"
                              f"▸ {t('logs.more_lines', n=len(extra) - len(shown))}</a>")
                elif len(extra) > _COLLAPSED_FRAMES + 1:
                    block += (f"<br><a href='toggle:{entry['index']}' style='color:{c['accent']}'>"
                              f"▾ {t('logs.collapse')}</a>")
            if entry.get("hint"):
                block += f"<br><span style='color:{c['success']}'>💡 {html.escape(entry['hint'])}</span>"
            out.append(f"<div style='margin:0 0 2px 0'>{block}</div>")
        out.append("</body></html>")
        self.view.setHtml("".join(out))
        if at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(position)

    @staticmethod
    def _highlight(text: str, query: str) -> str:
        escaped = html.escape(text)
        if not query:
            return escaped
        safe = html.escape(query)
        start = escaped.lower().find(safe.lower())
        if start < 0:
            return escaped
        end = start + len(safe)
        return f"{escaped[:start]}<span style='background:{current_colors()['selection']}'>" \
               f"{escaped[start:end]}</span>{escaped[end:]}"

    def _anchor(self, url: QUrl) -> None:
        target = url.toString()
        if target.startswith("toggle:"):
            index = int(target.split(":", 1)[1])
            self.expanded.symmetric_difference_update({index})
            self._render()

    def _jump_first_error(self) -> None:
        index = ((self.data or {}).get("summary") or {}).get("first_error")
        if index is None:
            return
        self.hide_noise.setChecked(True)
        for btn in self.level_group.buttons():
            if btn.property("level") == "all":
                btn.setChecked(True)
        self.expanded.add(index)
        self._render()
        self.view.scrollToAnchor(f"e{index}")

    # --- Действия -------------------------------------------------------------------------------------
    def _copy(self) -> None:
        lines = []
        for entry in self._visible_entries():
            head = " ".join(x for x in (entry["time"], entry["level"], entry["message"]) if x)
            lines.append(head + (f" ×{entry['count']}" if entry["count"] > 1 else ""))
            lines += entry["extra"]
        QGuiApplication.clipboard().setText("\n".join(lines))
        show_info(self.window(), t("logs.copied", n=len(lines)))

    def _share(self) -> None:
        if not self.data or not self.data.get("source"):
            return
        if not confirm(self.window(), t("logs.share_confirm")):
            return
        sid, window = self._source_id, self.window()

        def done(result: dict) -> None:
            QGuiApplication.clipboard().setText(result["url"])
            show_info(window, t("logs.shared", url=result["url"]))

        run_async(lambda: self.api.share_log(self.name, sid), done, lambda msg: show_error(window, msg), owner=self)
