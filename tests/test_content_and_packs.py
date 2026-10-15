"""Тесты контента (Modrinth), миров и импорта/экспорта сборок."""

import json
import zipfile

from shared.paths import get_instances_dir


def make_instance(client, name="Pack", loader="fabric"):
    r = client.post("/api/v1/instances/", json={"name": name, "version": "1.20.1", "mod_loader": loader,
                                                "install": False})
    assert r.status_code == 201
    return r.json()


def test_search(client, modrinth):
    modrinth.add_project("sodium", "Sodium", "sodium.jar")
    r = client.get("/api/v1/content/search", params={"project_type": "mod", "query": "sod"})
    assert r.status_code == 200
    assert [p["title"] for p in r.json()["results"]] == ["Sodium"]
    assert client.get("/api/v1/content/search", params={"project_type": "bad"}).status_code == 422


def test_install_mod_with_dependencies(client, modrinth, wait_task):
    make_instance(client)
    modrinth.add_project("fabric-api", "Fabric API", "fabric-api.jar")
    modrinth.add_project("lithium", "Lithium", "lithium.jar", deps=["fabric-api"])
    task = client.post("/api/v1/instances/Pack/content/mod", json={"project_id": "lithium"}).json()
    result = wait_task(task["id"])
    assert result["status"] == "done", result["error"]
    assert {i["project_id"] for i in result["result"]} == {"lithium", "fabric-api"}

    items = client.get("/api/v1/instances/Pack/content/mod").json()
    assert {i["filename"] for i in items} == {"lithium.jar", "fabric-api.jar"}
    assert all(i["enabled"] for i in items)
    mods_dir = get_instances_dir() / "Pack" / ".minecraft" / "mods"
    assert (mods_dir / "lithium.jar").read_bytes() == b"lithium-content"


def test_incompatible_mod_is_refused(client, modrinth, wait_task):
    make_instance(client)
    modrinth.add_project("optifabric", "OptiFabric", "optifabric.jar")
    sodium = modrinth.add_project("sodium", "Sodium", "sodium.jar")
    sodium["dependencies"].append({"project_id": "optifabric", "version_id": None,
                                   "dependency_type": "incompatible"})
    assert wait_task(client.post("/api/v1/instances/Pack/content/mod",
                                 json={"project_id": "sodium"}).json()["id"])["status"] == "done"
    # Sodium установлен раньше — OptiFabric сам по себе не запрещает Sodium, ставится
    assert wait_task(client.post("/api/v1/instances/Pack/content/mod",
                                 json={"project_id": "optifabric"}).json()["id"])["status"] == "done"

    make_instance(client, "Second")
    wait_task(client.post("/api/v1/instances/Second/content/mod", json={"project_id": "optifabric"}).json()["id"])
    result = wait_task(client.post("/api/v1/instances/Second/content/mod", json={"project_id": "sodium"}).json()["id"])
    assert result["status"] == "failed" and "несовместим" in result["error"] and "OptiFabric" in result["error"]
    files = {i["filename"] for i in client.get("/api/v1/instances/Second/content/mod").json()}
    assert files == {"optifabric.jar"}


def test_update_replaces_old_file(client, modrinth, wait_task):
    make_instance(client)
    modrinth.add_project("sodium", "Sodium", "sodium-1.jar")
    wait_task(client.post("/api/v1/instances/Pack/content/mod", json={"project_id": "sodium"}).json()["id"])
    modrinth.add_project("sodium", "Sodium", "sodium-2.jar", version_id="sodium-v2")
    wait_task(client.post("/api/v1/instances/Pack/content/mod", json={"project_id": "sodium"}).json()["id"])
    files = [i["filename"] for i in client.get("/api/v1/instances/Pack/content/mod").json()]
    assert files == ["sodium-2.jar"]


def test_toggle_and_remove(client, modrinth, wait_task):
    make_instance(client)
    modrinth.add_project("sodium", "Sodium", "sodium.jar")
    wait_task(client.post("/api/v1/instances/Pack/content/mod", json={"project_id": "sodium"}).json()["id"])
    r = client.patch("/api/v1/instances/Pack/content/mod/sodium.jar", json={"enabled": False})
    assert r.json() == {"filename": "sodium.jar.disabled", "enabled": False}
    item = client.get("/api/v1/instances/Pack/content/mod").json()[0]
    assert item["enabled"] is False and item["name"] == "Sodium"
    assert client.delete("/api/v1/instances/Pack/content/mod/sodium.jar.disabled").status_code == 204
    assert client.get("/api/v1/instances/Pack/content/mod").json() == []
    assert client.delete("/api/v1/instances/Pack/content/mod/..%2F..%2Finstance.json").status_code in (400, 404)
    assert (get_instances_dir() / "Pack" / "instance.json").exists()


def test_checksum_mismatch_fails(client, modrinth, wait_task):
    make_instance(client)
    modrinth.add_project("evil", "Evil", "evil.jar")
    modrinth.corrupt.add("evil.jar")
    result = wait_task(client.post("/api/v1/instances/Pack/content/mod", json={"project_id": "evil"}).json()["id"])
    assert result["status"] == "failed" and "сумма" in result["error"]
    assert not (get_instances_dir() / "Pack" / ".minecraft" / "mods" / "evil.jar").exists()


def test_mods_need_loader(client, modrinth, wait_task):
    make_instance(client, "Vanilla", loader="vanilla")
    modrinth.add_project("sodium", "Sodium", "sodium.jar")
    result = wait_task(client.post("/api/v1/instances/Vanilla/content/mod",
                                   json={"project_id": "sodium"}).json()["id"])
    assert result["status"] == "failed" and "загрузчик" in result["error"]


def test_incompatible_version(client, modrinth, wait_task):
    make_instance(client)
    modrinth.add_project("forgeonly", "ForgeOnly", "f.jar", loaders=["forge"])
    result = wait_task(client.post("/api/v1/instances/Pack/content/mod",
                                   json={"project_id": "forgeonly"}).json()["id"])
    assert result["status"] == "failed"


def test_resourcepack_install_location(client, modrinth, wait_task):
    make_instance(client, "RP", loader="vanilla")
    modrinth.add_project("faithful", "Faithful", "faithful.zip", loaders=["minecraft"],
                         project_type="resourcepack")
    result = wait_task(client.post("/api/v1/instances/RP/content/resourcepack",
                                   json={"project_id": "faithful"}).json()["id"])
    assert result["status"] == "done", result["error"]
    assert (get_instances_dir() / "RP" / ".minecraft" / "resourcepacks" / "faithful.zip").exists()


def test_worlds_import_export_delete(client, tmp_path):
    make_instance(client, "W", loader="vanilla")
    archive = tmp_path / "MyWorld.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("MyWorld/level.dat", b"nbt")
        zf.writestr("MyWorld/region/r.0.0.mca", b"data")
    r = client.post("/api/v1/instances/W/worlds/import", json={"path": str(archive)})
    assert r.status_code == 200 and r.json()["name"] == "MyWorld"
    # Повторный импорт получает уникальное имя
    assert client.post("/api/v1/instances/W/worlds/import", json={"path": str(archive)}).json()["name"] \
        == "MyWorld (2)"
    worlds = client.get("/api/v1/instances/W/worlds").json()
    assert len(worlds) == 2
    export = tmp_path / "out.zip"
    assert client.post("/api/v1/instances/W/worlds/MyWorld/export", json={"path": str(export)}).status_code == 200
    with zipfile.ZipFile(export) as zf:
        assert "MyWorld/level.dat" in zf.namelist()
    assert client.delete("/api/v1/instances/W/worlds/MyWorld").status_code == 204
    assert client.delete("/api/v1/instances/W/worlds/%2E%2E").status_code in (400, 404)
    assert client.get("/api/v1/instances/W").status_code == 200


def test_export_import_zip_roundtrip(client, tmp_path, wait_task):
    make_instance(client, "Orig", loader="vanilla")
    saves = get_instances_dir() / "Orig" / ".minecraft" / "options.txt"
    saves.write_text("fov:90", encoding="utf-8")
    (get_instances_dir() / "Orig" / "logs").mkdir()
    (get_instances_dir() / "Orig" / "logs" / "old.log").write_text("log", encoding="utf-8")
    export = tmp_path / "orig.zip"
    task = client.post("/api/v1/instances/Orig/export", json={"path": str(export)}).json()
    assert wait_task(task["id"])["status"] == "done"
    with zipfile.ZipFile(export) as zf:
        assert not any(n.startswith("logs/") for n in zf.namelist())

    task = client.post("/api/v1/instances/import", json={"file_path": str(export), "new_name": "Imported"}).json()
    result = wait_task(task["id"])
    assert result["status"] == "done", result["error"]
    imported = client.get("/api/v1/instances/Imported").json()
    assert imported["name"] == "Imported"
    assert (get_instances_dir() / "Imported" / ".minecraft" / "options.txt").read_text(encoding="utf-8") == "fov:90"


def test_import_rejects_foreign_zip(client, tmp_path, wait_task):
    archive = tmp_path / "random.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "hi")
    task = client.post("/api/v1/instances/import", json={"file_path": str(archive)}).json()
    result = wait_task(task["id"])
    assert result["status"] == "failed" and "instance.json" in result["error"]


def test_import_mrpack(client, tmp_path, wait_task, fake_minecraft, monkeypatch):
    import minecraft_launcher_lib as mll
    installed = {}

    def fake_install_mrpack(path, minecraft_directory, modpack_directory=None, callback=None,
                            mrpack_install_options=None):
        installed["dir"] = modpack_directory
        (modpack_directory / "mods").mkdir(parents=True, exist_ok=True)
        (modpack_directory / "mods" / "from-pack.jar").write_bytes(b"x")

    monkeypatch.setattr(mll.mrpack, "install_mrpack", fake_install_mrpack)
    archive = tmp_path / "Cool Pack.mrpack"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps({
            "formatVersion": 1, "game": "minecraft", "name": "Cool: Pack", "versionId": "1",
            "files": [], "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"},
        }))
    task = client.post("/api/v1/instances/import", json={"file_path": str(archive)}).json()
    result = wait_task(task["id"])
    assert result["status"] == "done", result["error"]
    name = result["result"]["name"]
    assert name == "Cool_ Pack"
    instance = client.get(f"/api/v1/instances/{name}").json()
    assert instance["mod_loader"] == "fabric" and instance["loader_version"] == "0.15.0"
    assert instance["launch_version_id"] == "fabric-loader-0.15.0-1.20.1"
    assert instance["installed"] is True
    assert ("fabric", "1.20.1", "0.15.0") in fake_minecraft
