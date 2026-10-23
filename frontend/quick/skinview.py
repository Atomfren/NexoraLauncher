"""3D-модель персонажа Minecraft со скином и плащом (элемент QML ``NxSkinView``).

Рисуется через QPainter, без Qt Quick 3D: проекция ортографическая, поэтому каждая грань
коробки (голова, тело, руки, ноги, плащ) — параллелограмм, и кусок развёртки скина
переносится на неё аффинным преобразованием. Работает и при программной отрисовке.

Координаты модели — в пикселях скина: ось Y направлена вниз, игрок смотрит на +Z (на зрителя),
+X — его левая рука. Модель высотой 32: голова 0–8, тело 8–20, ноги 20–32.
"""

import math
from dataclasses import dataclass

from PySide6.QtCore import Property, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient, QTransform
from PySide6.QtQuick import QQuickPaintedItem

Vec = tuple[float, float, float]


@dataclass
class Box:
    """Коробка в своих координатах (верх — y=0) + развёртка на текстуре."""

    w: float
    h: float
    d: float
    u: int
    v: int
    # Перенос и поворот вокруг оси X относительно точки крепления (плечо, бедро, верх плаща)
    pivot: Vec = (0.0, 0.0, 0.0)
    offset: Vec = (0.0, 0.0, 0.0)  # левый-верхний-задний угол относительно pivot
    angle_x: float = 0.0
    inflate: float = 0.0
    texture: str = "skin"
    flip: bool = False  # плащ: развёрнут лицом назад


def _faces(box: Box) -> list[tuple[str, tuple[Vec, Vec, Vec], tuple[float, float, float, float]]]:
    """Грани: (имя, углы TL/TR/BL в своих координатах, прямоугольник на развёртке)."""
    i = box.inflate
    x0, y0, z0 = box.offset[0] - i, box.offset[1] - i, box.offset[2] - i
    x1, y1, z1 = box.offset[0] + box.w + i, box.offset[1] + box.h + i, box.offset[2] + box.d + i
    w, h, d, u, v = box.w, box.h, box.d, box.u, box.v
    return [
        ("front", ((x0, y0, z1), (x1, y0, z1), (x0, y1, z1)), (u + d, v + d, w, h)),
        ("back", ((x1, y0, z0), (x0, y0, z0), (x1, y1, z0)), (u + 2 * d + w, v + d, w, h)),
        ("right", ((x0, y0, z0), (x0, y0, z1), (x0, y1, z0)), (u, v + d, d, h)),
        ("left", ((x1, y0, z1), (x1, y0, z0), (x1, y1, z1)), (u + d + w, v + d, d, h)),
        ("top", ((x0, y0, z0), (x1, y0, z0), (x0, y0, z1)), (u + d, v, w, d)),
        ("bottom", ((x0, y1, z1), (x1, y1, z1), (x0, y1, z0)), (u + d + w, v, w, d)),
    ]


def model_boxes(slim: bool, swing: float, cape_angle: float, has_cape: bool, legacy: bool) -> list[Box]:
    """Части модели с учётом позы (swing — размах рук и ног в радианах)."""
    arm = 3.0 if slim else 4.0
    boxes = [
        Box(8, 8, 8, 0, 0, pivot=(0, 0, 0), offset=(-4, 0, -4)),                       # голова
        Box(8, 12, 4, 16, 16, pivot=(0, 8, 0), offset=(-4, 0, -2)),                    # тело
        Box(arm, 12, 4, 40, 16, pivot=(-4 - arm / 2, 10, 0), offset=(-arm / 2, -2, -2), angle_x=swing),
        Box(arm, 12, 4, 40 if legacy else 32, 16 if legacy else 48,
            pivot=(4 + arm / 2, 10, 0), offset=(-arm / 2, -2, -2), angle_x=-swing),
        Box(4, 12, 4, 0, 16, pivot=(-2, 20, 0), offset=(-2, 0, -2), angle_x=-swing),
        Box(4, 12, 4, 0 if legacy else 16, 16 if legacy else 48, pivot=(2, 20, 0), offset=(-2, 0, -2), angle_x=swing),
        Box(8, 8, 8, 32, 0, pivot=(0, 0, 0), offset=(-4, 0, -4), inflate=0.5),            # шапка
    ]
    if not legacy:
        boxes += [
            Box(8, 12, 4, 16, 32, pivot=(0, 8, 0), offset=(-4, 0, -2), inflate=0.25),   # куртка
            Box(arm, 12, 4, 40, 32, pivot=(-4 - arm / 2, 10, 0), offset=(-arm / 2, -2, -2), angle_x=swing,
                inflate=0.25),
            Box(arm, 12, 4, 48, 48, pivot=(4 + arm / 2, 10, 0), offset=(-arm / 2, -2, -2), angle_x=-swing,
                inflate=0.25),
            Box(4, 12, 4, 0, 32, pivot=(-2, 20, 0), offset=(-2, 0, -2), angle_x=-swing, inflate=0.25),
            Box(4, 12, 4, 0, 48, pivot=(2, 20, 0), offset=(-2, 0, -2), angle_x=swing, inflate=0.25),
        ]
    if has_cape:
        # Плащ 10×16×1 висит за спиной и чуть отходит назад
        boxes.append(Box(10, 16, 1, 0, 0, pivot=(0, 8, -2), offset=(-5, 0, -1), angle_x=-cape_angle,
                         texture="cape", flip=True))
    return boxes


def _local_to_model(box: Box, p: Vec) -> Vec:
    x, y, z = p
    if box.flip:  # разворот на 180° вокруг вертикальной оси коробки
        cx = box.offset[0] + box.w / 2
        cz = box.offset[2] + box.d / 2
        x, z = 2 * cx - x, 2 * cz - z
    if box.angle_x:
        c, s = math.cos(box.angle_x), math.sin(box.angle_x)
        y, z = y * c - z * s, y * s + z * c
    return x + box.pivot[0], y + box.pivot[1], z + box.pivot[2]


def project(p: Vec, yaw: float, pitch: float) -> tuple[float, float, float]:
    """Модель → экран (x, y) и глубина (больше — ближе к зрителю)."""
    x, y, z = p
    cy, sy = math.cos(yaw), math.sin(yaw)
    x1, z1 = x * cy + z * sy, -x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y2, z2 = y * cp - z1 * sp, y * sp + z1 * cp
    return x1, y2, z2


def normalize_skin(image: QImage) -> tuple[QImage, bool]:
    """Скин → формат ARGB32 64×64 (масштаб HD учитывается отдельно); True, если это старый скин 64×32."""
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    legacy = image.height() * 2 == image.width()
    if legacy:
        # «Хак прозрачности» игры: полностью непрозрачная шапка у старых скинов не рисуется
        k = image.width() // 64
        hat = image.copy(32 * k, 0, 32 * k, 16 * k)
        if all(QColor(hat.pixel(x, y)).alpha() == 255 for x in range(0, hat.width(), max(1, k))
               for y in range(0, hat.height(), max(1, k))):
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(32 * k, 0, 32 * k, 16 * k, Qt.GlobalColor.transparent)
            painter.end()
    return image, legacy


class SkinView(QQuickPaintedItem):
    """QML: ``NxSkinView { skin: "C:/…/skin.png"; cape: "…"; slim: false; yaw: 20; time: t }``."""

    # Отдельный сигнал на каждое свойство: с общим сигналом привязка yaw к time давала цикл
    skinChanged = Signal()
    capeChanged = Signal()
    slimChanged = Signal()
    yawChanged = Signal()
    pitchChanged = Signal()
    timeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._skin_path = ""
        self._cape_path = ""
        self._skin = QImage()
        self._cape = QImage()
        self._legacy = False
        self._slim = False
        self._yaw = 25.0
        self._pitch = -12.0
        self._time = 0.0
        self.setAntialiasing(False)
        for signal in (self.skinChanged, self.capeChanged, self.slimChanged, self.yawChanged,
                       self.pitchChanged, self.timeChanged):
            signal.connect(self.update)

    # --- Свойства --------------------------------------------------------------------------------
    @Property(str, notify=skinChanged)
    def skin(self) -> str:
        return self._skin_path

    @skin.setter
    def skin(self, path: str) -> None:
        if path == self._skin_path:
            return
        self._skin_path = path
        image = QImage(path) if path else QImage()
        if not image.isNull() and image.width() >= 64 and image.height() in (image.width(), image.width() // 2):
            self._skin, self._legacy = normalize_skin(image)
        else:
            self._skin, self._legacy = QImage(), False
        self.skinChanged.emit()

    @Property(str, notify=capeChanged)
    def cape(self) -> str:
        return self._cape_path

    @cape.setter
    def cape(self, path: str) -> None:
        if path == self._cape_path:
            return
        self._cape_path = path
        image = QImage(path) if path else QImage()
        self._cape = image.convertToFormat(QImage.Format.Format_ARGB32) if not image.isNull() else QImage()
        self.capeChanged.emit()

    @Property(bool, notify=slimChanged)
    def slim(self) -> bool:
        return self._slim

    @slim.setter
    def slim(self, value: bool) -> None:
        if value != self._slim:
            self._slim = value
            self.slimChanged.emit()

    @Property(float, notify=yawChanged)
    def yaw(self) -> float:
        return self._yaw

    @yaw.setter
    def yaw(self, value: float) -> None:
        if value != self._yaw:
            self._yaw = value
            self.yawChanged.emit()

    @Property(float, notify=pitchChanged)
    def pitch(self) -> float:
        return self._pitch

    @pitch.setter
    def pitch(self, value: float) -> None:
        if value != self._pitch:
            self._pitch = value
            self.pitchChanged.emit()

    @Property(float, notify=timeChanged)
    def time(self) -> float:
        """Фаза покачивания рук и плаща (обычно анимируется из QML)."""
        return self._time

    @time.setter
    def time(self, value: float) -> None:
        if value != self._time:
            self._time = value
            self.timeChanged.emit()

    @Property(bool, notify=skinChanged)
    def ready(self) -> bool:
        return not self._skin.isNull()

    # --- Отрисовка -------------------------------------------------------------------------------
    def paint(self, painter: QPainter) -> None:
        if self._skin.isNull():
            return
        width, height = self.width(), self.height()
        # Модель 32 в высоту + запас под плащ и тень
        scale = min(height / 38.0, width / 22.0)
        cx, cy = width / 2, (height - 34 * scale) / 2
        yaw, pitch = math.radians(self._yaw), math.radians(self._pitch)
        swing = math.sin(self._time) * 0.12
        cape_angle = 0.18 + math.sin(self._time * 0.8) * 0.05

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        # Тень под ногами
        shadow = QRadialGradient(QPointF(cx, cy + 32.6 * scale), 9 * scale)
        shadow.setColorAt(0, QColor(0, 0, 0, 110))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(QPointF(cx, cy + 32.6 * scale), 9 * scale, 2.6 * scale)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        skin_k = self._skin.width() / 64.0
        cape_k = self._cape.width() / 64.0 if not self._cape.isNull() else 1.0
        has_cape = not self._cape.isNull()
        # Сортируем целые коробки (они выпуклые и почти не пересекаются), а не отдельные грани:
        # иначе низ плаща просвечивал сквозь ноги. При равной глубине накладной слой — поверх основного.
        parts = []
        for box in model_boxes(self._slim, swing, cape_angle, has_cape, self._legacy):
            image, k = (self._cape, cape_k) if box.texture == "cape" else (self._skin, skin_k)
            center = (box.offset[0] + box.w / 2, box.offset[1] + box.h / 2, box.offset[2] + box.d / 2)
            depth = project(_local_to_model(box, center), yaw, pitch)[2]
            faces = []
            for _name, corners, uv in _faces(box):
                (ax, ay, _az), (bx, by, _bz), (dx, dy, _dz) = [
                    project(_local_to_model(box, c), yaw, pitch) for c in corners]
                ex, ey, fx, fy = bx - ax, by - ay, dx - ax, dy - ay
                if ex * fy - ey * fx > 1e-6:  # иначе грань смотрит от зрителя
                    faces.append((uv, (ax, ay, ex, ey, fx, fy)))
            parts.append((depth, box.inflate, image, k, faces))
        parts.sort(key=lambda part: (part[0], part[1]))
        for _depth, _inflate, image, k, faces in parts:
            for (u, v, tw, th), (ax, ay, ex, ey, fx, fy) in faces:
                # Чуть расширяем грань, чтобы между соседними не просвечивали щели
                grow = 1.0 + 0.6 / max(1.0, min(math.hypot(ex, ey), math.hypot(fx, fy)) * scale)
                ox, oy = ax + (ex + fx) * (1 - grow) / 2, ay + (ey + fy) * (1 - grow) / 2
                transform = QTransform(ex * grow * scale / tw, ey * grow * scale / tw,
                                       fx * grow * scale / th, fy * grow * scale / th,
                                       cx + ox * scale, cy + oy * scale)
                painter.setTransform(transform)
                painter.drawImage(QRectF(0, 0, tw, th), image, QRectF(u * k, v * k, tw * k, th * k))
        painter.resetTransform()

