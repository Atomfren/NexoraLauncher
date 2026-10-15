"""Тесты API: инстансы, задачи, аккаунты, настройки, серверы, безопасность."""

import json
import time

import pytest

from backend.core.auth import offline_uuid
from backend.core.tasks import TaskManager, humanize_status
from shared.paths import get_config_dir, get_instances_dir


def create(client, name="Test", version="1.20.1", loader="vanilla"):
    return client.post("/api/v1/instances/", json={"name": name, "version": version, "mod_loader": loader,
                                                   "install": False})


# --- Инстансы ------------------------------------------------------------------------
def test_instance_crud(client):
    r = create(client)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test" and body["installed"] is False and body["running_pid"] is None
    assert (get_instances_dir() / "Test" / "instance.json").exists()

    assert create(client).status_code == 409
    assert [i["name"] for i in client.get("/api/v1/instances/").json()] == ["Test"]

    r = client.patch("/api/v1/instances/Test", json={"max_memory": 6144, "jvm_args": "-XX:+UseG1GC"})
    assert r.status_code == 200 and r.json()["max_memory"] == 6144

    assert client.delete("/api/v1/instances/Test").status_code == 204
    assert client.get("/api/v1/instances/Test").status_code == 404


@pytest.mark.parametrize("name", ["../evil", "a/b", "..", "CON"])
def test_instance_path_traversal_rejected(client, name):
    r = create(client, name=name)
    assert r.status_code in (400, 422)
    assert not (get_instances_dir().parent / "evil").exists()


def test_instance_invalid_loader(client):
    assert create(client, loader="optifine").status_code == 422


def test_update_loader_resets_launch_version(client):
    create(client, loader="fabric")
    client.patch("/api/v1/instances/Test", json={"loader_version": "0.15.0"})
    path = get_instances_dir() / "Test" / "instance.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["launch_version_id"] = "fabric-loader-0.15.0-1.20.1"
    path.write_text(json.dumps(data), encoding="utf-8")
    r = client.patch("/api/v1/instances/Test", json={"version": "1.20.4"})
    assert r.json()["launch_version_id"] == ""


def test_rename_and_duplicate(client):
    create(client)
    r = client.post("/api/v1/instances/Test/rename", json={"new_name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    assert client.get("/api/v1/instances/Test").status_code == 404
    r = client.post("/api/v1/instances/Renamed/duplicate", json={"new_name": "Copy"})
    assert r.status_code == 201 and r.json()["play_count"] == 0
    assert client.post("/api/v1/instances/Renamed/rename", json={"new_name": "Copy"}).status_code == 409


# --- Задачи --------------------------------------------------------------------------
def test_task_manager_lifecycle():
    manager = TaskManager(max_workers=2)

    def ok(task):
        task.set_max(4)
        task.set_progress(2)
        return {"answer": 42}

    def fail(task):
        raise ValueError("boom")

    def slow(task):
        for _ in range(200):
            task.check_cancelled()
            time.sleep(0.01)

    done = manager.wait(manager.submit("t", "ok", ok).id)
    assert done.status == "done" and done.result == {"answer": 42} and done.progress == 1.0
    failed = manager.wait(manager.submit("t", "fail", fail).id)
    assert failed.status == "failed" and "boom" in failed.error
    task = manager.submit("t", "slow", slow)
    time.sleep(0.05)
    manager.cancel(task.id)
    assert manager.wait(task.id).status == "cancelled"
    manager.shutdown()


def test_humanize_status():
    assert humanize_status("Download Assets", "") == "Загрузка ресурсов игры…"
    assert humanize_status("Download a1b2c3", "Загрузка библиотек…") == "Загрузка библиотек…"
    assert humanize_status("Custom", "x") == "Custom"


def test_tasks_api_404(client):
    assert client.get("/api/v1/tasks/nope").status_code == 404


# --- Аккаунты ------------------------------------------------------------------------
def test_offline_uuid_matches_vanilla_server():
    # Значение, которое выдаёт ванильный сервер в offline-mode для «Steve»
    assert offline_uuid("Steve") == "5627dd98-e6be-3c21-b8a8-e92344183641"


def test_accounts_flow(client):
    assert client.get("/api/v1/auth/profile").status_code == 404
    assert client.post("/api/v1/auth/offline/login", json={"username": "bad name!"}).status_code in (400, 422)
    steve = client.post("/api/v1/auth/offline/login", json={"username": "Steve"}).json()
    alex = client.post("/api/v1/auth/offline/login", json={"username": "Alex"}).json()
    assert alex["active"] is True
    accounts = client.get("/api/v1/auth/accounts").json()
    assert len(accounts) == 2
    r = client.post(f"/api/v1/auth/accounts/{steve['id']}/activate")
    assert r.json()["active"] is True
    assert client.get("/api/v1/auth/profile").json()["username"] == "Steve"
    # Повторный вход тем же ником не создаёт дубликат
    client.post("/api/v1/auth/offline/login", json={"username": "Steve"})
    assert len(client.get("/api/v1/auth/accounts").json()) == 2
    assert client.delete(f"/api/v1/auth/accounts/{steve['id']}").status_code == 204
    assert client.get("/api/v1/auth/profile").json()["username"] == "Alex"


def test_microsoft_tokens_are_encrypted_on_disk():
    from backend.core.auth import Account, AccountStore
    account = Account(id="1", username="Notch", uuid="069a79f4-44e9-4726-a5be-fca90e38aaf5",
                      auth_type="microsoft")
    account.set_tokens("SECRET_ACCESS_TOKEN", "SECRET_REFRESH_TOKEN", 3600)
    AccountStore.save([account], "1")
    raw = (get_config_dir() / "accounts.json").read_text(encoding="utf-8")
    assert "SECRET_ACCESS_TOKEN" not in raw and "SECRET_REFRESH_TOKEN" not in raw
    loaded, _ = AccountStore.load()
    assert loaded[0].access_token == "SECRET_ACCESS_TOKEN"


def test_legacy_profile_migrated_and_deleted(client):
    legacy = get_config_dir() / "profile.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"username": "OldUser", "uuid": "x", "auth_type": "offline",
                                  "access_token": "PLAINTEXT"}), encoding="utf-8")
    accounts = client.get("/api/v1/auth/accounts").json()
    assert [a["username"] for a in accounts] == ["OldUser"] and accounts[0]["active"]
    assert not legacy.exists()


def test_microsoft_login_requires_client_id(client):
    r = client.post("/api/v1/auth/microsoft/login/start")
    assert r.status_code == 400 and "Client ID" in r.json()["detail"]


def test_launch_without_account_is_401(client):
    create(client)
    r = client.post("/api/v1/instances/Test/launch")
    assert r.status_code == 401


# --- Настройки -------------------------------------------------------------------------
def test_settings_api(client):
    assert client.get("/api/v1/settings/").json()["language"] == "ru"
    r = client.patch("/api/v1/settings/", json={"language": "en", "max_memory": 8192, "ms_client_id": "abc"})
    assert r.status_code == 200
    body = client.get("/api/v1/settings/").json()
    assert body["language"] == "en" and body["max_memory"] == 8192 and body["ms_client_id"] == "abc"
    assert client.patch("/api/v1/settings/", json={"language": "xx"}).status_code == 422
    assert client.get("/api/v1/settings/system").json()["total_memory_mb"] > 0


# --- Серверы ---------------------------------------------------------------------------
def test_servers_crud_and_ping(client, monkeypatch):
    from backend.api.v1 import servers as servers_api
    from backend.core.server_ping import PingResult
    monkeypatch.setattr(servers_api, "ping_server",
                        lambda host, port: PingResult(online=True, player_count=3, max_players=20, motd="Hi"))
    server = client.post("/api/v1/servers/", json={"name": "Local", "host": "localhost", "port": 25566}).json()
    assert server["port"] == 25566
    assert client.patch(f"/api/v1/servers/{server['id']}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    ping = client.get(f"/api/v1/servers/{server['id']}/ping").json()
    assert ping["online"] and ping["player_count"] == 3
    assert client.delete(f"/api/v1/servers/{server['id']}").status_code == 204
    assert client.get(f"/api/v1/servers/{server['id']}").status_code == 404


def test_connect_without_instances(client):
    server = client.post("/api/v1/servers/", json={"name": "S", "host": "example.org"}).json()
    r = client.post(f"/api/v1/servers/{server['id']}/connect")
    assert r.status_code == 400


# --- Безопасность ----------------------------------------------------------------------
def test_api_token_required(client, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "api_token", "s3cret")
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/instances/").status_code == 401
    assert client.get("/api/v1/instances/", headers={"X-Nexora-Token": "wrong"}).status_code == 401
    assert client.get("/api/v1/instances/", headers={"X-Nexora-Token": "s3cret"}).status_code == 200


def test_no_wildcard_cors(client):
    r = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_ai_status_without_library(client):
    body = client.get("/api/v1/ai/status").json()
    assert body["available"] is False
