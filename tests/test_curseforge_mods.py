"""Отдельные моды из каталога CurseForge: поиск, версии, установка, запрет автора, обновления."""

import hashlib
import json

import httpx
import pytest

from shared.paths import get_instances_dir

CDN = "edge.forgecdn.test"


class FakeCurseForge:
    """Минимальная эмуляция официального API CurseForge (моды, файлы, CDN)."""

    def __init__(self):
        self.mods: dict[int, dict] = {}
        self.files: dict[int, dict] = {}
        self.blobs: dict[str, bytes] = {}
        self.corrupt: set[str] = set()
        self.keys: set[str] = set()

    def add_mod(self, mod_id: int, name: str, filename: str, file_id: int | None = None,
                game_version: str = "1.20.1", loader: str = "fabric", class_id: int = 6,
                deps: list[int] | None = None, incompatible: list[int] | None = None,
                blocked: bool = False, release_type: int = 1, date: str = "2024-01-01T00:00:00Z",
                content: bytes | None = None) -> dict:
        content = content if content is not None else f"{name}-content".encode()
        file_id = file_id or mod_id * 10
        self.blobs[filename] = content
        relations = [{"modId": d, "relationType": 3} for d in deps or []]
        relations += [{"modId": d, "relationType": 5} for d in incompatible or []]
        file = {
            "id": file_id, "modId": mod_id, "displayName": f"{name} {file_id}", "fileName": filename,
            "releaseType": release_type, "fileDate": date, "downloadCount": 7, "fileLength": len(content),
            "downloadUrl": None if blocked else f"https://{CDN}/{filename}",
            "gameVersions": [game_version] + ([loader.capitalize()] if loader else []),
            "hashes": [{"value": hashlib.sha1(content).hexdigest(), "algo": 1}],
            "dependencies": relations,
        }
        self.files[file_id] = file
        mod = self.mods.setdefault(mod_id, {
            "id": mod_id, "name": name, "slug": name.lower().replace(" ", "-"), "classId": class_id,
            "summary": f"{name} summary", "downloadCount": 1500, "thumbsUpCount": 42,
            "authors": [{"name": "tester"}], "categories": [{"name": "Utility"}],
            "logo": {"url": f"https://{CDN}/{name}.png"},
            "links": {"websiteUrl": f"https://www.curseforge.com/minecraft/mc-mods/{mod_id}"},
            "screenshots": [{"url": f"https://{CDN}/shot.png"}], "latestFilesIndexes": [],
        })
        index = {"gameVersion": game_version, "fileId": file_id, "filename": filename,
                 "releaseType": release_type,
                 "modLoader": {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}.get(loader)}
        mod["latestFilesIndexes"] = [index, *mod["latestFilesIndexes"]]
        return file

    # --- Транспорт ------------------------------------------------------------------
    def _files_of(self, mod_id: int, params) -> list[dict]:
        files = [f for f in self.files.values() if f["modId"] == mod_id]
        if params.get("gameVersion"):
            files = [f for f in files if params["gameVersion"] in f["gameVersions"]]
        if params.get("modLoaderType"):
            name = {"1": "Forge", "4": "Fabric", "5": "Quilt", "6": "NeoForge"}[params["modLoaderType"]]
            files = [f for f in files if name in f["gameVersions"]]
        return sorted(files, key=lambda f: f["fileDate"], reverse=True)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == CDN:
            name = request.url.path.rsplit("/", 1)[-1]
            data = self.blobs.get(name)
            if data is None:
                return httpx.Response(404)
            return httpx.Response(200, content=b"broken" if name in self.corrupt else data)
        key = request.headers.get("x-api-key", "")
        self.keys.add(key)
        if not key:
            return httpx.Response(403)
        path, params = request.url.path, request.url.params
        if request.method == "POST":
            body = json.loads(request.content or b"{}")
            if path.endswith("/mods/files"):
                found = [self.files[i] for i in body.get("fileIds", []) if i in self.files]
                return httpx.Response(200, json={"data": found})
            if path.endswith("/mods"):
                found = [self.mods[i] for i in body.get("modIds", []) if i in self.mods]
                return httpx.Response(200, json={"data": found})
            return httpx.Response(404)
        if path.endswith("/mods/search"):
            term = (params.get("searchFilter") or "").lower()
            class_id = int(params.get("classId") or 6)
            rows = [m for m in self.mods.values()
                    if m["classId"] == class_id and term in m["name"].lower()
                    and self._files_of(m["id"], params)]
            return httpx.Response(200, json={"data": rows, "pagination": {"totalCount": len(rows)}})
        parts = path.strip("/").split("/")  # v1/mods/<id>[/files]
        if len(parts) >= 3 and parts[1] == "mods" and parts[2].isdigit():
            mod = self.mods.get(int(parts[2]))
            if not mod:
                return httpx.Response(404)
            if len(parts) == 3:
                return httpx.Response(200, json={"data": mod})
            if parts[3] == "files":
                return httpx.Response(200, json={"data": self._files_of(int(parts[2]), params)})
        return httpx.Response(404)


@pytest.fixture
def curseforge(client):
    """Поддельный CurseForge с сохранённым (зашифрованным) ключом API."""
    from backend.services import curseforge_client as cf
    fake = FakeCurseForge()
    cf.set_transport(httpx.MockTransport(fake.handler))
    assert client.patch("/api/v1/settings/", json={"curseforge_api_key": "test-key"}).status_code == 200
    yield fake
    cf.set_transport(None)


@pytest.fixture
def no_key(client):
    """Транспорт есть, ключа нет: проверяем объяснение вместо пустого списка."""
    from backend.services import curseforge_client as cf
    fake = FakeCurseForge()
    cf.set_transport(httpx.MockTransport(fake.handler))
    yield fake
    cf.set_transport(None)


def make_instance(client, name="Pack", loader="fabric"):
    assert client.post("/api/v1/instances/", json={"name": name, "version": "1.20.1", "mod_loader": loader,
                                                   "install": False}).status_code == 201


def mods_dir(name="Pack"):
    return get_instances_dir() / name / ".minecraft" / "mods"


def install(client, wait_task, project_id, name="Pack", content_type="mod", **body):
    task = client.post(f"/api/v1/instances/{name}/content/{content_type}",
                       json={"project_id": project_id, **body}).json()
    return wait_task(task["id"])


# --- Каталог ---------------------------------------------------------------------------------
def test_search_mods(client, curseforge):
    curseforge.add_mod(238222, "Jade", "jade.jar")
    curseforge.add_mod(306612, "Fabric API", "fabric-api.jar")
    r = client.get("/api/v1/content/search", params={"project_type": "mod", "query": "jad",
                                                     "provider": "curseforge", "game_version": "1.20.1",
                                                     "loader": "fabric"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert [p["title"] for p in results] == ["Jade"]
    row = results[0]
    assert row["project_id"] == "curseforge:238222" and row["provider"] == "curseforge"
    assert row["loaders"] == ["fabric"] and row["game_versions"] == ["1.20.1"]
    assert row["page_url"].endswith("/238222") and row["downloads"] == 1500
    # Ключ прочитан из зашифрованных настроек и ушёл в заголовке
    assert curseforge.keys == {"test-key"}
    # Чужой загрузчик отфильтрован на стороне CurseForge
    assert client.get("/api/v1/content/search", params={"project_type": "mod", "provider": "curseforge",
                                                        "loader": "forge"}).json()["total"] == 0


def test_search_without_key_explains_where_to_get_it(client, no_key, modrinth):
    r = client.get("/api/v1/content/search", params={"project_type": "mod", "provider": "curseforge"})
    assert r.status_code == 400
    assert "console.curseforge.com" in r.json()["detail"]
    # Modrinth без ключа CurseForge работает как раньше
    modrinth.add_project("sodium", "Sodium", "sodium.jar")
    r = client.get("/api/v1/content/search", params={"project_type": "mod", "provider": "modrinth"})
    assert r.status_code == 200 and [p["title"] for p in r.json()["results"]] == ["Sodium"]


def test_project_card_and_versions(client, curseforge):
    curseforge.add_mod(238222, "Jade", "jade-1.jar", file_id=111)
    curseforge.add_mod(238222, "Jade", "jade-2.jar", file_id=222, date="2024-06-01T00:00:00Z",
                       blocked=True, release_type=2)
    card = client.get("/api/v1/content/projects/curseforge:238222").json()
    assert card["title"] == "Jade" and card["provider"] == "curseforge" and card["follows"] == 42
    assert card["gallery"] and card["project_type"] == "mod"

    versions = client.get("/api/v1/content/projects/curseforge:238222/versions").json()
    assert [v["id"] for v in versions] == ["curseforge:222", "curseforge:111"]
    # Запрет автора виден в списке версий, а не только при установке
    assert versions[0]["blocked"] is True and versions[0]["version_type"] == "beta"
    assert versions[0]["game_versions"] == ["1.20.1"] and versions[0]["loaders"] == ["fabric"]
    assert versions[1]["blocked"] is False and versions[1]["files"][0]["filename"] == "jade-1.jar"


def test_unknown_project_is_404(client, curseforge):
    assert client.get("/api/v1/content/projects/curseforge:999").status_code == 404
    assert client.get("/api/v1/content/projects/curseforge:not-a-number").status_code == 400


# --- Установка -------------------------------------------------------------------------------
def test_install_mod_with_dependencies(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(306612, "Fabric API", "fabric-api.jar")
    curseforge.add_mod(238222, "Jade", "jade.jar", deps=[306612])
    result = install(client, wait_task, "curseforge:238222")
    assert result["status"] == "done", result["error"]
    assert {i["project_id"] for i in result["result"]} == {"curseforge:238222", "curseforge:306612"}
    assert (mods_dir() / "jade.jar").read_bytes() == b"Jade-content"
    assert (mods_dir() / "fabric-api.jar").exists()

    items = client.get("/api/v1/instances/Pack/content/mod").json()
    by_name = {i["filename"]: i for i in items}
    assert by_name["jade.jar"]["provider"] == "curseforge"
    assert by_name["jade.jar"]["project_id"] == "curseforge:238222"
    assert by_name["jade.jar"]["version_id"] == "curseforge:2382220"
    assert by_name["jade.jar"]["name"] == "Jade"


def test_blocked_file_sends_to_site(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(238222, "Jade", "jade.jar", blocked=True)
    result = install(client, wait_task, "curseforge:238222")
    assert result["status"] == "failed"
    assert "curseforge.com/minecraft/mc-mods/238222" in result["error"]
    assert "вручную" in result["error"] and not (mods_dir() / "jade.jar").exists()


def test_blocked_dependency_does_not_break_install(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(306612, "Fabric API", "fabric-api.jar", blocked=True)
    curseforge.add_mod(238222, "Jade", "jade.jar", deps=[306612])
    result = install(client, wait_task, "curseforge:238222")
    assert result["status"] == "done", result["error"]
    assert [i["filename"] for i in result["result"]] == ["jade.jar"]


def test_checksum_mismatch_fails(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(1, "Evil", "evil.jar")
    curseforge.corrupt.add("evil.jar")
    result = install(client, wait_task, "curseforge:1")
    assert result["status"] == "failed" and "сумма" in result["error"]
    assert not (mods_dir() / "evil.jar").exists()


def test_no_compatible_file(client, curseforge, wait_task):
    make_instance(client, "Forged", loader="forge")
    curseforge.add_mod(238222, "Jade", "jade.jar", loader="fabric")
    result = install(client, wait_task, "curseforge:238222", name="Forged")
    assert result["status"] == "failed" and "CurseForge" in result["error"]


def test_mods_need_loader(client, curseforge, wait_task):
    make_instance(client, "Vanilla", loader="vanilla")
    curseforge.add_mod(238222, "Jade", "jade.jar")
    result = install(client, wait_task, "curseforge:238222", name="Vanilla")
    assert result["status"] == "failed" and "загрузчик" in result["error"]


def test_incompatible_mod_is_refused(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(1, "OptiFine Alt", "optialt.jar")
    curseforge.add_mod(2, "Sodium CF", "sodium.jar", incompatible=[1])
    assert install(client, wait_task, "curseforge:1")["status"] == "done"
    result = install(client, wait_task, "curseforge:2")
    assert result["status"] == "failed" and "несовместим" in result["error"]
    assert not (mods_dir() / "sodium.jar").exists()


def test_chosen_version_and_replacing_old_file(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(238222, "Jade", "jade-1.jar", file_id=111)
    assert install(client, wait_task, "curseforge:238222", version_id="curseforge:111")["status"] == "done"
    curseforge.add_mod(238222, "Jade", "jade-2.jar", file_id=222, date="2024-06-01T00:00:00Z")
    assert install(client, wait_task, "curseforge:238222")["status"] == "done"
    assert [i["filename"] for i in client.get("/api/v1/instances/Pack/content/mod").json()] == ["jade-2.jar"]
    assert not (mods_dir() / "jade-1.jar").exists()


def test_resourcepack_goes_to_its_folder(client, curseforge, wait_task):
    make_instance(client, "RP", loader="vanilla")
    curseforge.add_mod(400, "Faithful", "faithful.zip", class_id=12, loader="")
    result = install(client, wait_task, "curseforge:400", name="RP", content_type="resourcepack")
    assert result["status"] == "done", result["error"]
    assert (get_instances_dir() / "RP" / ".minecraft" / "resourcepacks" / "faithful.zip").exists()


def test_plugins_are_not_on_curseforge(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(500, "Some Plugin", "plugin.jar")
    result = install(client, wait_task, "curseforge:500", content_type="plugin")
    assert result["status"] == "failed" and "CurseForge" in result["error"]


# --- Обновления ------------------------------------------------------------------------------
def test_updates_alongside_modrinth(client, curseforge, modrinth, wait_task):
    """Моды CurseForge и Modrinth обновляются из одного списка, не мешая друг другу."""
    make_instance(client)
    curseforge.add_mod(238222, "Jade", "jade-1.jar", file_id=111)
    modrinth.add_project("sodium", "Sodium", "sodium-1.jar")
    assert install(client, wait_task, "curseforge:238222")["status"] == "done"
    assert install(client, wait_task, "sodium")["status"] == "done"
    assert client.get("/api/v1/instances/Pack/mods/updates").json() == []

    curseforge.add_mod(238222, "Jade", "jade-2.jar", file_id=222, date="2024-06-01T00:00:00Z")
    modrinth.add_project("sodium", "Sodium", "sodium-2.jar", version_id="sodium-v2",
                         published="2024-06-01T00:00:00Z", content=b"sodium-2")
    found = client.get("/api/v1/instances/Pack/mods/updates").json()
    assert {u["filename"]: u["version_id"] for u in found} == {"jade-1.jar": "curseforge:222",
                                                               "sodium-1.jar": "sodium-v2"}
    assert sorted(u["name"] for u in found) == ["Jade", "Sodium"]

    result = wait_task(client.post("/api/v1/instances/Pack/mods/updates", json={}).json()["id"])
    assert result["status"] == "done", result["error"]
    assert sorted(result["result"]["updated"]) == ["Jade", "Sodium"] and not result["result"]["failed"]
    assert sorted(i["filename"] for i in client.get("/api/v1/instances/Pack/content/mod").json()) \
        == ["jade-2.jar", "sodium-2.jar"]
    assert not (mods_dir() / "jade-1.jar").exists()
    assert client.get("/api/v1/instances/Pack/mods/updates").json() == []


def test_update_keeps_disabled_state(client, curseforge, wait_task):
    make_instance(client)
    curseforge.add_mod(238222, "Jade", "jade-1.jar", file_id=111)
    assert install(client, wait_task, "curseforge:238222")["status"] == "done"
    client.patch("/api/v1/instances/Pack/content/mod/jade-1.jar", json={"enabled": False})
    curseforge.add_mod(238222, "Jade", "jade-2.jar", file_id=222, date="2024-06-01T00:00:00Z")
    found = client.get("/api/v1/instances/Pack/mods/updates").json()
    assert [u["filename"] for u in found] == ["jade-1.jar.disabled"]
    assert found[0]["enabled"] is False
    assert wait_task(client.post("/api/v1/instances/Pack/mods/updates", json={}).json()["id"])["status"] == "done"
    assert (mods_dir() / "jade-2.jar.disabled").exists()
    assert not (mods_dir() / "jade-1.jar.disabled").exists()


def test_updates_survive_missing_key(client, curseforge, modrinth, wait_task):
    """Ключ убрали — моды Modrinth всё равно проверяются."""
    make_instance(client)
    curseforge.add_mod(238222, "Jade", "jade-1.jar", file_id=111)
    modrinth.add_project("sodium", "Sodium", "sodium-1.jar")
    assert install(client, wait_task, "curseforge:238222")["status"] == "done"
    assert install(client, wait_task, "sodium")["status"] == "done"
    curseforge.add_mod(238222, "Jade", "jade-2.jar", file_id=222, date="2024-06-01T00:00:00Z")
    modrinth.add_project("sodium", "Sodium", "sodium-2.jar", version_id="sodium-v2",
                         published="2024-06-01T00:00:00Z", content=b"sodium-2")
    assert client.patch("/api/v1/settings/", json={"curseforge_api_key": ""}).status_code == 200
    found = client.get("/api/v1/instances/Pack/mods/updates").json()
    assert [u["filename"] for u in found] == ["sodium-1.jar"]


# --- Вспомогательное -------------------------------------------------------------------------
def test_identifiers_and_file_choice():
    from backend.core.errors import BadRequestError, NotFoundError
    from backend.services import curseforge_client as cf
    assert cf.is_curseforge("curseforge:238222") and not cf.is_curseforge("sodium")
    assert cf.numeric_id("curseforge:238222") == 238222 and cf.numeric_id(238222) == 238222
    assert cf.tagged_id(7) == "curseforge:7"
    with pytest.raises(BadRequestError):
        cf.numeric_id("curseforge:sodium")

    files = [
        {"id": 1, "fileName": "a.jar", "releaseType": 1, "fileDate": "2024-01-01", "gameVersions": ["1.20.1", "Fabric"]},
        {"id": 2, "fileName": "b.jar", "releaseType": 3, "fileDate": "2024-09-01", "gameVersions": ["1.20.1", "Fabric"]},
        {"id": 3, "fileName": "c.jar", "releaseType": 1, "fileDate": "2024-05-01", "gameVersions": ["1.21", "Fabric"]},
        {"id": 4, "fileName": "d.jar", "releaseType": 1, "fileDate": "2024-07-01", "gameVersions": ["1.20.1", "Forge"]},
    ]
    # Релиз важнее свежести, альфа берётся только если релизов нет
    assert cf.pick_file(files, "1.20.1", ["fabric"])["id"] == 1
    assert cf.pick_file(files, "1.21", ["fabric"])["id"] == 3
    assert cf.pick_file(files, "1.20.1", ["quilt", "fabric"])["id"] == 1
    assert cf.pick_file([files[1]], "1.20.1", ["fabric"])["id"] == 2
    with pytest.raises(NotFoundError):
        cf.pick_file(files, "1.16.5", ["fabric"])
    # Старые моды под Forge не указывают загрузчик — такой файл подходит
    assert cf.pick_file([{"id": 9, "releaseType": 1, "fileDate": "2024-01-01",
                          "gameVersions": ["1.20.1"]}], "1.20.1", ["forge"])["id"] == 9


def test_catalog_sources_and_rows():
    from frontend.quick.catalog import project_row, sources_for, split_pack_id
    assert sources_for("mod") == ("modrinth", "curseforge")
    assert sources_for("shader") == ("modrinth", "curseforge")
    assert sources_for("plugin") == ("modrinth",)
    assert sources_for("modpack") == ("modrinth", "ftb", "curseforge")
    # ID сборки и ID мода выглядят одинаково: различает их только раздел каталога
    assert split_pack_id("curseforge:925200") == ("curseforge", "925200")
    row = project_row({"project_id": "curseforge:238222", "title": "Jade", "downloads": 1500,
                       "provider": "curseforge"})
    assert row["provider"] == "curseforge" and row["downloads"] == "1,5 К"
    assert project_row({"project_id": "AANobbMI", "title": "Sodium"})["provider"] == "modrinth"


def test_installed_row_names_the_source():
    from frontend.quick.build import content_row
    cf_row = content_row({"filename": "jade.jar", "name": "Jade", "enabled": True, "size": 10,
                          "project_id": "curseforge:238222", "provider": "curseforge",
                          "version_number": "Jade 222"})
    assert cf_row["source"] == "CurseForge" and cf_row["version"] == "Jade 222"
    mr_row = content_row({"filename": "sodium.jar", "name": "Sodium", "enabled": True, "size": 10,
                          "project_id": "AANobbMI", "provider": "modrinth", "version_number": "0.5.8"})
    assert mr_row["source"] == "Modrinth"
    local = content_row({"filename": "my-mod.jar", "enabled": True, "size": 10})
    assert local["source"] == "локально"
