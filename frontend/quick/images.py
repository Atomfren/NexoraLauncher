"""Провайдер картинок для QML: ``image://nx/<вид>/<параметры>``.

Виды:
    icon/<имя>/<rrggbb>          — иконка Lucide нужного цвета
    loader/<загрузчик>           — значок загрузчика
    logo/<rrggbb>/<rrggbb>       — логотип (основной цвет, акцент)
    illus/<имя>/<rrggbb>         — иллюстрация пустого состояния
    scene/<палитра>/<зерно>/<w>/<h> — процедурный пейзаж (обложка, фон)
    mod/<зерно>/<оттенок>        — процедурная иконка мода
    head/<зерно>                 — лицо скина
    remote/<ref>                 — внешняя картинка (иконки Modrinth), с кэшем в памяти
    file/<ref>                   — локальный файл (скриншот, иконка мира)
    round/<радиус>/<dim>/<вид…>  — любая картинка выше, обрезанная по размеру и скруглённая

``ref`` — строка в кодировке ``encode_ref`` (без «/» и «%», чтобы Qt не перекодировал адрес).
Векторные и скруглённые виды рисуются в размере ``sourceSize`` из QML, пиксельные — в родном
размере (в QML у них ``smooth: false``). Скругление делается здесь, а не шейдером:
так картинки видны и при программной отрисовке.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import quote, unquote

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import QImage, QImageReader, QPainter, QPainterPath
from PyQt6.QtQuick import QQuickImageProvider
from PyQt6.QtSvg import QSvgRenderer

from frontend.quick import art, icons
from frontend.utils.logger import logger

_REMOTE_CACHE_SIZE = 300
_PIXEL_KINDS = ("scene", "mod", "head")


def encode_ref(value: str) -> str:
    """Строка → безопасный фрагмент адреса image://nx (обратное — ``decode_ref``)."""
    return quote(value, safe="").replace("~", "%7E").replace("%", "~")


def decode_ref(value: str) -> str:
    return unquote(value.replace("~", "%"))


def file_ref(path: str) -> str:
    return f"image://nx/file/{encode_ref(path)}"


def remote_ref(url: str) -> str:
    return f"image://nx/remote/{encode_ref(url)}"


def _fill(image: QImage, size: QSize, pixel: bool) -> QImage:
    """Масштабирует с обрезкой по центру (как PreserveAspectCrop)."""
    mode = Qt.TransformationMode.FastTransformation if pixel else Qt.TransformationMode.SmoothTransformation
    scaled = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, mode)
    x = (scaled.width() - size.width()) // 2
    y = (scaled.height() - size.height()) // 2
    return scaled.copy(x, y, size.width(), size.height())


def _round(image: QImage, radius: float, dim: bool) -> QImage:
    out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, image.width(), image.height()), radius, radius)
    painter.setClipPath(path)
    if dim:
        gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
        painter.drawImage(0, 0, gray)
        painter.setOpacity(0.3)
    painter.drawImage(0, 0, image)
    painter.end()
    return out


def _render_svg(data: bytes, size: QSize) -> QImage:
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(data))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


class NxImageProvider(QQuickImageProvider):
    def __init__(self, fetch: Callable[[str], bytes] | None = None):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._fetch = fetch
        self._remote: OrderedDict[str, QImage] = OrderedDict()
        self._lock = threading.Lock()

    def requestImage(self, image_id: str, requested: QSize):
        try:
            image = self._make(image_id, requested)
        except Exception:  # noqa: BLE001 — битая картинка не должна ронять интерфейс
            logger.debug(f"Не удалось построить картинку {image_id}")
            image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
        return image, image.size()

    def _make(self, image_id: str, requested: QSize) -> QImage:
        kind, _, rest = image_id.partition("/")
        parts = rest.split("/")
        size = requested if requested.isValid() and not requested.isEmpty() else QSize(24, 24)
        if kind == "icon":
            return _render_svg(icons.icon_svg(parts[0], "#" + parts[1] if len(parts) > 1 else "#000"), size)
        if kind == "loader":
            return _render_svg(icons.loader_svg(parts[0]), size)
        if kind == "logo":
            return _render_svg(icons.logo_svg("#" + parts[0], "#" + parts[1]), size)
        if kind == "illus":
            return _render_svg(icons.illustration_svg(parts[0], "#" + parts[1]), size)
        if kind == "scene":
            return art.scene(_int(parts[1], 1), parts[0], _int(parts[2], 20), _int(parts[3], 20))
        if kind == "mod":
            return art.mod_icon(_int(parts[0], 1), _int(parts[1], 140))
        if kind == "head":
            return art.head(_int(parts[0], 1))
        if kind == "remote":
            return _fill(self._remote_image(decode_ref(rest)), size, pixel=False)
        if kind == "file":
            return self._file_image(decode_ref(rest), size)
        if kind == "round":
            radius, dim, inner = rest.split("/", 2)
            inner_kind = inner.partition("/")[0]
            pixel = inner_kind in _PIXEL_KINDS
            base = self._make(inner, size)
            return _round(_fill(base, size, pixel), _int(radius, 0), dim == "1")
        raise ValueError(kind)

    @staticmethod
    def _file_image(path: str, size: QSize) -> QImage:
        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        original = reader.size()
        if original.isValid() and not original.isEmpty():
            factor = max(size.width() / original.width(), size.height() / original.height())
            if factor < 1:
                reader.setScaledSize(QSize(max(1, round(original.width() * factor)),
                                           max(1, round(original.height() * factor))))
        image = reader.read()
        if image.isNull():
            raise ValueError(path)
        return _fill(image, size, pixel=False)

    def _remote_image(self, url: str) -> QImage:
        with self._lock:
            if url in self._remote:
                self._remote.move_to_end(url)
                return self._remote[url]
        if self._fetch is None or not url.startswith(("http://", "https://")):
            raise ValueError(url)
        image = QImage.fromData(self._fetch(url))
        if image.isNull():
            raise ValueError(url)
        with self._lock:
            self._remote[url] = image
            while len(self._remote) > _REMOTE_CACHE_SIZE:
                self._remote.popitem(last=False)
        return image
