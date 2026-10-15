"""Умные логи: разбор форматов, шум, виновники, сводка, проблемы, публикация."""

import json
import os
import time
import zipfile

import httpx

from backend.core import log_analyzer
from backend.core.instance import Instance

FABRIC_LOG = """\
[20:10:01] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.11
[20:10:01] [main/INFO]: Loading 3 mods:
\t- fabricloader 0.15.11
\t- minecraft 1.20.1
\t- sodium 0.5.8
[20:10:02] [main/INFO] (FabricLoader/Mixin) SpongePowered MIXIN Subsystem Version=0.8.5
[20:10:03] [Render thread/WARN]: Missing sound for event: minecraft:item.goat_horn.play
[20:10:03] [Render thread/WARN]: Missing sound for event: minecraft:item.goat_horn.play
[20:10:03] [Render thread/WARN]: Missing sound for event: minecraft:item.goat_horn.play
[20:10:04] [Render thread/INFO]: Backend library: LWJGL version 3.3.1 build 7
[20:10:05] [Render thread/WARN]: Texture pack is weird
[20:10:15] [Render thread/INFO]: Sound engine started
[20:10:20] [Render thread/ERROR]: Failed to render chunk
java.lang.NullPointerException: Cannot invoke "Object.hashCode()" because "key" is null
\tat me.jellysquid.mods.sodium.client.render.chunk.RenderSection.update(RenderSection.java:42)
\tat net.minecraft.client.render.WorldRenderer.render(WorldRenderer.java:100)
\t... 12 more
[20:10:21] [Render thread/INFO]: Stopping!
"""

FORGE_LOG = """\
[13Oct2026 20:10:01.123] [main/INFO] [cpw.mods.modlauncher.Launcher/MODLAUNCHER]: ModLauncher running
[13Oct2026 20:10:02.000] [main/INFO] [net.minecraftforge.fml.loading.FMLLoader/CORE]: Forge mod loading, version 47.2.0, for MC 1.20.1 with MCP 2023
[13Oct2026 20:10:03.000] [main/WARN] [mixin/]: Error loading class: com/x/Y (java.lang.ClassNotFoundException: com/x/Y)
[13Oct2026 20:10:04.000] [main/ERROR] [mixin/]: Mixin apply for mod create failed create.mixins.json:SomeMixin
"""

CRASH_REPORT = """\
---- Minecraft Crash Report ----
// Who set us up the TNT?

Time: 2026-10-13 20:10:21
Description: Rendering overlay

java.lang.RuntimeException: boom
\tat net.minecraft.client.Main.main(Main.java:1)

A detailed walkthrough of the error, its code path and all known details is as follows:
"""


def _make_instance(client, name="Logs", loader="fabric"):
    client.post("/api/v1/instances/", json={"name": name, "version": "1.20.1", "mod_loader": loader,
                                            "install": False})
    return Instance.load(name)


def _fabric_mod(path, mod_id, name):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": mod_id, "name": name,
                                                   "version": "1.0"}))


def test_parse_fabric_log():
    entries = log_analyzer.parse(FABRIC_LOG, {"sodium"})
    first = entries[0]
    assert (first.time, first.thread, first.level) == ("20:10:01", "main", "INFO")
    mods_line = entries[1]
    assert mods_line.message == "Loading 3 mods:" and len(mods_line.extra) == 3
    mixin = entries[2]
    assert mixin.source == "FabricLoader/Mixin"
    sound = next(e for e in entries if "Missing sound" in e.message)
    assert sound.count == 3 and sound.noise and sound.level == "WARN"
    error = next(e for e in entries if e.level == "ERROR")
    assert error.message == "Failed to render chunk" and len(error.extra) == 4
    assert error.mod == "sodium"  # по пакету в стек-трейсе
    assert not next(e for e in entries if "Texture pack" in e.message).noise


def test_parse_forge_log_and_mixin_culprit():
    entries = log_analyzer.parse(FORGE_LOG, {"create"})
    assert entries[0].source == "cpw.mods.modlauncher.Launcher/MODLAUNCHER"
    assert entries[0].time == "13Oct2026 20:10:01.123"
    assert entries[2].noise  # ClassNotFound от mixin при загрузке — частый безвредный шум
    assert entries[3].level == "ERROR" and entries[3].mod == "create"
    summary = log_analyzer.summarize(FORGE_LOG, entries)
    assert (summary["loader"], summary["loader_version"], summary["minecraft"]) == ("forge", "47.2.0", "1.20.1")


def test_summary_fabric():
    entries = log_analyzer.parse(FABRIC_LOG, {"sodium"})
    summary = log_analyzer.summarize(FABRIC_LOG, entries)
    assert summary["minecraft"] == "1.20.1" and summary["loader"] == "fabric"
    assert summary["loader_version"] == "0.15.11" and summary["mods"] == 3
    assert summary["load_seconds"] == 14 and summary["outcome"] == "stopped"
    assert summary["errors"] == 1 and summary["warnings"] == 1 and summary["noise"] == 1
    assert summary["renderer"].startswith("LWJGL") and summary["suspects"] == ["sodium"]
    assert summary["first_error"] == next(e.index for e in entries if e.level == "ERROR")


def test_crash_report_summary():
    entries = log_analyzer.parse(CRASH_REPORT)
    summary = log_analyzer.summarize(CRASH_REPORT, entries, source={"kind": "crash"})
    assert summary["outcome"] == "crashed" and summary["crash_description"] == "Rendering overlay"
    exc = next(e for e in entries if e.message.startswith("java.lang.RuntimeException"))
    assert exc.level == "ERROR" and len(exc.extra) == 1


def test_sources_and_analyze_endpoint(client):
    instance = _make_instance(client)
    instance.logs_dir.mkdir(parents=True, exist_ok=True)
    old = instance.logs_dir / "2026-10-12_10-00-00.log"
    old.write_text("[10:00:00] [main/INFO]: old session\n", encoding="utf-8")
    os.utime(old, (time.time() - 100, time.time() - 100))
    (instance.logs_dir / "2026-10-13_20-10-00.log").write_text(FABRIC_LOG, encoding="utf-8")
    (instance.game_dir / "crash-reports").mkdir(parents=True)
    (instance.game_dir / "crash-reports" / "crash-2026-10-13_20.10.21-client.txt").write_text(CRASH_REPORT,
                                                                                             encoding="utf-8")
    instance.mods_dir.mkdir(parents=True, exist_ok=True)
    _fabric_mod(instance.mods_dir / "sodium.jar", "sodium", "Sodium")

    sources = client.get("/api/v1/instances/Logs/logs").json()
    assert {s["kind"] for s in sources} == {"session", "crash"}
    data = client.get("/api/v1/instances/Logs/logs/analyze").json()
    assert data["source"]["kind"] in ("session", "crash")
    data = client.get("/api/v1/instances/Logs/logs/analyze",
                      params={"source": "session:2026-10-13_20-10-00.log"}).json()
    assert data["summary"]["suspects"] == [{"id": "sodium", "name": "Sodium"}]
    assert data["mod_names"]["sodium"] == "Sodium"
    assert any(e["level"] == "ERROR" for e in data["entries"])
    crash = client.get("/api/v1/instances/Logs/logs/analyze",
                       params={"source": "crash:crash-2026-10-13_20.10.21-client.txt"}).json()
    assert crash["summary"]["outcome"] == "crashed"

    assert client.get("/api/v1/instances/Logs/logs/analyze", params={"source": "session:..%2Fx.log"}).status_code \
        in (400, 404)
    assert client.get("/api/v1/instances/Logs/logs/analyze", params={"source": "evil:x.log"}).status_code == 400


def test_problems_come_from_doctor(client):
    instance = _make_instance(client, "Broken")
    instance.logs_dir.mkdir(parents=True, exist_ok=True)
    (instance.logs_dir / "2026-10-13_20-10-00.log").write_text(
        "[20:10:01] [main/ERROR]: Uncaught exception\njava.lang.OutOfMemoryError: Java heap space\n",
        encoding="utf-8")
    data = client.get("/api/v1/instances/Broken/logs/analyze").json()
    assert any(p["id"] == "memory" and p["fixes"] for p in data["problems"])


def test_redact():
    text = ("Setting user: Steve\n--accessToken eyJhbGciOiJIUzI1NiJ9.abc --version 1.20.1\n"
            "Loading C:\\Users\\Ivan\\AppData\\Roaming\\x and /home/ivan/.minecraft\n"
            "Connecting to 192.168.1.15, 25565\nsession_id=abcdefghijklmnopqrstuvwxyz123\nForge 14.23.5.2847")
    clean = log_analyzer.redact(text)
    assert "eyJhbG" not in clean and "Ivan" not in clean and "/home/ivan" not in clean
    assert "192.168.1.15" not in clean and "abcdefghijklmnop" not in clean
    assert "14.23.5.2847" in clean and "1.20.1" in clean and "Steve" in clean


def test_share(client, monkeypatch):
    instance = _make_instance(client, "Share")
    instance.logs_dir.mkdir(parents=True, exist_ok=True)
    (instance.logs_dir / "2026-10-13_20-10-00.log").write_text(
        "[20:10:01] [main/INFO]: Loading from C:\\Users\\Ivan\\x\n", encoding="utf-8")
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = request.content.decode()
        return httpx.Response(200, json={"success": True, "id": "abc123", "url": "https://mclo.gs/abc123"})

    real_client = httpx.Client
    monkeypatch.setattr(log_analyzer.httpx, "Client",
                        lambda *a, **kw: real_client(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    r = client.post("/api/v1/instances/Share/logs/share", json={})
    assert r.status_code == 200 and r.json()["url"] == "https://mclo.gs/abc123"
    assert "Ivan" not in sent["body"] and "content=" in sent["body"]

    monkeypatch.setattr(log_analyzer.httpx, "Client", lambda *a, **kw: real_client(
        *a, **{**kw, "transport": httpx.MockTransport(lambda r: httpx.Response(
            400, json={"success": False, "error": "too big"}))}))
    r = client.post("/api/v1/instances/Share/logs/share", json={})
    assert r.status_code == 502 and "too big" in r.json()["detail"]


def test_empty_instance_has_no_logs(client):
    _make_instance(client, "Empty")
    data = client.get("/api/v1/instances/Empty/logs/analyze").json()
    assert data["source"] is None and data["entries"] == [] and data["summary"]["lines"] == 0
    assert client.post("/api/v1/instances/Empty/logs/share", json={}).status_code == 400


def test_hints_and_crash_by_oom():
    text = ("[20:12:42] [Render thread/ERROR]: Uncaught exception in render thread\n"
            "java.lang.OutOfMemoryError: Java heap space\n[20:12:42] [Render thread/INFO]: Stopping!\n")
    entries = log_analyzer.parse(text)
    assert "памяти" in entries[0].hint
    assert log_analyzer.summarize(text, entries)["outcome"] == "crashed"
    offline = log_analyzer.parse("[20:10:05] [Render thread/ERROR]: Failed to retrieve profile key pair\n")
    assert offline[0].noise and not offline[0].hint
