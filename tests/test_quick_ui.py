"""Новый интерфейс на QML: форматы, графика, провайдер картинок, модель сборок и smoke-тест окна."""

import os
import sys
import time
from datetime import date, datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtQuick")


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _pump_until(predicate, timeout: float = 10.0) -> bool:
    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


# --- Форматы ------------------------------------------------------------------------------------
def test_plural_and_counts():
    from frontend.quick import fmt
    assert [fmt.plural_form(n) for n in (1, 2, 5, 11, 12, 21, 22, 25, 111, 101)] == \
        ["one", "few", "many", "many", "many", "one", "few", "many", "many", "one"]
    assert fmt.count(48, "q.mods") == "48 модов"
    assert fmt.count(3, "q.worlds") == "3 мира"
    assert fmt.count(1, "q.mods") == "1 мод"


def test_durations_dates_sizes():
    from frontend.quick import fmt
    assert fmt.duration(12 * 3600 + 40 * 60) == "12 ч 40 мин"
    assert fmt.duration(86 * 3600 + 5 * 60) == "86 ч 05 мин"
    assert fmt.duration(59) == "0 мин"
    assert fmt.clock(65) == "01:05" and fmt.clock(3723) == "1:02:03"
    today = date(2026, 10, 13)
    assert fmt.when("2026-10-13T10:05:00", today) == "Сегодня, 10:05"
    assert fmt.when("2026-10-12T22:14:00", today) == "Вчера, 22:14"
    assert fmt.when("2026-10-09T18:40:00", today) == "09.10, 18:40"
    assert fmt.when("2025-10-09T18:40:00", today) == "09.10.2025"
    assert fmt.when(datetime(2026, 10, 13, 9, 0).timestamp(), today) == "Сегодня, 09:00"
    assert fmt.when("") == "—"
    assert fmt.size(412 * 1024 * 1024) == "412 МБ"
    assert fmt.size(int(1.2 * 1024 ** 3)) == "1,2 ГБ"
    assert fmt.memory(4096) == "4 ГБ" and fmt.memory(3584) == "3,5 ГБ"


# --- Графика и провайдер ----------------------------------------------------------------------------
def test_procedural_art_is_deterministic(qt_app):
    from frontend.quick import art
    a, b = art.scene(11, "dusk", 20, 20), art.scene(11, "dusk", 20, 20)
    assert a.size().width() == 20 and a == b
    assert art.scene(12, "dusk", 20, 20) != a
    assert art.mod_icon(5, 140).width() == 8 and art.head(3).height() == 8
    assert art.seed_of("Survival 1.20") == art.seed_of("Survival 1.20")
    assert art.palette_for("x") in art.PALETTE_NAMES


def test_image_refs_and_provider(qt_app, tmp_path):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage

    from frontend.quick.images import NxImageProvider, decode_ref, encode_ref, file_ref

    path = r"D:\New folder (2)\Сборка ~1\100%.png"
    ref = encode_ref(path)
    assert "/" not in ref and "%" not in ref and decode_ref(ref) == path

    shot = tmp_path / "Скриншот 1.png"
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    image.save(str(shot))

    provider = NxImageProvider(fetch=lambda url: b"")
    requested = QSize(48, 48)

    def request(image_id: str):
        """Как зовёт Qt: ``size`` — выходной параметр, картинка — результат."""
        out = QSize()
        return provider.requestImage(image_id, out, requested), out

    for image_id in ("icon/play/ffffff", "loader/fabric", "logo/ffffff/f0b23a", "illus/library/999999",
                     "round/10/0/scene/dusk/11/20/20", "round/6/1/mod/5/140", "round/4/0/head/3",
                     "round/6/0/" + file_ref(str(shot))[len("image://nx/"):]):
        result, result_size = request(image_id)
        assert result_size == requested, image_id
        assert result.size() == requested, image_id
    rounded, _ = request("round/10/0/" + file_ref(str(shot))[len("image://nx/"):])
    assert rounded.pixelColor(0, 0).alpha() == 0          # угол прозрачный
    assert rounded.pixelColor(24, 24).name() == "#336699"  # центр — сама картинка
    broken, _ = request("round/6/0/file/nothing")
    assert broken.width() == 1                              # битая картинка не роняет интерфейс


# --- Модель сборок -------------------------------------------------------------------------------
def test_build_row_states():
    from frontend.quick.library import build_row
    base = {"name": "Survival", "version": "1.20.1", "mod_loader": "fabric", "installed": True,
            "total_play_seconds": 3600, "last_played": "", "game_dir": "", "_screenshot": ""}
    assert build_row(base, None, None)["state"] == "ready"
    assert build_row(dict(base, installed=False), None, None)["state"] == "none"
    running = build_row(dict(base, running_pid=42), {"started_at": 100.0}, None)
    assert running["state"] == "running" and running["pid"] == 42 and running["startedAt"] == 100.0
    busy = build_row(base, None, {"state": "launching", "progress": 42.0, "task": "t"})
    assert busy["state"] == "launching" and busy["progress"] == 42.0
    row = build_row(base, None, None)
    assert row["cover"].startswith("image://nx/scene/") and row["playtime"] == "1 ч 00 мин"


def test_verdict_and_rows(tmp_path):
    from frontend.quick.build import content_row, list_screenshots, verdict_from, world_row
    assert verdict_from({"issues": []})["state"] == "ok"
    verdict = verdict_from({"issues": [
        {"severity": "error", "title": "Не хватило памяти", "details": "2 ГБ",
         "fixes": [{"action": "set_memory", "label": "Выделить 6 ГБ", "params": {"value": 6144}}]},
        {"severity": "warning", "title": "Ещё", "fixes": []}]})
    assert verdict["state"] == "error" and verdict["count"] == 2
    assert verdict["fixAction"] == "set_memory" and verdict["fixParams"] == {"value": 6144}

    row = content_row({"filename": "sodium-fabric-0.5.8.jar.disabled", "name": "Sodium", "enabled": False,
                       "size": 1024, "project_id": "AANobbMI", "icon_url": "https://cdn/x.png"},
                      {"new_version": "0.6.0", "version_id": "v1"})
    assert row["source"] == "Modrinth" and row["newVersion"] == "0.6.0"
    assert row["icon"].startswith("image://nx/remote/") and row["version"] == "0.5.8"
    local = content_row({"filename": "hud.jar", "name": "hud", "enabled": True, "size": 10})
    assert local["source"] == "локально" and local["icon"].startswith("image://nx/mod/")

    world = world_row({"name": "Выживание", "size": 412 * 1024 * 1024, "last_played": "2026-10-12T22:14:00",
                       "has_icon": False, "path": str(tmp_path)})
    assert world["size"] == "412 МБ" and world["icon"].startswith("image://nx/scene/")

    shots = tmp_path / "screenshots"
    shots.mkdir()
    for name in ("a.png", "b.jpg", "notes.txt"):
        (shots / name).write_bytes(b"x")
    assert {s["name"] for s in list_screenshots(str(tmp_path))} == {"a", "b"}
    assert list_screenshots(str(tmp_path / "missing")) == []
    assert list_screenshots("") == []  # не папка screenshots текущего каталога


# --- Окно целиком ------------------------------------------------------------------------------
def test_quick_window_loads_and_plays(qt_app, fake_minecraft, monkeypatch):
    """Окно грузится без ошибок QML; кнопка проходит путь «Установить → Играть → Остановить»."""
    from backend.core.minecraft import MinecraftManager
    from frontend.backend_runner import EmbeddedBackend
    from frontend.quick.app import QuickUi
    from frontend.services.api_client import ApiClient

    script = "import time; print('Setting user: Tester', flush=True); time.sleep(1.5)"
    monkeypatch.setattr(MinecraftManager, "build_command", lambda self, *a, **k: [sys.executable, "-c", script])

    backend = EmbeddedBackend()
    backend.start()
    api = ApiClient(backend.base_url, backend.token)
    ui = None
    try:
        api.offline_login("Tester")
        created = api.create_instance("Smoke", "1.20.1", "vanilla", install=False)
        game_dir = created["game_dir"]
        os.makedirs(os.path.join(game_dir, "saves", "Мир", ""), exist_ok=True)
        open(os.path.join(game_dir, "saves", "Мир", "level.dat"), "wb").close()
        os.makedirs(os.path.join(game_dir, "mods"), exist_ok=True)
        open(os.path.join(game_dir, "mods", "hud-1.0.jar"), "wb").close()
        api.create_instance("Other", "1.20.1", "fabric", install=False)

        ui = QuickUi(api, dark=True)
        warnings: list[str] = []
        ui.engine.warnings.connect(lambda items: warnings.extend(w.toString() for w in items))
        toasts: list[tuple[str, str]] = []
        ui.shell.toastRequested.connect(lambda text, kind: toasts.append((text, kind)))
        assert ui.show()
        lib, build = ui.library, ui.build

        assert _pump_until(lambda: lib.loaded and lib.total == 2)
        lib.select("Smoke")
        assert _pump_until(lambda: len(build.worlds) == 1 and len(build.mods) == 1)
        assert build.mods[0]["name"] == "hud-1.0" and build.worlds[0]["name"] == "Мир"
        assert lib.current["state"] == "none"

        # Мир: экспорт в .zip и импорт обратно (под новым именем)
        import tempfile
        from pathlib import Path

        from PySide6.QtCore import QUrl
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "world-copy"
            build.exportWorld("Мир", QUrl.fromLocalFile(str(archive)).toString())
            assert _pump_until(lambda: archive.with_suffix(".zip").is_file())
            build.importWorld(QUrl.fromLocalFile(str(archive.with_suffix(".zip"))).toString())
            assert _pump_until(lambda: sorted(w["name"] for w in build.worlds) == ["Мир", "Мир (2)"])

        # Боковая панель: контент всегда начинается там, где она заканчивается (без наслоения и полосы)
        from PySide6.QtQuick import QQuickItem
        sidebar = ui.window.findChild(QQuickItem, "sidebar")
        content = ui.window.findChild(QQuickItem, "content")
        for _ in range(2):
            ui.shell.toggleSidebar()
            # Анимация ширины под нагрузкой может идти дольше — ждём конечного состояния
            assert _pump_until(lambda: sidebar.width() == (220 if ui.shell.sidebarWide else 72), 3)
            assert content.x() == sidebar.width()

        # Положение панели: справа — контент слева от неё; сверху/снизу — полоса во всю ширину
        original = ui.shell.sidebarPosition
        try:
            ui.shell.setSidebarPosition("right")
            _pump_until(lambda: False, 0.3)
            assert content.x() == 0 and sidebar.x() == ui.window.width() - sidebar.width()
            for side in ("top", "bottom"):
                ui.shell.setSidebarPosition(side)
                _pump_until(lambda: False, 0.3)
                assert sidebar.width() == ui.window.width() and sidebar.height() == 56 and content.x() == 0
            assert sidebar.y() == ui.window.height() - 56
            ui.shell.setSidebarPosition("diagonal")  # неизвестное значение игнорируется
            assert ui.shell.sidebarPosition == "bottom"
        finally:
            ui.shell.setSidebarPosition(original)
        _pump_until(lambda: False, 0.3)

        lib.setQuery("oth")
        assert lib.model.count == 1
        lib.setQuery("")

        for page in ("library", "wizard", "catalog", "network", "settings"):
            ui.shell.navigate(page)
            _pump_until(lambda: False, 0.2)
        for tab in ("mods", "resources", "worlds", "shots", "doctor", "settings", "overview"):
            ui.shell.navigate("library", tab)
            _pump_until(lambda: False, 0.2)

        lib.install("Smoke")
        assert _pump_until(lambda: lib.current.get("state") == "ready", 15)
        assert ("vanilla", "1.20.1") in fake_minecraft

        # «Сворачивать лаунчер при запуске игры» (по умолчанию включено): свернулось и вернулось после выхода
        from PySide6.QtGui import QWindow
        assert api.settings()["hide_on_launch"] is True
        lib.play("Smoke")
        assert _pump_until(lambda: lib.current.get("state") == "running", 15)
        assert lib.current["startedAt"] > 0
        assert _pump_until(lambda: ui.window.visibility() == QWindow.Visibility.Minimized, 5)
        assert _pump_until(lambda: lib.current.get("state") == "ready", 15)
        assert _pump_until(lambda: ui.window.visibility() != QWindow.Visibility.Minimized, 5)

        assert not [w for w in warnings if "qml" in w.lower()], warnings
        assert not [t for t in toasts if t[1] == "err"], toasts
    finally:
        if ui is not None:
            ui.close()
        api.close()
        backend.stop()


# --- Каталог, сеть, мастер, логи: чистая логика -----------------------------------------------------
def test_catalog_and_network_helpers():
    from frontend.quick.catalog import compact, project_row
    from frontend.quick.network import motd_spans, ping_kind
    assert compact(950) == "950" and compact(12_400) == "12,4 К" and compact(48_200_000) == "48,2 М"
    assert compact(278_000_000) == "278 М"
    row = project_row({"project_id": "AANobbMI", "title": "Sodium", "downloads": 1500, "icon_url": None})
    assert row["downloads"] == "1,5 К" and row["icon"].startswith("image://nx/mod/") and row["state"] == "none"
    spans = motd_spans("§6§lSunrise §r§8| §aSurvival\nсезон")
    assert [s["text"] for s in spans] == ["Sunrise ", "| ", "Survival сезон"]
    assert spans[0] == {"text": "Sunrise ", "color": "6", "bold": True, "italic": False}
    assert spans[1]["color"] == "8" and not spans[1]["bold"]
    assert [ping_kind(v) for v in (None, 38, 126, 212)] == ["off", "ok", "warn", "err"]


def test_wizard_names_and_log_filters():
    from frontend.quick.logs import entry_row, filter_rows, source_label
    from frontend.quick.wizard import name_error
    assert name_error("Survival 1.20", set()) == ""
    assert name_error("  ", set()) == "Введите название"
    assert name_error("Create: Above & Beyond", set()) == "" and name_error("x" * 65, set()) == "Не длиннее 64 символов"
    assert name_error("survival", {"Survival"}) == "Сборка с таким названием уже есть"

    rows = [entry_row(e, {"sodium": "Sodium"}) for e in (
        {"index": 0, "time": "20:10:02", "level": "INFO", "source": "main", "message": "Loading", "mod": ""},
        {"index": 1, "time": "20:10:05", "level": "WARN", "message": "refmap", "noise": True, "count": 3},
        {"index": 2, "time": "20:10:14", "level": "ERROR", "message": "OutOfMemoryError", "mod": "sodium",
         "extra": ["at a", "at b"], "hint": "Не хватило памяти"})]
    assert rows[2]["tag"] == "Sodium" and rows[2]["mod"] and rows[2]["stack"] == ["at a", "at b"]
    lines, hidden = filter_rows(rows, "all", True, "")
    assert [r["index"] for r in lines] == [0, 2] and hidden == 1
    assert [r["index"] for r in filter_rows(rows, "error", False, "")[0]] == [2]
    assert [r["index"] for r in filter_rows(rows, "all", False, "sodium")[0]] == [2]
    assert source_label({"kind": "crash", "modified": "2026-10-13T20:10:14"}) == "Отчёт о сбое · 13.10 20:10"
    assert source_label({"kind": "game", "modified": "2026-10-13T20:10:14", "live": True}) == "latest.log · идёт сейчас"


def test_quick_sections_work_end_to_end(qt_app, fake_minecraft, modrinth):
    """Мастер создаёт сборку, каталог ставит мод, работают сеть, настройки, логи, OptiFine и точки."""
    from frontend.backend_runner import EmbeddedBackend
    from frontend.quick.app import QuickUi
    from frontend.services.api_client import ApiClient

    modrinth.add_project("sodium", "Sodium", "sodium-0.5.8.jar")
    backend = EmbeddedBackend()
    backend.start()
    api = ApiClient(backend.base_url, backend.token)
    ui = None
    try:
        api.offline_login("Tester")
        ui = QuickUi(api, dark=False)
        warnings: list[str] = []
        ui.engine.warnings.connect(lambda items: warnings.extend(w.toString() for w in items))
        errors: list[str] = []
        ui.shell.toastRequested.connect(lambda text, kind: errors.append(text) if kind == "err" else None)
        assert ui.show()
        lib = ui.library
        assert _pump_until(lambda: lib.loaded)

        # Мастер: сборка создаётся и сразу ставится
        assert ui.wizard.nameError("Fab") == ""
        ui.shell.navigate("wizard")
        ui.wizard.create("Fab", "1.20.1", "fabric", "9.9.9")
        assert _pump_until(lambda: lib.current.get("name") == "Fab" and lib.current.get("state") == "ready", 15)
        assert ui.wizard.nameError("fab") != ""

        # Каталог: цель — выбранная сборка, фильтры по её версии и загрузчику
        ui.shell.navigate("catalog")
        assert _pump_until(lambda: any(r["id"] == "sodium" for r in ui.catalog.results))
        assert ui.catalog.target == "Fab" and ui.catalog.gameVersion == "1.20.1" and ui.catalog.loader == "fabric"
        ui.catalog.openProject("sodium")
        assert _pump_until(lambda: ui.catalog.project.get("loadingDetails") is False)
        assert ui.catalog.projectVersions[0]["number"] == "1.0"
        ui.catalog.install("sodium")
        assert _pump_until(lambda: ui.catalog.results[0]["state"] == "installed", 15)
        assert _pump_until(lambda: [m["name"] for m in ui.build.mods] == ["Sodium"])
        ui.catalog.setType("modpack")
        assert ui.catalog.targets == []
        ui.catalog.setType("mod")

        # Сеть: избранный сервер добавляется
        ui.shell.navigate("network")
        ui.network.addServer("Тест", "127.0.0.1:25599")
        assert _pump_until(lambda: len(ui.network.servers) == 1)
        assert ui.network.servers[0]["address"] == "127.0.0.1:25599"
        assert _pump_until(lambda: ui.network.servers[0]["pingKind"] == "off", 15)

        # Настройки
        ui.shell.navigate("settings", "game")
        assert _pump_until(lambda: "max_memory" in ui.settings.values)
        ui.settings.save({"max_memory": 3072})
        assert _pump_until(lambda: api.settings()["max_memory"] == 3072)

        # Логи, OptiFine (на Fabric — альтернатива), точки восстановления
        ui.shell.navigate("library", "doctor")
        ui.logs.ensure()
        assert _pump_until(lambda: not ui.logs.loading)
        ui.optifine.open()
        assert _pump_until(lambda: ui.optifine.state == "idle" and ui.optifine.status.get("supported") is False)
        ui.build.createSnapshot("перед тестом")
        assert _pump_until(lambda: len(ui.build.snapshots) == 1)
        for tab in ("settings", "mods", "overview"):
            ui.shell.navigate("library", tab)
            _pump_until(lambda: False, 0.2)

        # Название с «:» — папка очищается, в интерфейсе остаётся как введено
        ui.wizard.create("Create: Above & Beyond", "1.20.1", "vanilla", "")
        assert _pump_until(lambda: lib.current.get("title") == "Create: Above & Beyond", 15)
        assert lib.current["name"] == "Create_ Above & Beyond"
        assert ui.wizard.nameError("create: above & beyond") != ""
        lib.rename("Create_ Above & Beyond", "Create: A&B")
        # Переименование с двоеточием — это асинхронная смена заголовка с перезагрузкой списка;
        # на загруженном шарде CI ждём столько же, сколько соседние операции выше
        assert _pump_until(lambda: lib.titleOf("Create_ Above & Beyond") == "Create: A&B", 15)

        assert not [w for w in warnings if "qml" in w.lower()], warnings
        assert not errors, errors
    finally:
        if ui is not None:
            ui.close()
        api.close()
        backend.stop()
