"""Автообновление лаунчера: проверка релиза, загрузка, установка (без сети)."""

import io
import zipfile

import httpx
import pytest

from backend.core import self_update
from shared.version import APP_VERSION


def _zip_bytes(with_exe: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        if with_exe:
            zf.writestr("NexoraLauncher/NexoraLauncher.exe", b"MZ-new")
        zf.writestr("NexoraLauncher/_internal/lib.dll", b"lib")
    return buffer.getvalue()


@pytest.fixture
def github(monkeypatch):
    """Поддельный GitHub: state["release"] — ответ API (None → 404), state["zip"] — архив."""
    state = {"release": None, "zip": _zip_bytes()}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            if state["release"] is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=state["release"])
        if request.url.path.endswith(".zip"):
            return httpx.Response(200, content=state["zip"])
        return httpx.Response(404)

    monkeypatch.setattr(self_update, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler),
                                                                       follow_redirects=True))
    return state


def _release(tag: str, size: int) -> dict:
    return {"tag_name": tag, "html_url": f"https://github.com/Atomfren/NexoraLauncher/releases/tag/{tag}",
            "body": "Что нового", "assets": [
                {"name": "notes.txt", "browser_download_url": "https://x/notes.txt", "size": 1},
                {"name": f"NexoraLauncher-{tag[1:]}-windows-amd64.zip",
                 "browser_download_url": f"https://github.com/dl/NexoraLauncher-{tag[1:]}-windows-amd64.zip",
                 "size": size}]}


def test_parse_version():
    assert self_update.parse_version("v1.10.2") == (1, 10, 2)
    assert self_update.parse_version("nexora-2.0.0-beta") == (2, 0, 0)
    assert self_update.parse_version("latest") is None


def test_no_releases(client, github):
    data = client.get("/api/v1/app/update").json()
    assert data["available"] is False and data["current"] == APP_VERSION


def test_older_or_same_release_is_not_offered(client, github):
    github["release"] = _release(f"v{APP_VERSION}", 10)
    assert client.get("/api/v1/app/update").json()["available"] is False
    github["release"] = _release("v0.9.0", 10)
    assert client.get("/api/v1/app/update").json()["available"] is False


def test_download_and_apply(client, wait_task, github, monkeypatch, tmp_path):
    github["release"] = _release("v99.0.0", len(github["zip"]))
    info = client.get("/api/v1/app/update").json()
    assert info["available"] and info["latest"] == "99.0.0" and info["notes"] == "Что нового"
    assert info["asset_url"].endswith("windows-amd64.zip")
    assert info["can_install"] is False  # тесты запущены из исходников

    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "done", task["error"]
    prepared = task["result"]["path"]
    assert (self_update.updates_dir() / "99.0.0" / "NexoraLauncher" / "NexoraLauncher.exe").exists()

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


def test_broken_archive_is_rejected(client, wait_task, github):
    github["zip"] = _zip_bytes(with_exe=False)
    github["release"] = _release("v99.0.0", len(github["zip"]))
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed" and "NexoraLauncher.exe" in task["error"]
    assert not (self_update.updates_dir() / "99.0.0").exists()

    github["release"] = _release("v99.0.0", len(github["zip"]) + 100)  # размер не совпал
    task = wait_task(client.post("/api/v1/app/update/download").json()["id"])
    assert task["status"] == "failed"


def test_settings_check_updates_flag(client):
    assert client.get("/api/v1/settings").json()["check_updates"] is True
    assert client.patch("/api/v1/settings", json={"check_updates": False}).json()["check_updates"] is False
