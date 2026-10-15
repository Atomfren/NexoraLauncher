"""Процедурная пиксельная графика: обложки сборок, фоны, иконки модов, головы скинов.

Используется, пока у сборки нет настоящего скриншота или иконки. Картинки маленькие
(десятки пикселей), в QML они растягиваются без сглаживания — получается «пиксель-арт».
Результат детерминирован: одно и то же зерно даёт одну и ту же картинку.
"""

import colorsys
import math

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter

_U32 = 0xFFFFFFFF

PALETTES: dict[str, dict] = {
    "dusk": {"sky": ["#241731", "#3A2140", "#5A2B45", "#86354A", "#B24A44", "#D8703A", "#EE9B3A", "#F6C25A"],
             "sun": "#FFE08A", "far": "#4A2A4E", "mid": "#33203E", "grass": "#5F8F3C", "dirt": "#6B4A2E",
             "stone": "#4C4A48", "leaf": "#3F7A32", "trunk": "#4D3321"},
    "day": {"sky": ["#6FB5E8", "#82C0EC", "#95CBF0", "#A9D6F3", "#BDE0F5", "#D0E9F7"],
            "sun": "#FFF4B0", "far": "#7FA7B8", "mid": "#6C9AA8", "grass": "#68A63F", "dirt": "#7A5535",
            "stone": "#6B6A68", "leaf": "#4E8E34", "trunk": "#5B3E26"},
    "cave": {"sky": ["#0E0D0C", "#16130F", "#1C1712", "#241C14", "#2E2116", "#3A271A"],
             "sun": "#F0A23A", "far": "#2A2018", "mid": "#201812", "grass": "#5A5648", "dirt": "#4A3A2A",
             "stone": "#58544E", "leaf": "#6E6A5C", "trunk": "#3A2E22"},
    "nether": {"sky": ["#2A0A0A", "#401010", "#5A1612", "#7A1E14", "#9C2A14", "#B8401A"],
               "sun": "#FFB347", "far": "#4A1410", "mid": "#36100D", "grass": "#7A2A22", "dirt": "#5A2018",
               "stone": "#4A1A16", "leaf": "#8A3A2A", "trunk": "#3A1612"},
    "sky": {"sky": ["#143B5C", "#1B5278", "#256E92", "#2F8AAB", "#4BA7BF", "#7CC5CF", "#B6DDD3"],
            "sun": "#F4F2D0", "far": "#2D6A7A", "mid": "#1F5461", "grass": "#4D9A5A", "dirt": "#6A5A3A",
            "stone": "#5A6068", "leaf": "#3E8A4E", "trunk": "#4A3A28"},
}
PALETTE_NAMES = tuple(PALETTES)

_SKIN = ["#C98F6B", "#E0B08A", "#8D5A3C", "#F0C9A4", "#A6714F"]
_HAIR = ["#3B2A1D", "#1E1A17", "#7A4A24", "#C9A24A", "#5B3A7A", "#2E5E6E"]
_EYES = ["#2B5FA8", "#3E7A3C", "#4A3322"]


def seed_of(text: str) -> int:
    """Стабильное зерно из строки (имя сборки, id мода)."""
    h = 7
    for ch in text:
        h = (h * 31 + ord(ch)) % 997
    return h


def palette_for(text: str) -> str:
    return PALETTE_NAMES[seed_of(text) % len(PALETTE_NAMES)]


def _imul(a: int, b: int) -> int:
    return (a * b) & _U32


def rng(seed: int):
    """Генератор mulberry32: возвращает функцию, выдающую числа в [0, 1)."""
    state = (seed * 2654435761) & _U32

    def nxt() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & _U32
        t = _imul(state ^ (state >> 15), 1 | state)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & _U32) ^ t
        return ((t ^ (t >> 14)) & _U32) / 4294967296

    return nxt


class _Canvas:
    def __init__(self, width: int, height: int):
        self.image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.GlobalColor.transparent)
        self.painter = QPainter(self.image)

    def rect(self, x: int, y: int, w: int, h: int, color: str, opacity: float = 1.0) -> None:
        if w <= 0 or h <= 0:
            return
        c = QColor(color)
        if opacity < 1:
            c.setAlphaF(opacity)
        self.painter.fillRect(x, y, w, h, c)

    def done(self) -> QImage:
        self.painter.end()
        return self.image


def scene(seed: int, palette: str, cols: int, rows: int) -> QImage:
    """Пейзаж: небо полосами, солнце, холмы, трава/земля/камень, деревья."""
    cols, rows = max(4, min(cols, 512)), max(4, min(rows, 512))
    p = PALETTES.get(palette, PALETTES["day"])
    r = rng(seed)
    cv = _Canvas(cols, rows)
    bands = len(p["sky"])
    sky_h = round(rows * 0.78)
    for i, color in enumerate(p["sky"]):
        y = round(i * sky_h / bands)
        h = round((i + 1) * sky_h / bands) - y
        cv.rect(0, y, cols, h + 1, color)
    sx, sy = round(cols * (0.15 + r() * 0.7)), round(rows * (0.28 + r() * 0.12))
    ss = max(2, round(rows / 9))
    cv.rect(sx, sy, ss, ss, p["sun"])
    if palette in ("day", "sky"):
        for _ in range(3):
            cx, cy = round(r() * cols), round(rows * (0.1 + r() * 0.2))
            cw = max(3, round(cols / 8 + r() * cols / 12))
            cv.rect(cx, cy, cw, 1, "#ffffff", 0.55)
            cv.rect(cx + 1, cy - 1, max(1, cw - 2), 1, "#ffffff", 0.55)
    if palette in ("dusk", "cave", "nether"):
        for _ in range(round(cols / 6)):
            x, y = math.floor(r() * cols), math.floor(r() * rows * 0.4)
            cv.rect(x, y, 1, 1, "#ffffff", 0.25 + r() * 0.4)
    f1, f2, ph, ph2 = 0.06 + r() * 0.05, 0.16 + r() * 0.08, r() * 10, r() * 10
    h1 = [round(rows * 0.58 + math.sin(x * f1 + ph) * rows * 0.1 + math.sin(x * f1 * 2.3 + ph2) * rows * 0.04)
          for x in range(cols)]
    h2 = [round(rows * 0.7 + math.sin(x * f2 + ph2) * rows * 0.05 + math.sin(x * f2 * 1.7 + ph) * rows * 0.03)
          for x in range(cols)]
    for x in range(cols):
        cv.rect(x, h1[x], 1, rows - h1[x], p["far"])
    for x in range(cols):
        cv.rect(x, h2[x] - 1, 1, rows - h2[x] + 1, p["mid"])
    f3, ph3 = 0.09 + r() * 0.05, r() * 10
    ground = [round(rows * 0.8 + math.sin(x * f3 + ph3) * rows * 0.04 + math.sin(x * f3 * 2.6 + ph) * rows * 0.02)
              for x in range(cols)]
    dirt_h = max(1, round(rows * 0.07))
    for x in range(cols):
        y = ground[x]
        cv.rect(x, y, 1, 1, p["grass"])
        cv.rect(x, y + 1, 1, dirt_h, p["dirt"])
        cv.rect(x, y + 1 + dirt_h, 1, rows - (y + 1 + dirt_h), p["stone"])
        if r() < 0.07:
            cv.rect(x, y + 2 + dirt_h, 1, 1, "#000000", 0.18)
    for _ in range(max(1, round(cols / 28))):
        x = 3 + math.floor(r() * (cols - 6))
        y, th = ground[x], max(2, round(rows / 10))
        cv.rect(x, y - th, 1, th, p["trunk"])
        cv.rect(x - 1, y - th - 2, 3, 2, p["leaf"])
        cv.rect(x, y - th - 3, 1, 1, p["leaf"])
    return cv.done()


def _hsl(hue: float, sat: float, light: float) -> str:
    red, green, blue = colorsys.hls_to_rgb((hue % 360) / 360, light, sat)
    return QColor.fromRgbF(red, green, blue).name()


def mod_icon(seed: int, hue: int) -> QImage:
    """Симметричная иконка 8×8 для мода без собственной иконки."""
    r = rng(seed * 7 + 3)
    c1, c2, c3 = _hsl(hue, 0.55, 0.52), _hsl(hue + 30, 0.60, 0.38), _hsl(hue, 0.70, 0.78)
    cv = _Canvas(8, 8)
    cv.rect(0, 0, 8, 8, c2)
    for y in range(1, 7):
        for x in range(1, 4):
            if r() > 0.45:
                cv.rect(x, y, 1, 1, c3 if r() > 0.7 else c1)
                cv.rect(7 - x, y, 1, 1, c3 if r() > 0.7 else c1)
    return cv.done()


def head(seed: int) -> QImage:
    """Лицо скина 8×8 (пока нет настоящего скина аккаунта)."""
    r = rng(seed * 13 + 1)
    skin = _SKIN[math.floor(r() * len(_SKIN))]
    hair = _HAIR[math.floor(r() * len(_HAIR))]
    eye = _EYES[math.floor(r() * 3)]
    cv = _Canvas(8, 8)
    cv.rect(0, 0, 8, 8, skin)
    cv.rect(0, 0, 8, 2, hair)
    cv.rect(0, 2, 1, 2, hair)
    cv.rect(7, 2, 1, 2, hair)
    cv.rect(2, 4, 2, 1, "#ffffff")
    cv.rect(5, 4, 2, 1, "#ffffff")
    cv.rect(3, 4, 1, 1, eye)
    cv.rect(5, 4, 1, 1, eye)
    cv.rect(3, 6, 2, 1, "#000000", 0.28)
    return cv.done()
