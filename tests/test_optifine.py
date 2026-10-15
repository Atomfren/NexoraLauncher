"""OptiFine: список версий с сайта, распознавание файла, установка в Vanilla и Forge."""

import json
import subprocess
import zipfile

import pytest

from backend.core import optifine
from backend.core.instance import Instance
from shared.paths import get_minecraft_dir

PAGE = """
<h2>Minecraft 1.20.1</h2>
<table class='downloadTable mainTable'>
<tr class='downloadLine downloadLineMain'>
    <td class='colFile'>OptiFine HD U I6</td>
    <td class='colDownload'><a href="http://adfoc.us/serve/sitelinks/?id=1&url=http://optifine.net/adloadx?f=OptiFine_1.20.1_HD_U_I6.jar&x=e137">Download</a></td>
    <td class='colMirror'><a href="http://optifine.net/adloadx?f=OptiFine_1.20.1_HD_U_I6.jar">(Mirror)</a></td>
    <td class='colForge'>Forge 47.2.18</td>
    <td class='colDate'>21.12.2023</td>
</tr></table>
<tr class='downloadLine downloadLinePreview'>
    <td class='colFile'>OptiFine HD U I7 pre1</td>
    <td class='colMirror'><a href="http://optifine.net/adloadx?f=preview_OptiFine_1.20.1_HD_U_I7_pre1.jar">(Mirror)</a></td>
    <td class='colForge'>Forge N/A</td>
    <td class='colDate'>01.01.2024</td>
</tr>
<h2>Minecraft 1.12.2</h2>
<tr class='downloadLine downloadLineMain'>
    <td class='colFile'>OptiFine HD U G5</td>
    <td class='colMirror'><a href="http://optifine.net/adloadx?f=OptiFine_1.12.2_HD_U_G5.jar">(Mirror)</a></td>
    <td class='colForge'>Forge 14.23.5.2847</td>
    <td class='colDate'>01.12.2020</td>
</tr>
"""


def make_jar(path, mc="1.20.1", edition="HD_U_I6", patcher=True, wrapper="of"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("optifine/OptiFineTweaker.class", b"x")
        if patcher:
            zf.writestr("optifine/Patcher.class", b"x")
        zf.writestr("notch/net/optifine/Config.class", b"\x00\x01OptiFine_%s_%s\x00" % (mc.encode(), edition.encode()))
        if wrapper == "of":
            zf.writestr("launchwrapper-of.txt", "2.3\n")
            zf.writestr("launchwrapper-of-2.3.jar", b"wrapper")
        elif wrapper == "2.0":
            zf.writestr("launchwrapper-2.0.jar", b"wrapper20")
    return path


@pytest.fixture
def patcher_calls(monkeypatch):
    """Подменяет запуск optifine.Patcher: «патчит», записывая файл библиотеки."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        from pathlib import Path
        Path(cmd[-1]).write_bytes(b"patched-optifine")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(optifine.subprocess, "run", fake_run)
    return calls


def test_parse_downloads_page():
    versions = optifine.parse_downloads_page(PAGE)
    assert [v["filename"] for v in versions] == ["OptiFine_1.20.1_HD_U_I6.jar",
                                                  "preview_OptiFine_1.20.1_HD_U_I7_pre1.jar",
                                                  "OptiFine_1.12.2_HD_U_G5.jar"]
    first = versions[0]
    assert (first["mc_version"], first["edition"], first["forge"], first["preview"]) == \
        ("1.20.1", "HD_U_I6", "47.2.18", False)
    assert first["page_url"] == "https://optifine.net/adloadx?f=OptiFine_1.20.1_HD_U_I6.jar"
    assert versions[1]["preview"] and versions[1]["forge"] == "N/A"


def test_inspect_jar(tmp_path):
    info = optifine.inspect_jar(make_jar(tmp_path / "OptiFine_1.20.1_HD_U_I6.jar"))
    assert (info["mc_version"], info["edition"], info["patcher"]) == ("1.20.1", "HD_U_I6", True)
    # Переименованный файл: версия берётся из класса Config
    renamed = make_jar(tmp_path / "optifine (1).jar", mc="1.12.2", edition="HD_U_G5")
    assert optifine.inspect_jar(renamed)["filename"] == "OptiFine_1.12.2_HD_U_G5.jar"
    not_of = tmp_path / "sodium.jar"
    with zipfile.ZipFile(not_of, "w") as zf:
        zf.writestr("fabric.mod.json", "{}")
    with pytest.raises(Exception, match="не файл OptiFine"):
        optifine.inspect_jar(not_of)


def test_find_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(optifine, "downloads_dirs", lambda: [tmp_path])
    make_jar(tmp_path / "OptiFine_1.20.1_HD_U_I6.jar")
    make_jar(tmp_path / "preview_OptiFine_1.21.4_HD_U_J3_pre2.jar", mc="1.21.4", edition="HD_U_J3_pre2")
    (tmp_path / "other.jar").write_bytes(b"x")
    assert [f["edition"] for f in optifine.find_downloaded("1.20.1")] == ["HD_U_I6"]
    assert len(optifine.find_downloaded()) == 2


def test_install_vanilla(client, wait_task, fake_minecraft, patcher_calls, tmp_path):
    client.post("/api/v1/instances/", json={"name": "OF", "version": "1.20.1", "install": False})
    jar = make_jar(tmp_path / "OptiFine_1.20.1_HD_U_I6.jar")
    task = wait_task(client.post("/api/v1/instances/OF/optifine", json={"path": str(jar)}).json()["id"])
    assert task["status"] == "done", task["error"]

    instance = Instance.load("OF")
    assert instance.optifine == "OptiFine_1.20.1_HD_U_I6.jar"
    assert instance.launch_version_id == "1.20.1-OptiFine_HD_U_I6"
    assert patcher_calls and patcher_calls[0][2:4] == [str(optifine.cache_dir() / jar.name), "optifine.Patcher"]
    libs = get_minecraft_dir() / "libraries" / "optifine"
    assert (libs / "OptiFine" / "1.20.1_HD_U_I6" / "OptiFine-1.20.1_HD_U_I6.jar").read_bytes() == b"patched-optifine"
    assert (libs / "launchwrapper-of" / "2.3" / "launchwrapper-of-2.3.jar").read_bytes() == b"wrapper"
    profile = json.loads((get_minecraft_dir() / "versions" / "1.20.1-OptiFine_HD_U_I6" /
                          "1.20.1-OptiFine_HD_U_I6.json").read_text(encoding="utf-8"))
    assert profile["inheritsFrom"] == profile["jar"] == "1.20.1"
    assert profile["mainClass"] == "net.minecraft.launchwrapper.Launch"
    # У поддельной ванильной версии нет "arguments" — значит, как у старых версий, minecraftArguments
    assert profile["minecraftArguments"].endswith("--tweakClass optifine.OptiFineTweaker")
    assert [lib["name"] for lib in profile["libraries"]] == ["optifine:OptiFine:1.20.1_HD_U_I6",
                                                             "optifine:launchwrapper-of:2.3"]
    data = client.get("/api/v1/instances/OF").json()
    assert data["optifine"] == "OptiFine_1.20.1_HD_U_I6.jar" and data["installed"]
    assert client.get("/api/v1/instances/OF/optifine").json()["edition"] == "HD_U_I6"

    # Подготовка инстанса не перезапускает установщик, если всё на месте
    task = wait_task(client.post("/api/v1/instances/OF/prepare").json()["id"])
    assert task["result"]["launch_version_id"] == "1.20.1-OptiFine_HD_U_I6" and len(patcher_calls) == 1

    # Снятие OptiFine возвращает обычный запуск
    assert client.delete("/api/v1/instances/OF/optifine").status_code == 204
    instance = Instance.load("OF")
    assert instance.optifine == "" and instance.launch_version_id == ""
    task = wait_task(client.post("/api/v1/instances/OF/prepare").json()["id"])
    assert task["result"]["launch_version_id"] == "1.20.1"


def test_install_forge_and_version_change(client, wait_task, fake_minecraft, patcher_calls, tmp_path):
    client.post("/api/v1/instances/", json={"name": "FG", "version": "1.20.1", "mod_loader": "forge",
                                            "install": False})
    old = make_jar(tmp_path / "OptiFine_1.20.1_HD_U_I5.jar", edition="HD_U_I5")
    new = make_jar(tmp_path / "OptiFine_1.20.1_HD_U_I6.jar")
    for jar in (old, new):
        task = wait_task(client.post("/api/v1/instances/FG/optifine", json={"path": str(jar)}).json()["id"])
        assert task["status"] == "done", task["error"]
    instance = Instance.load("FG")
    assert sorted(p.name for p in instance.mods_dir.iterdir()) == ["OptiFine_1.20.1_HD_U_I6.jar"]
    assert not patcher_calls  # на Forge OptiFine — обычный мод

    # Файл удалили из mods вручную — подготовка вернёт его из кэша
    (instance.mods_dir / "OptiFine_1.20.1_HD_U_I6.jar").unlink()
    assert wait_task(client.post("/api/v1/instances/FG/prepare").json()["id"])["status"] == "done"
    assert (instance.mods_dir / "OptiFine_1.20.1_HD_U_I6.jar").exists()

    # Смена версии игры снимает OptiFine
    client.patch("/api/v1/instances/FG", json={"version": "1.20.4"})
    instance = Instance.load("FG")
    assert instance.optifine == "" and not list(instance.mods_dir.glob("*OptiFine*"))


def test_install_rejections(client, wait_task, fake_minecraft, tmp_path):
    client.post("/api/v1/instances/", json={"name": "FB", "version": "1.20.1", "mod_loader": "fabric",
                                            "install": False})
    client.post("/api/v1/instances/", json={"name": "V", "version": "1.21.4", "install": False})
    jar = make_jar(tmp_path / "OptiFine_1.20.1_HD_U_I6.jar")
    task = wait_task(client.post("/api/v1/instances/FB/optifine", json={"path": str(jar)}).json()["id"])
    assert task["status"] == "failed" and "Sodium" in task["error"]
    task = wait_task(client.post("/api/v1/instances/V/optifine", json={"path": str(jar)}).json()["id"])
    assert task["status"] == "failed" and "1.20.1" in task["error"]
    bad = tmp_path / "bad.jar"
    bad.write_bytes(b"not a zip")
    assert client.post("/api/v1/instances/V/optifine", json={"path": str(bad)}).status_code == 400
    assert client.get("/api/v1/instances/FB/optifine").json()["supported"] is False
