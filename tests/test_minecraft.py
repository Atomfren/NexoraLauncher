"""Тесты установки версий, сборки команды запуска и процесса игры."""

import sys
import time

import minecraft_launcher_lib as mll
import pytest

from backend.core.errors import BadRequestError
from backend.core.instance import Instance, InstanceManager
from backend.core.minecraft import MinecraftManager
from shared.config import AppConfig

CREDS = {"username": "Tester", "uuid": "00000000-0000-0000-0000-000000000000", "token": "0"}


@pytest.fixture
def captured_options(monkeypatch):
    captured = {}

    def fake_command(version, directory, options):
        captured["version"] = version
        captured["options"] = options
        return ["java", "-jar", "mc.jar"]

    monkeypatch.setattr(mll.command, "get_minecraft_command", fake_command)
    return captured


def test_prepare_vanilla_installs_once(fake_minecraft):
    instance = InstanceManager.create("V", "1.20.1")
    mc = MinecraftManager()
    assert mc.prepare_instance(instance) == "1.20.1"
    assert mc.prepare_instance(instance) == "1.20.1"
    assert fake_minecraft.count(("vanilla", "1.20.1")) == 1
    assert mc.is_version_installed("1.20.1")


def test_prepare_fabric_installs_loader_and_saves_launch_id(fake_minecraft):
    instance = InstanceManager.create("F", "1.20.1", "fabric")
    launch_id = MinecraftManager().prepare_instance(instance)
    assert launch_id == "fabric-loader-9.9.9-1.20.1"
    saved = Instance.load("F")
    assert saved.launch_version_id == launch_id and saved.loader_version == "9.9.9"
    MinecraftManager().prepare_instance(saved)
    assert sum(1 for c in fake_minecraft if c[0] == "fabric") == 1


def test_unsupported_loader_version(fake_minecraft):
    instance = InstanceManager.create("Old", "b1.7.3", "fabric")
    with pytest.raises(BadRequestError):
        MinecraftManager().prepare_instance(instance)


def test_installed_versions_requires_parent(fake_minecraft):
    mc = MinecraftManager()
    mc.install_loader("fabric", "1.20.1")
    ids = {v["id"] for v in mc.get_installed_versions()}
    assert ids == {"1.20.1", "fabric-loader-9.9.9-1.20.1"}


def test_build_command_uses_instance_overrides(captured_options):
    instance = InstanceManager.create("Cmd", "1.20.1")
    instance.max_memory = 8192
    instance.jvm_args = '-XX:+UseG1GC -Dname="a b"'
    instance.width, instance.height = 1920, 1080
    config = AppConfig(max_memory=2048, min_memory=1024)
    command = MinecraftManager().build_command(instance, "1.20.1", CREDS, config, server="mc.example.org",
                                               port=25570)
    options = captured_options["options"]
    assert options["jvmArguments"][:2] == ["-Xmx8192M", "-Xms1024M"]
    assert "-Dname=a b" in options["jvmArguments"]
    assert options["gameDirectory"] == str(instance.game_dir)
    assert (options["resolutionWidth"], options["resolutionHeight"]) == ("1920", "1080")
    assert options["quickPlayMultiplayer"] == "mc.example.org:25570"
    assert "executablePath" not in options  # Java от Mojang по умолчанию
    assert "--fullscreen" not in command


def test_build_command_global_defaults_and_fullscreen(captured_options):
    instance = InstanceManager.create("Glob", "1.20.1")
    instance.fullscreen = True
    command = MinecraftManager().build_command(instance, "1.20.1", CREDS, AppConfig(max_memory=3072))
    assert captured_options["options"]["jvmArguments"][0] == "-Xmx3072M"
    assert command[-1] == "--fullscreen"


def test_fullscreen_synced_to_options_txt():
    """options.txt (его меняет F11) перекрывает --fullscreen, поэтому лаунчер пишет туда свою настройку."""
    instance = InstanceManager.create("Opt", "1.20.1")
    options = instance.game_dir / "options.txt"
    options.parent.mkdir(parents=True, exist_ok=True)
    options.write_text("version:3465\nfullscreen:false\nguiScale:2\n", encoding="utf-8")
    instance.fullscreen = True
    MinecraftManager.sync_game_options(instance, AppConfig())
    assert options.read_text(encoding="utf-8").splitlines() == ["version:3465", "fullscreen:true", "guiScale:2"]
    instance.fullscreen = False
    MinecraftManager.sync_game_options(instance, AppConfig())
    assert "fullscreen:false" in options.read_text(encoding="utf-8")
    fresh = InstanceManager.create("New", "1.20.1")
    MinecraftManager.sync_game_options(fresh, AppConfig(fullscreen=True))
    assert (fresh.game_dir / "options.txt").read_text(encoding="utf-8") == "fullscreen:true\n"


def test_build_command_rejects_missing_java(captured_options):
    instance = InstanceManager.create("J", "1.20.1")
    instance.java_path = "/definitely/not/java"
    with pytest.raises(BadRequestError):
        MinecraftManager().build_command(instance, "1.20.1", CREDS, AppConfig())


def test_launch_flow_runs_process_and_records_stats(client, wait_task, monkeypatch):
    """Полный сценарий запуска с подменённой командой (вместо Java — Python)."""
    client.post("/api/v1/auth/offline/login", json={"username": "Tester"})
    client.post("/api/v1/instances/", json={"name": "Game", "version": "1.20.1", "install": False})
    monkeypatch.setattr(MinecraftManager, "prepare_instance", lambda self, inst, task=None, force=False: "1.20.1")
    script = "import time; print('Setting user: Tester', flush=True); time.sleep(0.5)"
    monkeypatch.setattr(MinecraftManager, "build_command",
                        lambda self, *a, **k: [sys.executable, "-c", script])

    task = client.post("/api/v1/instances/Game/launch").json()
    result = wait_task(task["id"])
    assert result["status"] == "done", result["error"]
    pid = result["result"]["pid"]
    assert client.get("/api/v1/instances/Game").json()["running_pid"] == pid
    # Повторный запуск того же инстанса запрещён
    assert client.post("/api/v1/instances/Game/launch").status_code == 409

    for _ in range(100):
        if client.get(f"/api/v1/minecraft/processes/{pid}").json()["status"] != "running":
            break
        time.sleep(0.05)
    process = client.get(f"/api/v1/minecraft/processes/{pid}").json()
    assert process["status"] == "exited" and process["exit_code"] == 0
    assert "Setting user: Tester" in client.get(f"/api/v1/minecraft/processes/{pid}/log").json()
    file_log = client.get("/api/v1/instances/Game/log").json()
    assert file_log["file"].endswith(".log") and "Setting user: Tester" in file_log["lines"]
    instance = client.get("/api/v1/instances/Game").json()
    assert instance["play_count"] == 1 and instance["last_played"]
    assert client.get("/api/v1/settings/").json()["last_instance"] == "Game"


def test_crash_is_reported(client, wait_task, monkeypatch):
    client.post("/api/v1/auth/offline/login", json={"username": "Tester"})
    client.post("/api/v1/instances/", json={"name": "Crash", "version": "1.20.1", "install": False})
    monkeypatch.setattr(MinecraftManager, "prepare_instance", lambda self, inst, task=None, force=False: "1.20.1")
    monkeypatch.setattr(MinecraftManager, "build_command",
                        lambda self, *a, **k: [sys.executable, "-c", "raise SystemExit(3)"])
    pid = wait_task(client.post("/api/v1/instances/Crash/launch").json()["id"])["result"]["pid"]
    for _ in range(100):
        process = client.get(f"/api/v1/minecraft/processes/{pid}").json()
        if process["status"] != "running":
            break
        time.sleep(0.05)
    assert process["status"] == "crashed" and process["exit_code"] == 3
