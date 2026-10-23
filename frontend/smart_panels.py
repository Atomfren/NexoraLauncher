"""Панели «Доктор Nexora» и «Машина времени» (снимки)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from frontend.utils.worker import run_async
from frontend.widgets import (
    AppContext,
    Card,
    ask_text,
    button,
    clear_layout,
    confirm,
    format_date,
    format_size,
    label,
    show_error,
    show_info,
)
from shared.i18n import t

_SEVERITY_ICON = {"error": "⛔", "warning": "⚠️", "info": "ℹ️"}


class DoctorPanel(QWidget):
    """Диагностика последнего запуска и состояния модов с исправлениями в один клик."""

    def __init__(self, ctx: AppContext, instance: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self.instance = instance
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        self.summary = label(t("doctor.intro"), muted=True, wrap=True)
        bar.addWidget(self.summary, 1)
        self.run_btn = button(t("doctor.run"), self.reload, "primary")
        bar.addWidget(self.run_btn)
        layout.addLayout(bar)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(8)
        area.setWidget(holder)
        layout.addWidget(area, 1)
        self.reload()

    def reload(self) -> None:
        self.run_btn.setEnabled(False)
        self.summary.setText(t("doctor.running"))
        name = self.instance["name"]
        run_async(lambda: self.api.diagnose(name), self._render, self._failed, owner=self)

    def _failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.summary.setText(message)

    def _render(self, report: dict) -> None:
        self.run_btn.setEnabled(True)
        clear_layout(self.list)
        issues = report["issues"]
        errors = sum(1 for i in issues if i["severity"] == "error")
        if not issues:
            self.summary.setText(t("doctor.healthy", mods=report["mods_scanned"]))
            ok = label("✅  " + t("doctor.no_issues"), "Empty", wrap=True)
            ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addWidget(ok)
        else:
            source = t("doctor.sources", sources=report["sources"]) if report["sources"] else t("doctor.no_log")
            self.summary.setText(t("doctor.found", n=len(issues), errors=errors) + "  " + source)
            for issue in issues:
                self.list.addWidget(self._card(issue))
        self.list.addStretch()

    def _card(self, issue: dict) -> Card:
        card = Card()
        icon = QLabel(_SEVERITY_ICON.get(issue["severity"], "•"))
        icon.setStyleSheet("font-size: 20px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        card.layout_.addWidget(icon)
        info = QVBoxLayout()
        info.addWidget(label(issue["title"], "CardTitle", wrap=True))
        if issue["details"]:
            info.addWidget(label(issue["details"], muted=True, wrap=True))
        fixes = QHBoxLayout()
        for fix in issue["fixes"]:
            variant = "primary" if fix is issue["fixes"][0] else ""
            fixes.addWidget(button(fix["label"], lambda f=fix: self._apply(f), variant, small=True))
        fixes.addStretch()
        info.addLayout(fixes)
        card.layout_.addLayout(info, 1)
        return card

    def _apply(self, fix: dict) -> None:
        name = self.instance["name"]

        def done(task: dict) -> None:
            message = (task.get("result") or {}).get("message", "")
            show_info(self, message or t("doctor.fixed"))
            self.ctx.instances_changed.emit()
            self.reload()

        run_async(lambda: self.api.apply_fix(name, fix["action"], fix["params"]),
                  lambda task: self.ctx.tracker.track(task, done, lambda msg: show_error(self, msg)),
                  lambda msg: show_error(self, msg), owner=self)


class SnapshotsPanel(QWidget):
    """Список снимков инстанса: создать, откатиться, удалить."""

    def __init__(self, ctx: AppContext, instance: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.api = ctx.api
        self.instance = instance
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        bar = QHBoxLayout()
        bar.addWidget(label(t("snapshots.intro"), muted=True, wrap=True), 1)
        bar.addWidget(button(t("snapshots.create"), self._create, "primary"))
        layout.addLayout(bar)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(6)
        area.setWidget(holder)
        layout.addWidget(area, 1)
        self.reload()

    def reload(self) -> None:
        name = self.instance["name"]
        run_async(lambda: self.api.snapshots(name), self._render, lambda msg: show_error(self, msg), owner=self)

    def _render(self, items: list[dict]) -> None:
        clear_layout(self.list)
        if not items:
            empty = label(t("snapshots.empty"), "Empty", wrap=True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addWidget(empty)
        for item in items:
            card = Card(padding=10)
            icon = QLabel("🕓" if item["auto"] else "📌")
            icon.setStyleSheet("font-size: 18px;")
            card.layout_.addWidget(icon)
            info = QVBoxLayout()
            info.addWidget(label(item["label"], "CardTitle", shrink=True))
            info.addWidget(label(t("snapshots.meta", date=format_date(item["created_at"]), mods=item["mods"],
                                   loader=item["mod_loader"], version=item["version"],
                                   size=format_size(item["size"])), muted=True, shrink=True))
            card.layout_.addLayout(info, 1)
            card.layout_.addWidget(button(t("snapshots.restore"), lambda i=item: self._restore(i), small=True))
            card.layout_.addWidget(button("🗑", lambda i=item: self._delete(i), "ghost", t("common.delete"),
                                          small=True))
            self.list.addWidget(card)
        self.list.addStretch()

    def _create(self) -> None:
        text = ask_text(self, t("snapshots.create"), t("snapshots.label_prompt"), t("snapshots.default_label"))
        if text is None:
            return
        name = self.instance["name"]
        run_async(lambda: self.api.create_snapshot(name, text), lambda _r: self.reload(),
                  lambda msg: show_error(self, msg), owner=self)

    def _restore(self, item: dict) -> None:
        if not confirm(self, t("snapshots.restore_confirm", label=item["label"])):
            return
        name = self.instance["name"]

        def done(_r) -> None:
            show_info(self, t("snapshots.restored"))
            self.ctx.instances_changed.emit()
            self.reload()

        run_async(lambda: self.api.restore_snapshot(name, item["id"]), done,
                  lambda msg: show_error(self, msg), owner=self)

    def _delete(self, item: dict) -> None:
        if confirm(self, t("snapshots.delete_confirm", label=item["label"])):
            name = self.instance["name"]
            run_async(lambda: self.api.delete_snapshot(name, item["id"]), lambda _r: self.reload(),
                      lambda msg: show_error(self, msg), owner=self)
