"""Общие виджеты и хелперы UI."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend.services.api_client import ApiClient
from frontend.utils.worker import run_async
from shared.i18n import t


# --- Форматирование --------------------------------------------------------------
def format_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


def format_count(num: int) -> str:
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


def format_duration(seconds: int) -> str:
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    if hours:
        return t("time.hours_minutes", h=hours, m=minutes)
    return t("time.minutes", m=minutes)


def format_date(iso: str) -> str:
    if not iso:
        return t("common.never")
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


# --- Диалоги -------------------------------------------------------------------------
def show_error(parent: QWidget | None, message: str, title: str | None = None) -> None:
    QMessageBox.critical(parent, title or t("common.error"), message)


def show_info(parent: QWidget | None, message: str, title: str | None = None) -> None:
    QMessageBox.information(parent, title or t("common.info"), message)


def confirm(parent: QWidget | None, message: str, title: str | None = None) -> bool:
    answer = QMessageBox.question(parent, title or t("common.confirm"), message,
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def ask_text(parent: QWidget | None, title: str, label: str, value: str = "") -> str | None:
    text, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, value)
    return text.strip() if ok and text.strip() else None


def open_path(path: str | Path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


# --- Кнопки и метки ----------------------------------------------------------------------
def button(text: str, on_click: Callable | None = None, variant: str = "",
           tooltip: str = "", small: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if small:
        btn.setProperty("size", "small")
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
    if on_click:
        btn.clicked.connect(lambda _checked=False: on_click())
    return btn


def set_variant(btn: QPushButton, variant: str) -> None:
    btn.setProperty("variant", variant)
    btn.style().unpolish(btn)
    btn.style().polish(btn)


def label(text: str = "", object_name: str = "", muted: bool = False, wrap: bool = False,
          shrink: bool = False) -> QLabel:
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    if muted:
        lbl.setProperty("muted", True)
    if wrap:
        lbl.setWordWrap(True)
    if shrink:
        # Длинный текст не растягивает карточку шире окна (обрезается)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lbl.setToolTip(text)
    return lbl


def badge(text: str, kind: str = "") -> QLabel:
    lbl = label(text, {"success": "BadgeSuccess", "danger": "BadgeDanger"}.get(kind, "Badge"))
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if widget := item.widget():
            widget.deleteLater()
        elif child := item.layout():
            clear_layout(child)


class Card(QFrame):
    """Карточка с рамкой."""

    def __init__(self, parent: QWidget | None = None, padding: int = 14):
        super().__init__(parent)
        self.setObjectName("Card")
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(padding, padding - 2, padding, padding - 2)
        self.layout_.setSpacing(12)


class Page(QWidget):
    """Базовая страница: заголовок, панель действий справа и прокручиваемое содержимое."""

    def __init__(self, ctx: "AppContext", title: str, subtitle: str = "", scroll: bool = True):
        super().__init__()
        self.ctx = ctx
        self.api = ctx.api
        self.setObjectName("Page")
        self._loaded_once = False
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "PageTitle"))
        if subtitle:
            titles.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        header.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        header.addLayout(self.actions)
        root.addLayout(header)

        self.toolbar = QHBoxLayout()
        self.toolbar.setSpacing(8)
        root.addLayout(self.toolbar)

        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            container = QWidget()
            self.body = QVBoxLayout(container)
            self.body.setContentsMargins(0, 0, 6, 0)
            self.body.setSpacing(10)
            area.setWidget(container)
            root.addWidget(area, 1)
        else:
            self.body = QVBoxLayout()
            self.body.setSpacing(10)
            root.addLayout(self.body, 1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.on_show(first=not self._loaded_once)
        self._loaded_once = True

    def on_show(self, first: bool) -> None:
        """Переопределяется страницами: загрузка данных при показе."""

    def run(self, fn, on_done=None, on_error=None) -> None:
        """Фоновый вызов API с выводом ошибки по умолчанию."""
        run_async(fn, on_done, on_error or (lambda msg: show_error(self, msg)), owner=self)

    def track(self, task: dict, on_done=None, on_error=None) -> None:
        self.ctx.tracker.track(task, on_done, on_error or (lambda msg: show_error(self, msg)))

    def set_empty(self, text: str) -> None:
        clear_layout(self.body)
        empty = label(text, "Empty")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.body.addWidget(empty)
        self.body.addStretch()


class AppContext(QObject):
    """Общие сервисы, доступные всем страницам."""

    instances_changed = pyqtSignal()
    accounts_changed = pyqtSignal()
    settings_changed = pyqtSignal(dict)
    navigate = pyqtSignal(str, dict)

    def __init__(self, api: ApiClient, tracker, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.tracker = tracker
        self.settings: dict = {}


# --- Загрузка иконок ------------------------------------------------------------------------
class IconCache(QObject):
    """Асинхронная загрузка и кэширование иконок проектов (в памяти)."""

    _instance: "IconCache | None" = None

    def __init__(self, api: ApiClient):
        super().__init__()
        self.api = api
        self._cache: dict[str, QPixmap] = {}
        self._waiting: dict[str, list[QLabel]] = {}

    @classmethod
    def init(cls, api: ApiClient) -> None:
        cls._instance = cls(api)

    @classmethod
    def load_into(cls, target: QLabel, url: str | None, size: int = 48) -> None:
        target.setFixedSize(size, size)
        target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target.setObjectName("Badge")
        if not url or cls._instance is None:
            return
        cls._instance._load(target, url, size)

    def _load(self, target: QLabel, url: str, size: int) -> None:
        if url in self._cache:
            self._apply(target, self._cache[url], size)
            return
        waiting = self._waiting.setdefault(url, [])
        waiting.append(target)
        if len(waiting) > 1:
            return

        def done(data: bytes) -> None:
            image = QImage()
            image.loadFromData(data)
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                self._cache[url] = pixmap
            for lbl in self._waiting.pop(url, []):
                if not pixmap.isNull():
                    self._apply(lbl, pixmap, size)

        run_async(lambda: self.api.download_bytes(url), done,
                  lambda _msg: self._waiting.pop(url, None), owner=self, background=True)

    @staticmethod
    def _apply(target: QLabel, pixmap: QPixmap, size: int) -> None:
        from PyQt6 import sip
        if sip.isdeleted(target):
            return
        target.setPixmap(pixmap.scaled(QSize(size, size), Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))


_LOADER_TITLES = {"vanilla": "Vanilla", "fabric": "Fabric", "quilt": "Quilt", "forge": "Forge",
                  "neoforge": "NeoForge"}


def instance_combo(include_empty: str | None = None) -> QComboBox:
    combo = QComboBox()
    combo.setMinimumWidth(200)
    combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    if include_empty is not None:
        combo.addItem(include_empty, None)
    return combo


def fill_instance_combo(combo: QComboBox, instances: list[dict], keep: str | None = None,
                        include_empty: str | None = None) -> None:
    """Заполняет комбобокс инстансами (data = dict инстанса)."""
    current = keep or (combo.currentData() or {}).get("name") if combo.count() else keep
    combo.blockSignals(True)
    combo.clear()
    if include_empty is not None:
        combo.addItem(include_empty, None)
    for inst in instances:
        loader = _LOADER_TITLES.get(inst["mod_loader"], inst["mod_loader"])
        combo.addItem(f"{inst['name']}  ·  {loader} {inst['version']}", inst)
    index = next((i for i in range(combo.count())
                  if (combo.itemData(i) or {}).get("name") == current), 0)
    combo.setCurrentIndex(index)
    combo.blockSignals(False)


def app_icon() -> QIcon:
    from shared.paths import get_resources_dir
    path = get_resources_dir() / "icon.png"
    return QIcon(str(path)) if path.exists() else QIcon()
