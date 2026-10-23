"""Smoke-тест GUI: окно, все страницы и диалоги создаются без исключений (offscreen)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def qt_app(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication(sys.argv)
    # Модальные окна не должны блокировать тест (нет сети и т.п.)
    for name in ("critical", "information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    return app


def _pump(seconds: float) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def test_all_pages_and_dialogs_open(qt_app, monkeypatch):
    errors: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda et, ev, tb: errors.append(ev))

    from frontend.app import MainWindow, _page_factories
    from frontend.backend_runner import EmbeddedBackend
    from frontend.services.api_client import ApiClient
    from frontend.theme import apply_theme

    backend = EmbeddedBackend()
    backend.start()
    api = ApiClient(backend.base_url, backend.token)
    try:
        api.offline_login("Tester")
        api.create_instance("Smoke", "1.20.1", "fabric", install=False)
        apply_theme(qt_app, "light")
        apply_theme(qt_app, "dark")
        window = MainWindow(api)
        window.show()
        for page_id, _, _ in _page_factories():
            window.navigate(page_id)
            _pump(0.2)
        window.navigate("mods", {"instance": "Smoke"})
        _pump(0.3)

        from frontend.dialogs.create_instance_dialog import CreateInstanceDialog
        from frontend.dialogs.instance_dialog import InstanceDialog
        dialog = CreateInstanceDialog(window.ctx, window)
        dialog.show()
        _pump(0.2)
        dialog.close()
        for tab in ("settings", "doctor", "mod", "worlds", "snapshots", "logs"):
            dialog = InstanceDialog(window.ctx, "Smoke", window, initial_tab=tab)
            dialog.show()
            for _ in range(50):
                if dialog.tabs.count():
                    break
                _pump(0.1)
            assert dialog.tabs.count() == 8
            dialog.close()
        window.close()
        # Окно удаляем: иначе его таймеры переживут тест и помешают следующим (модальные окна)
        window.deleteLater()
        _pump(0.2)
    finally:
        api.close()
        backend.stop()
    assert not errors, errors
