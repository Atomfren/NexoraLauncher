"""Генерирует иконку приложения resources/icon.png и icon.ico (нужен PySide6).

Запуск: python scripts/make_icon.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402,E501
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

OUT = Path(__file__).resolve().parent.parent / "resources"


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256

    # Фон: скруглённый квадрат с градиентом
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0, QColor("#4f8cff"))
    gradient.setColorAt(1, QColor("#7b4dff"))
    background = QPainterPath()
    background.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 56 * s, 56 * s)
    p.fillPath(background, QBrush(gradient))

    # Изометрический куб
    cx, cy, r = 128 * s, 132 * s, 78 * s
    top = QPolygonF([QPointF(cx, cy - r), QPointF(cx + r * 0.87, cy - r / 2), QPointF(cx, cy),
                     QPointF(cx - r * 0.87, cy - r / 2)])
    left = QPolygonF([QPointF(cx - r * 0.87, cy - r / 2), QPointF(cx, cy), QPointF(cx, cy + r),
                      QPointF(cx - r * 0.87, cy + r / 2)])
    right = QPolygonF([QPointF(cx, cy), QPointF(cx + r * 0.87, cy - r / 2), QPointF(cx + r * 0.87, cy + r / 2),
                       QPointF(cx, cy + r)])
    p.setPen(QPen(QColor(255, 255, 255, 90), max(1.0, 2 * s)))
    p.setBrush(QColor(255, 255, 255, 245))
    p.drawPolygon(top)
    p.setBrush(QColor(255, 255, 255, 190))
    p.drawPolygon(left)
    p.setBrush(QColor(255, 255, 255, 140))
    p.drawPolygon(right)

    # Буква N на верхней грани
    font = p.font()
    font.setBold(True)
    font.setPixelSize(int(64 * s))
    p.setFont(font)
    p.setPen(QColor("#5a6cff"))
    p.drawText(QRectF(cx - 40 * s, cy - r + 6 * s, 80 * s, 64 * s), Qt.AlignmentFlag.AlignCenter, "N")
    p.end()
    return image


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 — должен жить до конца рисования
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(str(OUT / "icon.png"))
    # .ico с несколькими размерами собираем вручную (PNG внутри ICO поддерживается Windows Vista+)
    import struct

    from PySide6.QtCore import QBuffer, QIODevice
    sizes = [16, 24, 32, 48, 64, 128, 256]
    blobs = []
    for size in sizes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        draw(size).save(buffer, "PNG")
        blobs.append(bytes(buffer.data()))
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for size, blob in zip(sizes, blobs, strict=True):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    (OUT / "icon.ico").write_bytes(header + entries + b"".join(blobs))
    print(f"Иконки сохранены в {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
