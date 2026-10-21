"""Доктор, снимки, умные обновления, «Турбо», экспорт .mrpack."""

import io
import json
import zipfile
from pathlib import Path

from backend.core.mod_metadata import read_mod, scan_mods
from shared.paths import get_instances_dir


# --- Хелперы: поддельные jar ----------------------------------------------------------------
def fabric_jar(mod_id: str, name: str = "", version: str = "1.0", depends: dict | None = None,
               nested: list[str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        meta = {"schemaVersion": 1, "id": mod_id, "name": name or mod_id, "version": version,
                "depends": depends or {"fabricloader": "*", "minecraft": "1.20.1"}}
        if nested:
            meta["jars"] = [{"file": f"META-INF/jars/{n}.jar"} for n in nested]
            for n in nested:
                zf.writestr(f"META-INF/jars/{n}.jar", fabric_jar(n))
        zf.writestr("fabric.mod.json", json.dumps(meta))
    return buffer.getvalue()


def forge_jar(mod_id: str, name: str = "", neo: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        toml = (f'modLoader="javafml"\nloaderVersion="[47,)"\n[[mods]]\nmodId="{mod_id}"\n'
                f'version="${{file.jarVersion}}"\ndisplayName="{name or mod_id}"\n'
                f'[[dependencies.{mod_id}]]\nmodId="cloth_config"\nmandatory=true\nversionRange="[11,)"\n')
        zf.writestr("META-INF/neoforge.mods.toml" if neo else "META-INF/mods.toml", toml)
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nImplementation-Version: 2.5.1\n")
    return buffer.getvalue()


def make_instance(client, name="Pack", loader="fabric"):
    assert client.post("/api/v1/instances/", json={"name": name, "version": "1.20.1", "mod_loader": loader,
                                                   "install": False}).status_code == 201
    mods = get_instances_dir() / name / ".minecraft" / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    return mods


def write_log(name: str, text: str) -> None:
    logs = get_instances_dir() / name / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "2026-01-01_00-00-00.log").write_text(text, encoding="utf-8")


# --- Метаданные модов ---------------------------------------------------------------------
def test_read_fabric_with_nested(tmp_path):
    path = tmp_path / "a.jar"
    path.write_bytes(fabric_jar("cool", "Cool Mod", nested=["mixinextras"]))
    info = read_mod(path)
    assert info.ids == ["cool"] and info.name == "Cool Mod" and info.loader == "fabric"
    assert info.bundled == ["mixinextras"] and len(info.sha1) == 40


def test_read_forge_and_broken(tmp_path):
    forge = tmp_path / "f.jar"
    forge.write_bytes(forge_jar("jei", "Just Enough Items"))
    info = read_mod(forge)
    assert info.loader == "forge" and info.ids == ["jei"] and info.version == "2.5.1"
    assert info.depends == ["cloth_config"]
    neo = tmp_path / "n.jar"
    neo.write_bytes(forge_jar("neomod", neo=True))
    assert read_mod(neo).loader == "neoforge"
    broken = tmp_path / "b.jar"
    broken.write_bytes(b"not a zip")
    assert read_mod(broken).broken is True


def test_scan_uses_cache_and_sees_disabled(tmp_path):
    mods = tmp_path / "i" / ".minecraft" / "mods"
    mods.mkdir(parents=True)
    (mods / "x.jar.disabled").write_bytes(fabric_jar("x"))
    (mods / "notes.txt").write_text("skip")
    first = scan_mods(mods)
    assert [(m.filename, m.enabled) for m in first] == [("x.jar.disabled", False)]
    assert (tmp_path / "i" / ".nexora_modindex.json").exists()
    assert scan_mods(mods)[0].ids == ["x"]


# --- Доктор ---------------------------------------------------------------------------------
FABRIC_CRASH = """
[main/ERROR]: Incompatible mods found!
net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!
A potential solution has been determined, this may resolve your problem:
	 - Install fabric-api, any version.
More details:
	 - Mod 'Lithium' (lithium) 0.11.2 requires any version of fabric-api, which is missing!
	 - Mod 'Sodium' (sodium) 0.5.3 is incompatible with any version of mod 'OptiFabric' (optifabric), but a matching version is present: 1.13.0!
	 - Mod 'Old Thing' (oldthing) 1.0 requires version 1.19.2 of minecraft, but only the wrong version is present: 1.20.1!
"""


def test_doctor_fabric_log(client):
    mods = make_instance(client)
    (mods / "lithium.jar").write_bytes(fabric_jar("lithium", "Lithium"))
    (mods / "sodium.jar").write_bytes(fabric_jar("sodium", "Sodium"))
    (mods / "optifabric.jar").write_bytes(fabric_jar("optifabric", "OptiFabric"))
    (mods / "old.jar").write_bytes(fabric_jar("oldthing", "Old Thing"))
    write_log("Pack", FABRIC_CRASH)
    report = client.get("/api/v1/instances/Pack/doctor").json()
    issues = {i["id"]: i for i in report["issues"]}
    missing = issues["missing:fabric-api"]
    assert missing["severity"] == "error" and "Lithium" in missing["details"]
    assert missing["fixes"][0] == {"action": "install_mod", "label": "Установить «fabric-api» с Modrinth",
                                   "params": {"mod_id": "fabric-api"}}
    incompatible = issues["incompatible:sodium:optifabric"]
    assert {f["params"]["filename"] for f in incompatible["fixes"]} == {"sodium.jar", "optifabric.jar"}
    assert issues["game_version:oldthing"]["fixes"][0]["params"] == {"filename": "old.jar"}


def test_doctor_forge_oom_java(client):
    from shared.config import AppConfig
    mods = make_instance(client, "Forge", "forge")
    (mods / "jei.jar").write_bytes(forge_jar("jei", "JEI"))
    AppConfig.load().update(java_path="C:/java8/bin/java.exe", max_memory=2048)
    write_log("Forge", """
Missing or unsupported mandatory dependencies:
	Mod ID: 'cloth_config', Requested by: 'jei', Expected range: '[11,)', Actual version: '[MISSING]'
java.lang.OutOfMemoryError: Java heap space
java.lang.UnsupportedClassVersionError: x has been compiled by a more recent version of the Java Runtime (class file version 65.0), this version of the Java Runtime only recognizes class file versions up to 52.0
""")
    issues = {i["id"]: i for i in client.get("/api/v1/instances/Forge/doctor").json()["issues"]}
    assert issues["missing:cloth_config"]["fixes"][0]["action"] == "install_mod"
    assert issues["memory"]["fixes"][0]["action"] == "set_memory"
    assert issues["memory"]["fixes"][0]["params"]["max_memory"] > 2048
    java = issues["java_version"]
    assert "Java 21" in java["title"] and java["fixes"][0]["action"] == "reset_java"


def test_doctor_static_checks(client):
    mods = make_instance(client)
    (mods / "a-1.0.jar").write_bytes(fabric_jar("dup", "Dup", version="1.0"))
    (mods / "a-1.1.jar").write_bytes(fabric_jar("dup", "Dup", version="1.1"))
    (mods / "forgemod.jar").write_bytes(forge_jar("forgemod", "Forge Only"))
    (mods / "broken.jar").write_bytes(b"garbage")
    (mods / "needs.jar").write_bytes(fabric_jar("needs", "Needs", depends={"cloth-config": "*", "mixinextras": "*",
                                                                          "fabric-api-base": "*"}))
    (mods / "lib.jar").write_bytes(fabric_jar("libholder", nested=["mixinextras"]))
    (mods / "fapi.jar").write_bytes(fabric_jar("fabric-api"))
    issues = {i["id"]: i for i in client.get("/api/v1/instances/Pack/doctor").json()["issues"]}
    assert len(issues["duplicate:dup"]["fixes"]) == 2
    assert "wrong_loader:forgemod.jar" in issues
    assert "broken:broken.jar" in issues
    assert "missing:cloth-config" in issues
    # Вложенные jar и модули Fabric API не считаются недостающими
    assert "missing:mixinextras" not in issues and "missing:fabric-api-base" not in issues


def test_doctor_fixes(client, wait_task, modrinth):
    mods = make_instance(client)
    (mods / "bad.jar").write_bytes(fabric_jar("bad"))
    modrinth.add_project("fabric-api", "Fabric API", "fabric-api.jar")

    def fix(action, params):
        task = client.post("/api/v1/instances/Pack/doctor/fix", json={"action": action, "params": params}).json()
        return wait_task(task["id"])

    result = fix("disable_mod", {"filename": "bad.jar"})
    assert result["status"] == "done" and (mods / "bad.jar.disabled").exists()
    result = fix("install_mod", {"mod_id": "fabric_api"})  # алиас mod id → slug
    assert result["status"] == "done", result["error"]
    assert (mods / "fabric-api.jar").exists()
    assert fix("set_memory", {"max_memory": 6144})["status"] == "done"
    assert client.get("/api/v1/instances/Pack").json()["max_memory"] == 6144
    assert fix("install_mod", {"mod_id": "nonexistent_mod_xyz"})["status"] == "failed"
    # Перед исправлениями делается автоснимок
    assert any(s["auto"] for s in client.get("/api/v1/instances/Pack/snapshots").json())
    assert client.post("/api/v1/instances/Pack/doctor/fix", json={"action": "rm_rf"}).status_code == 422


# --- Снимки -----------------------------------------------------------------------------------
def test_snapshot_restore(client):
    mods = make_instance(client)
    (mods / "keep.jar").write_bytes(b"v1")
    config = mods.parent / "config"
    config.mkdir()
    (config / "a.toml").write_text("x=1")
    snap = client.post("/api/v1/instances/Pack/snapshots", json={"label": "Рабочая сборка"}).json()
    assert snap["mods"] == 1 and snap["label"] == "Рабочая сборка"

    (mods / "keep.jar").write_bytes(b"v2")
    (mods / "new.jar").write_bytes(b"new")
    (config / "a.toml").write_text("x=2")
    instance_file = get_instances_dir() / "Pack" / "instance.json"
    data = json.loads(instance_file.read_text(encoding="utf-8"))
    data["play_count"] = 7
    instance_file.write_text(json.dumps(data), encoding="utf-8")
    client.patch("/api/v1/instances/Pack", json={"max_memory": 8192})

    assert client.post(f"/api/v1/instances/Pack/snapshots/{snap['id']}/restore").status_code == 200
    assert (mods / "keep.jar").read_bytes() == b"v1" and not (mods / "new.jar").exists()
    assert (config / "a.toml").read_text() == "x=1"
    instance = client.get("/api/v1/instances/Pack").json()
    assert instance["max_memory"] == 0 and instance["play_count"] == 7  # настройки откатились, статистика — нет
    snaps = client.get("/api/v1/instances/Pack/snapshots").json()
    assert snaps[0]["auto"] and "Перед откатом" in snaps[0]["label"]
    assert client.delete(f"/api/v1/instances/Pack/snapshots/{snap['id']}").status_code == 204
    assert client.post("/api/v1/instances/Pack/snapshots/nope/restore").status_code == 404


def test_auto_snapshots_pruned_and_version_change(client):
    make_instance(client)
    from backend.core import snapshots
    for i in range(12):
        snapshots.create("Pack", f"auto {i}", auto=True)
    client.post("/api/v1/instances/Pack/snapshots", json={"label": "manual"})
    snaps = client.get("/api/v1/instances/Pack/snapshots").json()
    assert sum(s["auto"] for s in snaps) == 10 and any(s["label"] == "manual" for s in snaps)
    client.patch("/api/v1/instances/Pack", json={"version": "1.20.4"})
    assert "сменой версии" in client.get("/api/v1/instances/Pack/snapshots").json()[0]["label"]


# --- Обновления и «Турбо» -----------------------------------------------------------------
def test_identify_and_update_mods(client, modrinth, wait_task):
    mods = make_instance(client)
    old = fabric_jar("sodium", "Sodium", "0.4")
    modrinth.add_project("sodium", "Sodium", "sodium-0.4.jar", content=old, version_id="s-old",
                         published="2023-01-01T00:00:00Z")
    new = modrinth.add_project("sodium", "Sodium", "sodium-0.5.jar", content=fabric_jar("sodium", "Sodium", "0.5"),
                               version_id="s-new", published="2024-06-01T00:00:00Z")
    (mods / "manually-added.jar").write_bytes(old)
    (mods / "unknown.jar").write_bytes(fabric_jar("unknown"))

    assert client.post("/api/v1/instances/Pack/mods/identify").json() == {"total": 2, "identified": 1}
    listed = {i["filename"]: i for i in client.get("/api/v1/instances/Pack/content/mod").json()}
    assert listed["manually-added.jar"]["name"] == "Sodium"

    found = client.get("/api/v1/instances/Pack/mods/updates").json()
    assert [(u["name"], u["current_version"], u["version_id"]) for u in found] == [("Sodium", "1.0", "s-new")]
    result = wait_task(client.post("/api/v1/instances/Pack/mods/updates", json={}).json()["id"])
    assert result["status"] == "done" and result["result"]["updated"] == ["Sodium"]
    assert (mods / new["files"][0]["filename"]).exists() and not (mods / "manually-added.jar").exists()
    assert client.get("/api/v1/instances/Pack/mods/updates").json() == []
    assert any("обновлением" in s["label"] for s in client.get("/api/v1/instances/Pack/snapshots").json())


def test_turbo(client, modrinth, wait_task):
    mods = make_instance(client)
    (mods / "sodium.jar").write_bytes(fabric_jar("sodium"))
    for slug in ("lithium", "ferrite-core", "entityculling", "immediatelyfast", "modernfix", "krypton"):
        modrinth.add_project(slug, slug.title(), f"{slug}.jar")
    plan = client.get("/api/v1/instances/Pack/turbo").json()
    assert "sodium" not in plan["mods"] and "embeddium" not in plan["mods"] and "lithium" in plan["mods"]
    result = wait_task(client.post("/api/v1/instances/Pack/turbo", json={"tune_jvm": True}).json()["id"])
    assert result["status"] == "done", result["error"]
    assert (mods / "lithium.jar").exists()
    instance = client.get("/api/v1/instances/Pack").json()
    assert instance["max_memory"] >= 2048 and "UseG1GC" in instance["jvm_args"]
    make_instance(client, "Vanilla", "vanilla")
    assert client.get("/api/v1/instances/Vanilla/turbo").status_code == 400


def test_export_mrpack(client, modrinth, wait_task, tmp_path):
    mods = make_instance(client)
    content = fabric_jar("sodium", "Sodium")
    modrinth.add_project("sodium", "Sodium", "sodium.jar", content=content)
    (mods / "sodium.jar").write_bytes(content)
    (mods / "private.jar").write_bytes(fabric_jar("private"))
    (mods / "off.jar.disabled").write_bytes(fabric_jar("off"))
    (mods.parent / "options.txt").write_text("fov:90")
    dest = tmp_path / "pack.mrpack"
    result = wait_task(client.post("/api/v1/instances/Pack/export_mrpack", json={"path": str(dest)}).json()["id"])
    assert result["status"] == "done", result["error"]
    assert result["result"]["linked"] == 1
    with zipfile.ZipFile(dest) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
        names = zf.namelist()
    assert index["dependencies"]["minecraft"] == "1.20.1"
    assert [f["path"] for f in index["files"]] == ["mods/sodium.jar"]
    assert index["files"][0]["downloads"][0].startswith("https://")
    assert "overrides/mods/private.jar" in names and "overrides/options.txt" in names
    assert not any("off.jar" in n for n in names)
    assert Path(dest).stat().st_size > 0


def test_turbo_retries_network_errors(client, modrinth, wait_task, monkeypatch):
    """Сбой сети не теряет мод молча: повтор, а если не вышло — мод в списке failed."""
    from backend.core import updates
    from backend.core.content import ContentManager
    from backend.core.errors import ExternalServiceError
    monkeypatch.setattr(updates.time, "sleep", lambda s: None)
    monkeypatch.setattr(updates, "TURBO_MODS", [("lithium", ("fabric",)), ("krypton", ("fabric",))])
    make_instance(client)
    for slug in ("lithium", "krypton"):
        modrinth.add_project(slug, slug.title(), f"{slug}.jar")
    real_install, calls = ContentManager.install, {"lithium": 0}

    def flaky(name, kind, project_id, **kw):
        if project_id == "lithium":
            calls["lithium"] += 1
            if calls["lithium"] == 1:
                raise ExternalServiceError("timeout")  # первый раз сеть падает, второй — проходит
        if project_id == "krypton":
            raise ExternalServiceError("timeout")  # не скачивается совсем
        return real_install(name, kind, project_id, **kw)

    monkeypatch.setattr(ContentManager, "install", staticmethod(flaky))
    task = wait_task(client.post("/api/v1/instances/Pack/turbo", json={"tune_jvm": False}).json()["id"])
    assert task["status"] == "done", task["error"]
    assert task["result"]["installed"] == ["Lithium"] and task["result"]["failed"] == ["krypton"]
    assert calls["lithium"] == 2
