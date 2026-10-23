"""Скины и плащи аккаунтов, 3D-модель персонажа и переключение аккаунтов стрелками."""

import os
import sys
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _png(width: int, height: int, color: str = "#3366cc") -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


@pytest.fixture
def gui():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication(sys.argv)


@pytest.fixture
def offline(client, monkeypatch):
    from backend.core import skins
    monkeypatch.setattr(skins, "_mojang_textures", lambda name: {})  # без сети
    r = client.post("/api/v1/auth/offline/login", json={"username": "Tester"})
    return r.json()["id"]


def test_default_skin_from_game_jar(client, offline, gui):
    """Нет скина у Mojang — Стив или Алекс из установленной версии игры, как выбирает сама игра."""
    from backend.core import skins
    from shared.paths import get_minecraft_dir
    jar = get_minecraft_dir() / "versions" / "1.21.1" / "1.21.1.jar"
    jar.parent.mkdir(parents=True)
    with zipfile.ZipFile(jar, "w") as zf:
        zf.writestr("assets/minecraft/textures/entity/player/wide/steve.png", _png(64, 64))
        zf.writestr("assets/minecraft/textures/entity/player/slim/alex.png", _png(64, 64, "#cc6633"))
    info = client.get(f"/api/v1/auth/accounts/{offline}/skin").json()
    assert info["source"] == "default" and info["skin"].endswith(("steve.png", "alex.png"))
    assert info["slim"] == info["skin"].endswith("alex.png")
    # Чётность хэша UUID как у java.util.UUID.hashCode()
    assert skins.is_slim_default("00000000-0000-0000-0000-000000000001") is True
    assert skins.is_slim_default("00000000-0000-0000-0000-000000000000") is False


def test_custom_skin_and_cape(client, offline, tmp_path, gui):
    skin, cape = tmp_path / "my.png", tmp_path / "cape.png"
    skin.write_bytes(_png(64, 64))
    cape.write_bytes(_png(64, 32, "#aa0000"))
    r = client.put(f"/api/v1/auth/accounts/{offline}/skin", json={"path": str(skin), "slim": True})
    assert r.status_code == 200 and r.json()["source"] == "custom" and r.json()["slim"] is True
    r = client.put(f"/api/v1/auth/accounts/{offline}/cape", json={"path": str(cape)})
    assert r.json()["cape"].endswith("cape.png")
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    assert client.put(f"/api/v1/auth/accounts/{offline}/skin", json={"path": str(bad)}).status_code == 400
    r = client.delete(f"/api/v1/auth/accounts/{offline}/skin")
    assert r.json()["source"] == "default" and r.json()["cape"] == ""


def test_mojang_textures_cached(client, monkeypatch, gui):
    """Скин и плащ лицензионного ника скачиваются один раз и берутся из кэша."""
    import base64
    import json

    import httpx

    from backend.core import skins
    textures = {"textures": {"SKIN": {"url": "https://textures.minecraft.net/s", "metadata": {"model": "slim"}},
                             "CAPE": {"url": "https://textures.minecraft.net/c"}}}
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "users/profiles" in str(request.url):
            return httpx.Response(200, json={"id": "abc", "name": "jeb_"})
        if "session/minecraft/profile" in str(request.url):
            value = base64.b64encode(json.dumps(textures).encode()).decode()
            return httpx.Response(200, json={"properties": [{"name": "textures", "value": value}]})
        return httpx.Response(200, content=_png(64, 64) if request.url.path == "/s" else _png(64, 32))

    real = httpx.Client
    monkeypatch.setattr(skins, "_http", lambda: real(transport=httpx.MockTransport(handler)))
    first = skins._mojang_textures("jeb_")
    assert first["slim"] is True and first["skin"].endswith("skin.png") and first["cape"].endswith("cape.png")
    assert skins._mojang_textures("JEB_")["skin"] == first["skin"] and len(calls) == 4


def test_skin_view_renders_model_and_cape(gui, tmp_path):
    """Модель рисуется; плащ виден сзади и не просвечивает спереди."""
    from PySide6.QtGui import QColor, QImage, QPainter

    from frontend.quick.skinview import SkinView
    skin, cape = tmp_path / "s.png", tmp_path / "c.png"
    skin.write_bytes(_png(64, 64, "#2255dd"))
    cape.write_bytes(_png(64, 32, "#ff0000"))

    def render(yaw: float) -> QImage:
        view = SkinView()
        view.setWidth(120)
        view.setHeight(160)
        view.skin, view.cape, view.yaw = str(skin), str(cape), yaw
        image = QImage(120, 160, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        view.paint(painter)
        painter.end()
        return image

    def count(image: QImage, color: str) -> int:
        target = QColor(color)
        return sum(1 for x in range(0, 120, 2) for y in range(0, 160, 2)
                   if QColor(image.pixel(x, y)).red() == target.red() and QColor(image.pixel(x, y)).blue() == target.blue()
                   and QColor(image.pixel(x, y)).alpha() == 255)

    front, back = render(0), render(180)
    assert count(front, "#2255dd") > 300  # персонаж нарисован
    # Спереди виден разве что верхний край плаща за плечами (взгляд чуть сверху), сзади — весь плащ
    assert count(back, "#ff0000") > 100
    assert count(front, "#ff0000") * 8 < count(back, "#ff0000")


def test_step_account_switches_active(client, gui, monkeypatch):
    from test_quick_ui import _pump_until

    from backend.core import skins
    from frontend.backend_runner import EmbeddedBackend
    from frontend.quick.bridge import Shell
    from frontend.services.api_client import ApiClient
    monkeypatch.setattr(skins, "_mojang_textures", lambda name: {})
    backend = EmbeddedBackend()
    backend.start()
    api = ApiClient(backend.base_url, backend.token)
    try:
        for name in ("Alpha", "Bravo", "Charlie"):
            api.offline_login(name)
        shell = Shell(api, False, ("Segoe UI", "Consolas"))
        assert _pump_until(lambda: len(shell.accounts) == 3 and "source" in shell.skin)
        first = shell.account["name"]
        shell.stepAccount(1)
        assert _pump_until(lambda: shell.account["name"] != first and "source" in shell.skin)
        shell.stepAccount(-1)
        assert _pump_until(lambda: shell.account["name"] == first)
    finally:
        api.close()
        backend.stop()
