"""Автообновление лаунчера: подписанный манифест, SHA-256, загрузка и установка (без сети)."""

import base64
import hashlib
import io
import json
import zipfile

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.core import self_update
from shared.version import APP_VERSION

CHANNEL = "https://nexora.example/downloads/latest.json"
MIRROR = "https://mirror.example/latest.json"


def _zip_bytes(with_exe: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if with_exe:
            zf.writestr("NexoraLauncher/NexoraLauncher.exe", b"MZ-new")
        zf.writestr("NexoraLauncher/_internal/lib.dll", b"lib")
    return buffer.getvalue()


def _manifest(version: str, archive: bytes, **extra) -> dict:
    return {"version": version, "date": "2026-10-22",
            "zip": {"file": f"NexoraLauncher-{version}-windows-amd64.zip", "size": len(archive),
                    "sha256": hashlib.sha256(archive).hexdigest()},
            **extra}


@pytest.fixture
def channel(monkeypatch):
    """Поддельный канал обновлений с настоящей подписью Ed25519.

    ``state`` позволяет испортить любой кусок: манифест, подпись, архив, ответ сервера.
    """
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(self_update, "UPDATE_PUBLIC_KEY", base64.b64encode(public).decode("ascii"))
    monkeypatch.setattr(self_update, "UPDATE_MANIFEST_URLS", (CHANNEL,))
    monkeypatch.delenv("NEXORA_UPDATE_URL", raising=False)

    archive = _zip_bytes()
    state = {"zip": archive, "manifest": _manifest("99.0.0", archive),
             "sign_with": key, "status": {}, "raw": None, "signature": None}

    def body() -> bytes:
        if state["raw"] is not None:
            return state["raw"]
        return (json.dumps(state["manifest"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, code in state["status"].items():
            if url.startswith(prefix):
                return httpx.Response(code)
        if url.endswith(".json"):
            return httpx.Response(200, content=body())
        if url.endswith(".json.sig"):
            signature = state["signature"] or base64.b64encode(state["sign_with"].sign(body())).decode("ascii")
            return httpx.Response(200, text=signature + "\n")
        if url.endswith(".zip"):
            return httpx.Response(200, content=state["zip"])
        return httpx.Response(404)

    monkeypatch.setattr(self_update, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    return state


# --- Версии и настройка канала -------------------------------------------------------------------
def test_parse_version():
    assert self_update.parse_version("v1.10.2") == (1, 10, 2)
    assert self_update.parse_version("nexora-2.0.0-beta") == (2, 0, 0)
    assert self_update.parse_version("latest") is None


def test_channel_without_key_is_reported(client, monkeypatch):
    """Без вшитого ключа обновления не проверяются — и это видно, а не молча «всё свежее»."""
    monkeypatch.setattr(self_update, "UPDATE_PUBLIC_KEY", "")
    response = client.get("/api/v1/app/update")
    assert response.status_code == 400 and "не настроен" in response.json()["detail"]


def test_manifest_url_override(monkeypatch):
    monkeypatch.setenv("NEXORA_UPDATE_URL", "https://staging.example/latest.json")
    assert self_update.manifest_urls() == ["https://staging.example/latest.json"]


# --- Проверка подписи ----------------------------------------------------------------------------
def test_signed_manifest_is_accepted(client, channel):
    channel["manifest"] = _manifest("99.0.0", channel["zip"], notes="Что нового", page="https://nexora.example/")
    info = client.get("/api/v1/app/update").json()
    assert info["available"] and info["latest"] == "99.0.0"
    assert info["notes"] == "Что нового" and info["url"] == "https://nexora.example/"
    assert info["sha256"] == hashlib.sha256(channel["zip"]).hexdigest()
    assert info["asset_url"] == "https://nexora.example/downloads/NexoraLauncher-99.0.0-windows-amd64.zip"
    assert info["channel"] == CHANNEL
    assert info["can_install"] is False  # тесты запущены из исходников


def test_older_or_same_version_is_not_offered(client, channel):
    channel["manifest"] = _manifest(APP_VERSION, channel["zip"])
    assert client.get("/api/v1/app/update").json()["available"] is False
    channel["manifest"] = _manifest("0.9.0", channel["zip"])
    assert client.get("/api/v1/app/update").json()["available"] is False


def test_tampered_manifest_is_rejected(client, channel):
    """Подменённый манифест (подпись осталась от прежнего) не принимается."""
    good = (json.dumps(_manifest("99.0.0", channel["zip"]), ensure_ascii=False, indent=2) + "\n").encode()
    channel["signature"] = base64.b64encode(channel["sign_with"].sign(good)).decode("ascii")
    channel["raw"] = good.replace(b'"99.0.0"', b'"99.9.9"')
    response = client.get("/api/v1/app/update")
    assert response.status_code == 502 and "одпись" in response.json()["detail"]


def test_manifest_signed_by_stranger_is_rejected(client, channel):
    channel["sign_with"] = Ed25519PrivateKey.generate()  # чужой ключ
    response = client.get("/api/v1/app/update")
    assert response.status_code == 502 and "одпись" in response.json()["detail"]


def test_missing_signature_is_rejected(client, channel):
    channel["status"] = {CHANNEL + ".sig": 404}
    response = client.get("/api/v1/app/update")
    assert response.status_code == 502 and "обновлении" in response.json()["detail"]


def test_second_address_is_used_when_first_is_down(client, channel, monkeypatch):
    """Если свой сайт лежит, берётся запасной адрес — но подпись проверяется так же."""
    monkeypatch.setattr(self_update, "UPDATE_MANIFEST_URLS", (CHANNEL, MIRROR))
    channel["status"] = {CHANNEL: 503}
    info = client.get("/api/v1/app/update").json()
    assert info["available"] and info["channel"] == MIRROR
    assert info["asset_url"] == "https://mirror.example/NexoraLauncher-99.0.0-windows-amd64.zip"


# --- Загрузка ------------------------------------------------------------------------------------
def test_download_checks_hash_and_applies(client, wait_task, channel, monkeypatch, tmp_path):
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "done", task["error"]
    prepared = task["result"]["path"]
    assert (self_update.updates_dir() / "99.0.0" / "NexoraLauncher" / "NexoraLauncher.exe").exists()
    assert not list(self_update.updates_dir().glob("*.zip"))  # архив удалён после распаковки

    # Из исходников обновлять на месте нельзя
    assert client.post("/api/v1/app/update/apply", json={"path": prepared}).status_code == 400

    started = []
    install = tmp_path / "Program"
    install.mkdir()
    # Подменяем саму проверку, а не os.name: иначе pathlib на Linux начнёт создавать WindowsPath
    monkeypatch.setattr(self_update, "can_self_update", lambda: True)
    monkeypatch.setattr(self_update, "install_dir", lambda: install)
    monkeypatch.setattr(self_update.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    assert client.post("/api/v1/app/update/apply", json={"path": str(tmp_path)}).status_code == 400
    r = client.post("/api/v1/app/update/apply", json={"path": prepared})
    assert r.status_code == 200 and r.json() == {"restart": True}
    script = (self_update.updates_dir() / "apply_update.bat").read_text(encoding="utf-8")
    assert "Robocopy.exe" in script and str(install) in script and "NexoraLauncher.exe" in script
    assert f'rmdir /S /Q "{(self_update.updates_dir() / "99.0.0").resolve()}"' in script
    assert started and started[0][:2] == ["cmd", "/c"]


def test_substituted_archive_is_rejected(client, wait_task, channel):
    """Архив подменён байт в байт (размер сошёлся), манифест настоящий — спасает SHA-256."""
    tampered = bytearray(channel["zip"])
    tampered[-1] ^= 0xFF
    channel["zip"] = bytes(tampered)
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed" and "умма" in task["error"]
    assert not (self_update.updates_dir() / "99.0.0").exists()
    assert not list(self_update.updates_dir().glob("*.part"))


def test_truncated_archive_is_rejected(client, wait_task, channel):
    archive = channel["zip"]
    channel["manifest"] = _manifest("99.0.0", archive)
    channel["manifest"]["zip"]["size"] = len(archive) + 100  # обещали больше, чем пришло
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed" and "не полностью" in task["error"]


def test_manifest_without_hash_is_rejected(client, wait_task, channel):
    channel["manifest"]["zip"].pop("sha256")
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed" and "SHA-256" in task["error"]


def test_archive_without_exe_is_rejected(client, wait_task, channel):
    channel["zip"] = _zip_bytes(with_exe=False)
    channel["manifest"] = _manifest("99.0.0", channel["zip"])
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed" and "NexoraLauncher.exe" in task["error"]
    assert not (self_update.updates_dir() / "99.0.0").exists()


def test_download_of_same_version_is_refused(client, wait_task, channel):
    channel["manifest"] = _manifest(APP_VERSION, channel["zip"])
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed" and "последняя версия" in task["error"]


def test_settings_check_updates_flag(client):
    assert client.get("/api/v1/settings").json()["check_updates"] is True
    assert client.patch("/api/v1/settings", json={"check_updates": False}).json()["check_updates"] is False
