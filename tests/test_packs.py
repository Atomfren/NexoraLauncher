"""Сборки FTB и CurseForge (All The Mods) через API FTB: поиск, установка, архив конфигов, запасной путь."""

import hashlib
import io
import json
import zipfile

import httpx
import pytest

from shared.paths import get_instances_dir

MOD = b"mod-jar-bytes"
CONFIG = b"# config"


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _cf_pack_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"overrides": "overrides"}))
        zf.writestr("overrides/config/atm.toml", "quests = true")
        zf.writestr("overrides/kubejs/startup.js", "// script")
        zf.writestr("../evil.txt", "zip-slip")
    return buf.getvalue()


class FakeFtb:
    """Поддельный API FTB: одна сборка FTB (id 5) и ATM10 с CurseForge (id 925200)."""

    def __init__(self):
        self.requests: list[str] = []
        self.down = False
        pack_zip = _cf_pack_zip()
        self.blobs = {"/mod.jar": MOD, "/cfg": CONFIG, "/atm.zip": pack_zip}
        self.packs = {
            ("modpack", 5): {"id": 5, "name": "FTB StoneBlock 4", "synopsis": "Каменный мир", "installs": 2155606,
                             "authors": [{"name": "FTB Team"}], "tags": [{"name": "Skyblock"}],
                             "art": [{"type": "square", "url": "https://cdn/x.webp"},
                                     {"type": "screenshot", "url": "https://cdn/s1.webp"}],
                             "versions": [
                                 {"id": 10, "name": "1.0.0", "type": "release", "updated": 100,
                                  "targets": [{"type": "game", "name": "minecraft", "version": "1.21.1"},
                                              {"type": "modloader", "name": "neoforge", "version": "21.1.80"}]},
                                 {"id": 11, "name": "1.1.0-beta", "type": "beta", "updated": 200, "targets": []}]},
            ("curseforge", 925200): {"id": 925200, "name": "All the Mods 10 - ATM10", "installs": 22491105,
                                     "authors": [{"name": "ATMTeam"}], "art": [],
                                     "versions": [{"id": 9190157, "name": "All the Mods 10-8.3.zip", "type": "release",
                                                   "updated": 300,
                                                   "targets": [{"type": "game", "name": "minecraft",
                                                                "version": "1.21.1"},
                                                               {"type": "modloader", "name": "neoforge",
                                                                "version": "NeoForge"}]}]},
        }
        self.manifests = {
            ("modpack", 5, 10): {"name": "1.0.0", "specs": {"recommended": 6144},
                                 "targets": [{"type": "game", "name": "minecraft", "version": "1.21.1"},
                                             {"type": "modloader", "name": "neoforge", "version": "21.1.80"}],
                                 "files": [
                                     {"path": "./mods/", "name": "stone.jar", "url": "https://files/mod.jar",
                                      "sha1": _sha1(MOD), "type": "mod"},
                                     {"path": "./config", "name": "stone.cfg", "url": "https://files/cfg",
                                      "sha1": _sha1(CONFIG), "type": "config"},
                                     {"path": "./mods/", "name": "server-only.jar", "url": "https://files/mod.jar",
                                      "sha1": _sha1(MOD), "serveronly": True},
                                 ]},
            ("curseforge", 925200, 9190157): {
                "name": "All the Mods 10-8.3",
                "targets": [{"type": "game", "name": "minecraft", "version": "1.21.1"},
                            {"type": "modloader", "name": "neoforge", "version": "21.1.259"}],
                "files": [
                    {"path": "mods/", "name": "atm-core.jar", "url": "https://edge.forgecdn.net/mod.jar",
                     "sha1": _sha1(MOD), "type": "release"},
                    {"path": "./", "name": "overrides.zip", "url": "https://edge.forgecdn.net/atm.zip", "id": 9190157,
                     "sha1": _sha1(pack_zip), "type": "cf-extract"},
                ]},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if "api.feed-the-beast.com" not in url:
            return httpx.Response(200, content=self.blobs.get(request.url.path, b""))
        if self.down:
            return httpx.Response(503)
        path = request.url.path.split("/public", 1)[1]
        parts = path.strip("/").split("/")
        if parts[:2] == ["modpack", "search"]:
            return httpx.Response(200, json={"packs": [5], "curseforge": [925200, 404]})
        if parts[:2] in (["modpack", "featured"], ["modpack", "popular"]):
            return httpx.Response(200, json={"packs": [5]})
        kind, pack_id = parts[0], int(parts[1])
        if len(parts) == 3:
            return httpx.Response(200, json=self.manifests[(kind, pack_id, int(parts[2]))])
        if (kind, pack_id) not in self.packs:
            return httpx.Response(200, json={"status": "error", "message": "not found"})
        return httpx.Response(200, json=self.packs[(kind, pack_id)])


@pytest.fixture
def ftb(monkeypatch):
    from backend.core import ftb_packs
    fake = FakeFtb()
    real = httpx.Client
    monkeypatch.setattr(ftb_packs, "_client", lambda: real(transport=httpx.MockTransport(fake.handler),
                                                           follow_redirects=True))
    monkeypatch.setattr(ftb_packs.time, "sleep", lambda s: None)
    ftb_packs._cache.clear()
    return fake


def test_search_ftb_and_curseforge(client, ftb):
    rows = client.get("/api/v1/packs/ftb/search", params={"q": "stone"}).json()["results"]
    assert [r["project_id"] for r in rows] == ["ftb:5"]
    row = rows[0]
    assert row["game_versions"] == ["1.21.1"] and row["loaders"] == ["neoforge"]  # свежая стабильная, не beta
    assert row["icon_url"] == "https://cdn/x.webp" and row["gallery"] == ["https://cdn/s1.webp"]
    # Пустой поиск CurseForge — семейство All The Mods; несуществующая сборка пропускается
    rows = client.get("/api/v1/packs/curseforge/search").json()["results"]
    assert [r["title"] for r in rows] == ["All the Mods 10 - ATM10"]
    assert any("term=all%20the%20mods" in u for u in ftb.requests)
    assert client.get("/api/v1/packs/steam/search").status_code == 400


def test_install_ftb_pack(client, ftb, fake_minecraft, wait_task):
    task = wait_task(client.post("/api/v1/packs/ftb/5/install", json={}).json()["id"])
    assert task["status"] == "done", task["error"]
    name = task["result"]["name"]
    instance = client.get(f"/api/v1/instances/{name}").json()
    assert instance["title"] == "" and name == "FTB StoneBlock 4"
    assert (instance["mod_loader"], instance["loader_version"], instance["version"]) == ("neoforge", "21.1.80", "1.21.1")
    assert instance["max_memory"] == 6144  # рекомендованная память сборки
    game = get_instances_dir() / name / ".minecraft"
    assert (game / "mods" / "stone.jar").read_bytes() == MOD
    assert (game / "config" / "stone.cfg").read_bytes() == CONFIG
    assert not (game / "mods" / "server-only.jar").exists()
    meta = json.loads((get_instances_dir() / name / "pack.json").read_text(encoding="utf-8"))
    assert meta == {"provider": "ftb", "pack_id": 5, "version_id": 10, "version": "1.0.0", "name": "FTB StoneBlock 4"}


def test_install_all_the_mods_with_overrides(client, ftb, fake_minecraft, wait_task):
    """ATM10: моды с CDN CurseForge + конфиги и квесты из архива сборки (overrides), без выхода за папку."""
    task = wait_task(client.post("/api/v1/packs/curseforge/925200/install", json={}).json()["id"])
    assert task["status"] == "done", task["error"]
    name = task["result"]["name"]
    instance = client.get(f"/api/v1/instances/{name}").json()
    assert name == "All the Mods 10 - ATM10" and instance["loader_version"] == "21.1.259"
    game = get_instances_dir() / name / ".minecraft"
    assert (game / "mods" / "atm-core.jar").read_bytes() == MOD
    assert (game / "config" / "atm.toml").read_text(encoding="utf-8") == "quests = true"
    assert (game / "kubejs" / "startup.js").exists()
    assert not (game.parent / "evil.txt").exists() and not (game / "overrides.zip").exists()


def test_bad_checksum_rolls_back(client, ftb, fake_minecraft, wait_task):
    ftb.blobs["/mod.jar"] = b"tampered"
    task = wait_task(client.post("/api/v1/packs/ftb/5/install", json={}).json()["id"], timeout=30)
    assert task["status"] == "failed" and "stone.jar" in task["error"]
    assert not any(get_instances_dir().iterdir())  # недоустановленная сборка удалена


def test_offline_uses_disk_cache(client, ftb):
    from backend.core import ftb_packs
    assert client.get("/api/v1/packs/ftb/search", params={"q": "stone"}).status_code == 200
    ftb_packs._cache.clear()  # «перезапуск»: в памяти пусто, на диске — копия
    ftb.down = True
    rows = client.get("/api/v1/packs/ftb/search", params={"q": "stone"}).json()["results"]
    assert [r["project_id"] for r in rows] == ["ftb:5"]


def test_curseforge_key_stored_encrypted(client):
    from shared.config import AppConfig
    r = client.patch("/api/v1/settings/", json={"curseforge_api_key": "$2a$10$secret-key"})
    assert r.status_code == 200 and r.json()["curseforge_key_set"] is True
    assert "curseforge_api_key" not in r.json() and "curseforge_key_enc" not in r.json()
    raw = AppConfig.load().curseforge_key_enc
    assert raw and "secret-key" not in raw
    from backend.services import curseforge_client
    assert curseforge_client.api_key() == "$2a$10$secret-key"
    assert client.patch("/api/v1/settings/", json={"curseforge_api_key": ""}).json()["curseforge_key_set"] is False


def test_curseforge_fallback_when_ftb_down(client, ftb, monkeypatch):
    """API FTB не отвечает, ключ есть — поиск CurseForge идёт через официальный API."""
    from backend.services import curseforge_client
    ftb.down = True
    monkeypatch.setattr(curseforge_client, "available", lambda: True)
    monkeypatch.setattr(curseforge_client, "search", lambda term, limit: [{"project_id": "curseforge:1", "title": term}])
    rows = client.get("/api/v1/packs/curseforge/search", params={"q": "atm9"}).json()["results"]
    assert rows == [{"project_id": "curseforge:1", "title": "atm9"}]


def test_catalog_pack_helpers():
    from frontend.quick.catalog import filter_packs, split_pack_id
    assert split_pack_id("ftb:135") == ("ftb", "135") and split_pack_id("curseforge:925200") == ("curseforge", "925200")
    assert split_pack_id("AANobbMI") is None and split_pack_id("mod:1") is None
    rows = [{"versions": ["1.21.1"], "loaders": ["neoforge"]}, {"versions": ["1.20.1"], "loaders": ["forge"]}]
    assert filter_packs(rows, "1.21", "") == rows[:1] and filter_packs(rows, "", "forge") == rows[1:]
