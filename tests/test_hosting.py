"""Свой сервер: создание, установка, запуск, консоль, туннель, настройки (без сети и Java)."""

import json
import sys
import time
import zipfile

import httpx
import pytest

from backend.core import hosting
from backend.core.hosting import HostingManager

# Поддельное «ядро сервера»: печатает строки как настоящий сервер с e4mc и ждёт команду stop
FAKE_SERVER = r"""
import sys
print('[12:00:00] [main/INFO]: Starting minecraft server version 1.20.1', flush=True)
print('[12:00:01] [e4mc/INFO]: Domain assigned: brave-fox.sg.e4mc.link', flush=True)
print('[12:00:02] [Server thread/INFO]: Done (1.234s)! For help, type "help"', flush=True)
print('[12:00:03] [Server thread/INFO]: Steve joined the game', flush=True)
for line in sys.stdin:
    cmd = line.strip()
    print(f'[12:00:04] [Server thread/INFO]: executed {cmd}', flush=True)
    if cmd.startswith('save-all'):
        print('[12:00:04] [Server thread/INFO]: Saved the game', flush=True)
    if cmd == 'kick Steve':
        print('[12:00:05] [Server thread/INFO]: Steve left the game', flush=True)
    if cmd == 'stop':
        print('[12:00:06] [Server thread/INFO]: Stopping server', flush=True)
        break
"""


@pytest.fixture
def fake_server_env(monkeypatch, modrinth, fake_minecraft):
    """Ядро Fabric, Java и мод e4mc подменены."""
    import minecraft_launcher_lib as mll

    monkeypatch.setattr(HostingManager, "_java_component", staticmethod(lambda version: "java-runtime-gamma"))
    monkeypatch.setattr(mll.runtime, "get_executable_path", lambda component, directory: sys.executable)
    monkeypatch.setattr(mll.fabric, "get_latest_installer_version", lambda: "1.0.1")
    real_client = httpx.Client

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, content=b"fabric-jar"))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(hosting.httpx, "Client", fake_client)
    monkeypatch.setattr(HostingManager, "build_command",
                        staticmethod(lambda server, java: [sys.executable, "-u", "-c", FAKE_SERVER]))
    modrinth.add_project("fabric-api", "Fabric API", "fabric-api.jar")
    modrinth.add_project("e4mc", "e4mc", "e4mc-6.2.3-fabric.jar", deps=["fabric-api"])
    return modrinth


def _create(client, wait_task, name="Friends"):
    r = client.post("/api/v1/hosting/servers", json={"name": name, "version": "1.20.1", "max_memory": 2048,
                                                     "accept_eula": True})
    assert r.status_code == 201, r.text
    task = wait_task(r.json()["task"]["id"])
    assert task["status"] == "done", task["error"]
    return client.get(f"/api/v1/hosting/servers/{name}").json()


def _wait_state(client, name, predicate, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/v1/hosting/servers/{name}").json()
        if predicate(status):
            return status
        time.sleep(0.1)
    raise AssertionError(f"Состояние не достигнуто: {status}")


def test_eula_required(client):
    r = client.post("/api/v1/hosting/servers", json={"name": "S", "version": "1.20.1", "accept_eula": False})
    assert r.status_code == 400 and "EULA" in r.json()["detail"]


def test_create_install_start_stop(client, wait_task, fake_server_env):
    server = _create(client, wait_task)
    assert server["installed"] and server["loader_version"] == "9.9.9" and server["state"] == "stopped"
    assert server["port"] >= 25565
    mods = {m["filename"] for m in client.get("/api/v1/hosting/servers/Friends/mods").json()}
    assert {"e4mc-6.2.3-fabric.jar", "fabric-api.jar"} <= mods
    props = client.get("/api/v1/hosting/servers/Friends/properties").json()
    assert props["server-port"] == str(server["port"]) and props["online-mode"] == "false"

    assert client.post("/api/v1/hosting/servers/Friends/start").status_code == 200
    status = _wait_state(client, "Friends", lambda s: s["state"] == "running" and s["players"])
    assert status["public_address"] == "brave-fox.sg.e4mc.link"
    assert status["players"] == ["Steve"]
    assert client.post("/api/v1/hosting/servers/Friends/start").status_code == 409
    assert (hosting.servers_dir() / "Friends" / "eula.txt").read_text(encoding="utf-8").strip().endswith("eula=true")

    assert client.post("/api/v1/hosting/servers/Friends/command", json={"command": "/kick Steve"}).status_code == 204
    _wait_state(client, "Friends", lambda s: not s["players"])
    console = client.get("/api/v1/hosting/servers/Friends/console").json()
    assert "> kick Steve" in console and any("executed kick Steve" in line for line in console)
    assert client.delete("/api/v1/hosting/servers/Friends").status_code == 409  # нельзя удалить работающий

    client.post("/api/v1/hosting/servers/Friends/stop")
    status = _wait_state(client, "Friends", lambda s: s["state"] in ("stopped", "crashed"))
    assert status["state"] == "stopped" and status["public_address"] == ""
    assert client.post("/api/v1/hosting/servers/Friends/command", json={"command": "say hi"}).status_code == 400
    assert client.delete("/api/v1/hosting/servers/Friends").status_code == 204


def test_tunnel_toggle_disables_mod(client, wait_task, fake_server_env):
    _create(client, wait_task)
    client.patch("/api/v1/hosting/servers/Friends", json={"tunnel": False})
    client.post("/api/v1/hosting/servers/Friends/start")
    files = {p.name for p in (hosting.servers_dir() / "Friends" / "mods").iterdir()}
    assert "e4mc-6.2.3-fabric.jar.disabled" in files
    client.post("/api/v1/hosting/servers/Friends/stop")
    _wait_state(client, "Friends", lambda s: s["state"] in ("stopped", "crashed"))
    client.patch("/api/v1/hosting/servers/Friends", json={"tunnel": True})
    client.post("/api/v1/hosting/servers/Friends/start")
    files = {p.name for p in (hosting.servers_dir() / "Friends" / "mods").iterdir()}
    assert "e4mc-6.2.3-fabric.jar" in files
    client.post("/api/v1/hosting/servers/Friends/stop")
    _wait_state(client, "Friends", lambda s: s["state"] in ("stopped", "crashed"))


def test_properties_validation(client, wait_task, fake_server_env):
    _create(client, wait_task)
    r = client.patch("/api/v1/hosting/servers/Friends/properties",
                     json={"motd": "Привет", "white-list": True, "max-players": 4})
    assert r.status_code == 200
    props = client.get("/api/v1/hosting/servers/Friends/properties").json()
    assert props["motd"] == "Привет" and props["white-list"] == "true" and props["max-players"] == "4"
    assert client.patch("/api/v1/hosting/servers/Friends/properties", json={"server-port": 1}).status_code == 400
    assert client.patch("/api/v1/hosting/servers/Friends/properties",
                        json={"motd": "a\nonline-mode=true"}).status_code == 400


def test_name_and_duplicates(client, fake_server_env):
    body = {"version": "1.20.1", "accept_eula": True}
    assert client.post("/api/v1/hosting/servers", json={"name": "../evil", **body}).status_code == 400
    assert client.post("/api/v1/hosting/servers", json={"name": "Dup", **body}).status_code == 201
    assert client.post("/api/v1/hosting/servers", json={"name": "Dup", **body}).status_code == 409


def test_start_requires_install(client, monkeypatch):
    HostingManager.create("Raw", "1.20.1")
    r = client.post("/api/v1/hosting/servers/Raw/start")
    assert r.status_code == 400 and "не установлен" in r.json()["detail"]


def test_friends_pack_excludes_tunnel(client, wait_task, fake_server_env, tmp_path):
    _create(client, wait_task)
    fake_server_env.projects["e4mc"]["client_side"] = "optional"
    fake_server_env.projects["fabric-api"]["client_side"] = "required"
    dest = tmp_path / "friends.mrpack"
    task = client.post("/api/v1/hosting/servers/Friends/client_pack", json={"path": str(dest)}).json()
    result = wait_task(task["id"])
    assert result["status"] == "done", result["error"]
    with zipfile.ZipFile(dest) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
    assert [f["path"] for f in index["files"]] == ["mods/fabric-api.jar"]
    assert index["dependencies"] == {"minecraft": "1.20.1", "fabric-loader": "9.9.9"}


def test_play_with_friends_prepares_instance(client, wait_task, modrinth):
    modrinth.add_project("fabric-api", "Fabric API", "fabric-api.jar")
    modrinth.add_project("e4mc", "e4mc", "e4mc.jar", deps=["fabric-api"])
    client.post("/api/v1/instances/", json={"name": "Mine", "version": "1.20.1", "mod_loader": "fabric",
                                            "install": False})
    result = wait_task(client.post("/api/v1/instances/Mine/friends/prepare").json()["id"])
    assert result["status"] == "done" and result["result"] == {"installed": True}
    files = {i["filename"] for i in client.get("/api/v1/instances/Mine/content/mod").json()}
    assert {"e4mc.jar", "fabric-api.jar"} <= files
    client.post("/api/v1/instances/", json={"name": "Van", "version": "1.20.1", "install": False})
    assert client.post("/api/v1/instances/Van/friends/prepare").status_code == 400


def test_game_process_reports_e4mc_domain(client, wait_task, monkeypatch):
    from backend.core.minecraft import MinecraftManager
    client.post("/api/v1/auth/offline/login", json={"username": "Tester"})
    client.post("/api/v1/instances/", json={"name": "Host", "version": "1.20.1", "install": False})
    monkeypatch.setattr(MinecraftManager, "prepare_instance", lambda self, inst, task=None, force=False: "1.20.1")
    script = ("import time; print('[e4mc/INFO]: Domain assigned: lucky-cat.eu.e4mc.link', flush=True); "
              "time.sleep(1.5)")
    monkeypatch.setattr(MinecraftManager, "build_command", lambda self, *a, **k: [sys.executable, "-c", script])
    pid = wait_task(client.post("/api/v1/instances/Host/launch").json()["id"])["result"]["pid"]
    for _ in range(50):
        process = client.get(f"/api/v1/minecraft/processes/{pid}").json()
        if process["public_address"]:
            break
        time.sleep(0.05)
    assert process["public_address"] == "lucky-cat.eu.e4mc.link"


def _make_world(name="Friends", text="v1"):
    world = hosting.servers_dir() / name / "world"
    (world / "region").mkdir(parents=True, exist_ok=True)
    (world / "level.dat").write_text(text, encoding="utf-8")
    (world / "region" / "r.0.0.mca").write_text(text * 10, encoding="utf-8")
    (world / "session.lock").write_text("lock", encoding="utf-8")
    return world


def test_backups_create_restore_prune(client, wait_task, fake_server_env):
    _create(client, wait_task)
    r = client.post("/api/v1/hosting/servers/Friends/backups")
    assert wait_task(r.json()["id"])["status"] == "failed"  # мира ещё нет

    world = _make_world(text="v1")
    task = wait_task(client.post("/api/v1/hosting/servers/Friends/backups").json()["id"])
    assert task["status"] == "done", task["error"]
    backups = client.get("/api/v1/hosting/servers/Friends/backups").json()
    assert len(backups) == 1 and backups[0]["reason"] == "manual"
    with zipfile.ZipFile(hosting.backups_dir() / "Friends" / backups[0]["filename"]) as zf:
        names = set(zf.namelist())
    assert {"world/level.dat", "world/region/r.0.0.mca", "server.properties"} <= names
    assert "world/session.lock" not in names

    (world / "level.dat").write_text("v2-broken", encoding="utf-8")
    (world / "junk.dat").write_text("junk", encoding="utf-8")
    task = wait_task(client.post(f"/api/v1/hosting/servers/Friends/backups/{backups[0]['filename']}/restore")
                     .json()["id"])
    assert task["status"] == "done", task["error"]
    assert (world / "level.dat").read_text(encoding="utf-8") == "v1"
    assert not (world / "junk.dat").exists()
    reasons = sorted(b["reason"] for b in client.get("/api/v1/hosting/servers/Friends/backups").json())
    assert reasons == ["before-restore", "manual"]

    # Автокопии сверх лимита удаляются, ручные остаются
    client.patch("/api/v1/hosting/servers/Friends", json={"backups_keep": 2})
    for _ in range(4):
        hosting.create_backup("Friends", "auto")
    backups = client.get("/api/v1/hosting/servers/Friends/backups").json()
    assert sum(b["reason"] == "auto" for b in backups) == 2
    assert any(b["reason"] == "manual" for b in backups)

    assert client.post("/api/v1/hosting/servers/Friends/backups/..%2Fx.zip/restore").status_code in (400, 404)
    name = backups[0]["filename"]
    assert client.delete(f"/api/v1/hosting/servers/Friends/backups/{name}").status_code == 204
    assert client.delete(f"/api/v1/hosting/servers/Friends/backups/{name}").status_code == 404


def test_backup_of_running_server_and_auto_backup_on_stop(client, wait_task, fake_server_env):
    _create(client, wait_task)
    _make_world()
    client.post("/api/v1/hosting/servers/Friends/start")
    _wait_state(client, "Friends", lambda s: s["state"] == "running")
    task = wait_task(client.post("/api/v1/hosting/servers/Friends/backups").json()["id"])
    assert task["status"] == "done", task["error"]
    console = client.get("/api/v1/hosting/servers/Friends/console").json()
    assert "> save-off" in console and "> save-all flush" in console and "> save-on" in console

    client.post("/api/v1/hosting/servers/Friends/stop")
    _wait_state(client, "Friends", lambda s: s["state"] in ("stopped", "crashed"))
    deadline = time.time() + 10
    while time.time() < deadline:
        reasons = [b["reason"] for b in client.get("/api/v1/hosting/servers/Friends/backups").json()]
        if "auto" in reasons:
            break
        time.sleep(0.1)
    assert reasons.count("auto") == 1 and reasons.count("manual") == 1


@pytest.fixture
def paper_env(monkeypatch, modrinth, fake_minecraft):
    """Ядро Paper: API PaperMC подменён, Java — текущий Python."""
    import minecraft_launcher_lib as mll

    monkeypatch.setattr(HostingManager, "_java_component", staticmethod(lambda version: "java-runtime-delta"))
    monkeypatch.setattr(mll.runtime, "get_executable_path", lambda component, directory: sys.executable)
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/versions/1.21.4/builds/latest"):
            return httpx.Response(200, json={"id": 232, "channel": "STABLE", "downloads": {"server:default": {
                "name": "paper-1.21.4-232.jar", "url": "https://fill-data.papermc.io/v1/objects/x/paper.jar"}}})
        if url.endswith("/paper.jar"):
            return httpx.Response(200, content=b"paper-jar")
        return httpx.Response(404, json={"ok": False})

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(hosting.httpx, "Client", fake_client)
    monkeypatch.setattr(HostingManager, "build_command",
                        staticmethod(lambda server, java: [sys.executable, "-u", "-c", FAKE_SERVER]))
    modrinth.add_project("luckperms", "LuckPerms", "LuckPerms-Bukkit.jar", loaders=["bukkit", "paper", "spigot"],
                         game_versions=["1.21.4"], project_type="plugin")
    modrinth.add_project("sodium", "Sodium", "sodium.jar", game_versions=["1.21.4"])


def test_paper_server_with_plugins(client, wait_task, paper_env):
    r = client.post("/api/v1/hosting/servers", json={"name": "Paper", "version": "1.21.4", "core": "paper",
                                                     "accept_eula": True})
    assert r.status_code == 201, r.text
    task = wait_task(r.json()["task"]["id"])
    assert task["status"] == "done", task["error"]
    server = client.get("/api/v1/hosting/servers/Paper").json()
    assert server["core"] == "paper" and server["loader_version"] == "232"
    assert server["content_type"] == "plugin" and not server["tunnel_supported"] and not server["tunnel"]
    assert (hosting.servers_dir() / "Paper" / "server.jar").read_bytes() == b"paper-jar"
    assert not (hosting.servers_dir() / "Paper" / "mods").exists()  # e4mc не ставится

    task = wait_task(client.post("/api/v1/hosting/servers/Paper/mods", json={"project_id": "luckperms"}).json()["id"])
    assert task["status"] == "done", task["error"]
    assert (hosting.servers_dir() / "Paper" / "plugins" / "LuckPerms-Bukkit.jar").exists()
    plugins = client.get("/api/v1/hosting/servers/Paper/mods").json()
    assert [p["filename"] for p in plugins] == ["LuckPerms-Bukkit.jar"]
    # Fabric-мод на Paper не ставится
    task = wait_task(client.post("/api/v1/hosting/servers/Paper/mods", json={"project_id": "sodium"}).json()["id"])
    assert task["status"] == "failed"
    task = wait_task(client.post("/api/v1/hosting/servers/Paper/client_pack", json={"path": "x.mrpack"}).json()["id"])
    assert task["status"] == "failed"  # сборка для друзей — только для Fabric

    assert client.delete("/api/v1/hosting/servers/Paper/mods/LuckPerms-Bukkit.jar").status_code == 204
    assert client.get("/api/v1/hosting/servers/Paper/mods").json() == []


def test_unsupported_core_version_and_vanilla(client, wait_task, paper_env, monkeypatch):
    r = client.post("/api/v1/hosting/servers", json={"name": "Old", "version": "1.7.10", "core": "paper",
                                                     "accept_eula": True})
    task = wait_task(r.json()["task"]["id"])
    assert task["status"] == "failed" and "Paper не поддерживает" in task["error"]
    assert client.post("/api/v1/hosting/servers", json={"name": "Bad", "version": "1.21.4", "core": "spigot",
                                                        "accept_eula": True}).status_code == 422

    monkeypatch.setattr(HostingManager, "_version_data", staticmethod(lambda version: {
        "downloads": {"server": {"url": "https://piston-data.mojang.com/v1/objects/abc/paper.jar"}}}))
    r = client.post("/api/v1/hosting/servers", json={"name": "Vanilla", "version": "1.21.4", "core": "vanilla",
                                                     "accept_eula": True})
    task = wait_task(r.json()["task"]["id"])
    assert task["status"] == "done", task["error"]
    server = client.get("/api/v1/hosting/servers/Vanilla").json()
    assert server["content_type"] is None and (hosting.servers_dir() / "Vanilla" / "server.jar").exists()
    assert client.post("/api/v1/hosting/servers/Vanilla/mods", json={"project_id": "luckperms"}).status_code == 400
