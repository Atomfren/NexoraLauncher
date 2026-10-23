"""Выбор видеокарты для игры: распознавание, запись выбора, применение при запуске."""

import os

import pytest

from backend.core import gpu


def test_discrete_cards_are_recognised():
    for name in ("NVIDIA GeForce RTX 4060 Laptop GPU", "NVIDIA GeForce GTX 1650",
                 "AMD Radeon RX 6600M", "Intel(R) Arc(TM) A770 Graphics", "NVIDIA Quadro P2000"):
        assert gpu.classify(name) is True, name


def test_integrated_cards_are_recognised():
    for name in ("Intel(R) UHD Graphics 630", "Intel(R) Iris(R) Xe Graphics",
                 "AMD Radeon(TM) Graphics", "AMD Radeon(TM) Vega 8 Graphics",
                 "Microsoft Basic Display Adapter", "VMware SVGA 3D"):
        assert gpu.classify(name) is False, name


def test_unknown_card_is_not_called_discrete():
    """Незнакомое название не должно уводить игру на несуществующую видеокарту."""
    assert gpu.classify("Super Graphics 9000") is False


@pytest.fixture
def written(monkeypatch):
    """Перехватывает запись в реестр: тесты не трогают настоящие настройки Windows."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(gpu, "is_supported", lambda: True)
    monkeypatch.setattr(gpu, "_write_preference", lambda path, value: calls.append((path, value)) or True)
    monkeypatch.setattr(gpu, "_clear_preference", lambda path: calls.append((path, "clear")))
    return calls


JAVA = r"C:\Program Files\Java\bin\javaw.exe"
DISCRETE = [gpu.Adapter("Intel UHD Graphics", False), gpu.Adapter("NVIDIA GeForce RTX 4060", True)]
ONLY_INTEGRATED = [gpu.Adapter("Intel UHD Graphics", False)]


def test_auto_prefers_discrete_when_present(written):
    assert gpu.apply_preference(JAVA, gpu.AUTO, DISCRETE) == gpu.HIGH_PERFORMANCE
    assert written == [(JAVA, "2")]


def test_auto_does_nothing_without_discrete(written):
    """На одной видеокарте выбирать нечего — запись не делается."""
    assert gpu.apply_preference(JAVA, gpu.AUTO, ONLY_INTEGRATED) == ""
    assert written == []


def test_explicit_choices(written):
    assert gpu.apply_preference(JAVA, gpu.DISCRETE, ONLY_INTEGRATED) == gpu.HIGH_PERFORMANCE
    assert gpu.apply_preference(JAVA, gpu.INTEGRATED, DISCRETE) == gpu.POWER_SAVING
    assert written == [(JAVA, "2"), (JAVA, "1")]


def test_system_choice_removes_our_record(written):
    """«Как в системе» убирает запись лаунчера, а не ставит свою."""
    assert gpu.apply_preference(JAVA, gpu.SYSTEM, DISCRETE) == ""
    assert written == [(JAVA, "clear")]


def test_unknown_choice_falls_back_to_auto(written):
    assert gpu.apply_preference(JAVA, "чепуха", DISCRETE) == gpu.HIGH_PERFORMANCE


def test_nothing_happens_on_unsupported_system(monkeypatch):
    monkeypatch.setattr(gpu, "is_supported", lambda: False)
    monkeypatch.setattr(gpu, "_write_preference", lambda *a: pytest.fail("писать нельзя"))
    assert gpu.apply_preference(JAVA, gpu.DISCRETE, DISCRETE) == ""


def test_empty_path_is_ignored(written):
    assert gpu.apply_preference("", gpu.DISCRETE, DISCRETE) == ""
    assert written == []


@pytest.mark.skipif(os.name != "nt", reason="реестр есть только в Windows")
def test_real_registry_round_trip(monkeypatch):
    """Настоящая запись и чтение — в отдельной ветке реестра, которая удаляется после теста."""
    import winreg

    key_path = r"Software\NexoraLauncher\test-gpu"
    monkeypatch.setattr(gpu, "PREFERENCE_KEY", key_path)
    exe = r"C:\test\javaw.exe"
    try:
        assert gpu.apply_preference(exe, gpu.DISCRETE, DISCRETE) == gpu.HIGH_PERFORMANCE
        assert gpu.read_preference(exe) == "2"
        assert gpu.apply_preference(exe, gpu.INTEGRATED, DISCRETE) == gpu.POWER_SAVING
        assert gpu.read_preference(exe) == "1"
        gpu.apply_preference(exe, gpu.SYSTEM, DISCRETE)
        assert gpu.read_preference(exe) == ""
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            pass


def test_state_for_interface(monkeypatch):
    monkeypatch.setattr(gpu, "is_supported", lambda: True)
    monkeypatch.setattr(gpu, "list_adapters", lambda: DISCRETE)
    data = gpu.state(gpu.AUTO).to_dict()
    assert data["supported"] and data["preference"] == "auto"
    assert data["discrete_name"] == "NVIDIA GeForce RTX 4060"
    assert [a["name"] for a in data["adapters"]] == ["Intel UHD Graphics", "NVIDIA GeForce RTX 4060"]


def test_settings_endpoint(client, monkeypatch):
    monkeypatch.setattr(gpu, "is_supported", lambda: True)
    monkeypatch.setattr(gpu, "list_adapters", lambda: DISCRETE)
    assert client.get("/api/v1/settings").json()["gpu_preference"] == "auto"
    assert client.patch("/api/v1/settings", json={"gpu_preference": "integrated"}).json()["gpu_preference"] \
        == "integrated"
    assert client.patch("/api/v1/settings", json={"gpu_preference": "чепуха"}).status_code == 422

    info = client.get("/api/v1/settings/gpu").json()
    assert info["supported"] and info["discrete_name"] == "NVIDIA GeForce RTX 4060"
    assert info["preference"] == "integrated"


def test_launch_applies_preference(client, wait_task, fake_minecraft, monkeypatch):
    """При запуске игры выбор видеокарты делается для того java.exe, который стартует."""
    import sys

    from backend.core.minecraft import MinecraftManager

    applied: list[tuple[str, str]] = []
    monkeypatch.setattr(gpu, "apply_preference",
                        lambda path, preference, adapters=None: applied.append((path, preference)))
    # Вместо Java запускаем короткий процесс: важен не он, а то, для какого файла сделан выбор
    monkeypatch.setattr(MinecraftManager, "build_command",
                        lambda self, *a, **k: [sys.executable, "-c", "import time; time.sleep(0.3)"])

    client.post("/api/v1/auth/offline/login", json={"username": "Tester"})
    client.post("/api/v1/instances/", json={"name": "Gpu", "version": "1.20.1",
                                            "mod_loader": "vanilla", "install": False})
    client.patch("/api/v1/settings", json={"gpu_preference": "discrete"})
    task = wait_task(client.post("/api/v1/instances/Gpu/launch", json={}).json()["id"])
    assert task["status"] == "done", task["error"]
    assert applied == [(sys.executable, "discrete")]
