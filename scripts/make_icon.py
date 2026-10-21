"""Генерирует иконку приложения resources/icon.png и icon.ico (нужен PyQt6): пиксельная кирка 16x16.

Запуск: python scripts/make_icon.py [папка]   (по умолчанию resources/)
Рисунок задаётся ниже по клеткам; размеры кратны 16, поэтому пиксели остаются чёткими.
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "resources"
ICO_SIZES = [16, 32, 48, 64, 128, 256]

PALETTE = {
    "O": "#0a332d",  # обводка
    "D": "#168f7c", "M": "#2cc9ae", "L": "#6ff0d8", "W": "#c9fff4",  # навершие
    "B": "#3a2710", "b": "#664620", "y": "#946a30",  # рукоять
}


def pixels() -> dict[tuple[int, int], str]:
    """Клетки (строка, столбец) -> ключ палитры."""
    px: dict[tuple[int, int], str] = {}
    # навершие: верхняя планка
    for c, k in zip(range(4, 11), "WWLLLMM", strict=True):
        px[(1, c)] = k
    for c, k in zip(range(5, 12), "LMMMDDD", strict=True):
        px[(2, c)] = k
    # угол
    px[(2, 12)] = "D"
    px[(3, 12)] = "M"
    px[(3, 13)] = "D"
    # правая планка
    for r, k in zip(range(4, 10), "MMMDDD", strict=True):
        px[(r, 12)] = k
    for r, k in zip(range(4, 11), "DMMMLLW", strict=True):
        px[(r, 13)] = k
    # рукоять: лесенка из нижнего левого угла к углу навершия
    for i in range(11):
        r, c = 13 - i, 1 + i
        if (r, c) in px:
            break
        px.setdefault((r, c), "y" if i % 2 else "b")
        px.setdefault((r, c + 1), "B")
    # обводка по четырём соседям
    for (r, c) in list(px):
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q = (r + dr, c + dc)
            if q not in px and 0 <= q[0] < 16 and 0 <= q[1] < 16:
                px[q] = "O"
    return px


def draw(size: int) -> QImage:
    base = QImage(16, 16, QImage.Format.Format_ARGB32)
    base.fill(Qt.GlobalColor.transparent)
    for (r, c), key in pixels().items():
        base.setPixelColor(c, r, QColor(PALETTE[key]))
    return base.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.FastTransformation)


def png_bytes(image: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def main() -> None:
    QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(str(OUT / "icon.png"))

    # ICO из PNG-записей (Windows Vista+)
    blobs = [png_bytes(draw(s)) for s in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for size, blob in zip(ICO_SIZES, blobs, strict=True):
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    (OUT / "icon.ico").write_bytes(header + entries + b"".join(blobs))
    print(f"Иконка записана в {OUT}")


if __name__ == "__main__":
    main()
