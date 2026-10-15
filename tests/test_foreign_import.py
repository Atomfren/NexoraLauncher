"""Импорт сборок Prism Launcher / MultiMC / CurseForge."""

import json
import shutil
import zipfile

from backend.core import foreign_import
from backend.core.instance import Instance


def _prism_instance(root, name="Fabulous", loader=True, cfg_header=True):
    folder = root / name
    game = folder / ".minecraft"
    (game / "mods").mkdir(parents=True)
    (game / "config").mkdir()
    (game / "logs").mkdir()
    (game / "mods" / "sodium.jar").write_bytes(b"sodium")
    (game / "config" / "sodium.json").write_text("{}", encoding="utf-8")
    (game / "options.txt").write_text("lang:ru_ru", encoding="utf-8")
    (game / "logs" / "latest.log").write_text("old log", encoding="utf-8")
    components = [{"uid": "net.minecraft", "version": "1.20.1"}]
    if loader:
        components.append({"uid": "net.fabricmc.fabric-loader", "version": "0.15.11"})
    (folder / "mmc-pack.json").write_text(json.dumps({"components": components, "formatVersion": 1}),
                                          encoding="utf-8")
    header = "[General]\n" if cfg_header else ""
    (folder / "instance.cfg").write_text(
        f"{header}InstanceType=OneSix\nname=Мой {name}\nOverrideMemory=true\nMaxMemAlloc=6144\n", encoding="utf-8")
    return folder


def _curseforge_instance(root, name="All the Mods"):
    folder = root / name
    (folder / "mods").mkdir(parents=True)
    (folder / "mods" / "jei.jar").write_bytes(b"jei")
    (folder / "minecraftinstance.json").write_text(json.dumps({
        "name": name, "gameVersion": "1.20.1",
        "baseModLoader": {"name": "forge-47.2.0", "forgeVersion": "47.2.0"},
        "isMemoryOverride": False, "allocatedMemory": 8192}), encoding="utf-8")
    return folder


def test_detect(tmp_path):
    prism = foreign_import.detect(_prism_instance(tmp_path))
    assert (prism.version, prism.mod_loader, prism.loader_version) == ("1.20.1", "fabric", "0.15.11")
    assert prism.name == "Мой Fabulous" and prism.max_memory == 6144
    old_mmc = foreign_import.detect(_prism_instance(tmp_path, "Vanilla", loader=False, cfg_header=False))
    assert old_mmc.mod_loader == "vanilla" and old_mmc.name == "Мой Vanilla"
    cf = foreign_import.detect(_curseforge_instance(tmp_path))
    assert (cf.source, cf.mod_loader, cf.loader_version, cf.max_memory) == ("curseforge", "forge", "47.2.0", 0)
    assert foreign_import.detect(tmp_path) is None


def test_import_prism_folder(client, wait_task, fake_minecraft, tmp_path):
    folder = _prism_instance(tmp_path)
    task = wait_task(client.post("/api/v1/instances/import", json={"file_path": str(folder)}).json()["id"])
    assert task["status"] == "done", task["error"]
    instance = Instance.load(task["result"]["name"])
    assert instance.name == "Мой Fabulous" and instance.mod_loader == "fabric" and instance.max_memory == 6144
    assert (instance.mods_dir / "sodium.jar").read_bytes() == b"sodium"
    assert (instance.game_dir / "options.txt").exists() and (instance.game_dir / "config" / "sodium.json").exists()
    assert not (instance.game_dir / "logs").exists()
    assert instance.launch_version_id  # версия и загрузчик установлены
    assert (folder / ".minecraft" / "mods" / "sodium.jar").exists()  # исходная сборка не тронута


def test_import_prism_zip_and_curseforge(client, wait_task, fake_minecraft, tmp_path):
    folder = _prism_instance(tmp_path / "src", "Zipped")
    archive = tmp_path / "Zipped.zip"
    shutil.make_archive(str(archive.with_suffix("")), "zip", folder.parent, folder.name)
    with zipfile.ZipFile(archive) as zf:
        assert "Zipped/mmc-pack.json" in zf.namelist()
    task = wait_task(client.post("/api/v1/instances/import",
                                 json={"file_path": str(archive), "new_name": "FromZip"}).json()["id"])
    assert task["status"] == "done", task["error"]
    assert (Instance.load("FromZip").mods_dir / "sodium.jar").exists()

    cf = _curseforge_instance(tmp_path / "cf")
    task = wait_task(client.post("/api/v1/instances/import", json={"file_path": str(cf)}).json()["id"])
    assert task["status"] == "done", task["error"]
    instance = Instance.load("All the Mods")
    assert instance.mod_loader == "forge" and (instance.mods_dir / "jei.jar").exists()
    assert not (instance.game_dir / "minecraftinstance.json").exists()


def test_import_unknown_folder_fails(client, wait_task, tmp_path):
    task = wait_task(client.post("/api/v1/instances/import", json={"file_path": str(tmp_path)}).json()["id"])
    assert task["status"] == "failed" and "Prism" in task["error"]


def test_discover(client, monkeypatch, tmp_path):
    prism_root = tmp_path / "PrismLauncher" / "instances"
    _prism_instance(prism_root, "One")
    _curseforge_instance(tmp_path / "curseforge")
    (prism_root / "not-an-instance").mkdir()
    monkeypatch.setattr(foreign_import, "_known_roots", lambda: [prism_root, tmp_path / "curseforge",
                                                                  tmp_path / "missing"])
    found = client.get("/api/v1/instances/import/foreign").json()
    assert sorted(f["name"] for f in found) == ["All the Mods", "Мой One"]
    assert {f["source"] for f in found} == {"prism", "curseforge"}
