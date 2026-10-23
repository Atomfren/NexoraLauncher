"""Предложение обновиться: тихая проверка, повтор после сбоя сети, один показ на версию."""

import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtQuick")


@pytest.fixture
def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _pump_until(predicate, timeout: float = 5.0) -> bool:
    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class FakeApi:
    """Backend, который сначала «без сети», а потом отвечает."""

    def __init__(self, check_updates: bool = True, available: bool = True):
        self.checks = 0
        self.offline_until = 0
        self._check_updates = check_updates
        self._available = available

    def settings(self) -> dict:
        return {"check_updates": self._check_updates}

    def system_info(self) -> dict:
        return {"total_memory_mb": 8192}

    def languages(self, online: bool = True) -> dict:
        return {"builtin": [{"code": "ru", "name": "Русский"}], "installed": [], "available": [], "error": ""}

    def check_update(self) -> dict:
        self.checks += 1
        if self.checks <= self.offline_until:
            raise RuntimeError("нет связи с backend")
        return {"current": "1.5.0", "latest": "9.9.9", "available": self._available,
                "can_install": False, "notes": "", "url": ""}


class FakeShell:
    def toast(self, text: str, kind: str = "ok") -> None:
        pass


def make_settings(api):
    from frontend.quick.settings import Settings

    settings = Settings(api, FakeShell())
    assert _pump_until(lambda: bool(settings.values)), "настройки не загрузились"
    return settings


def test_offer_appears_when_update_found(qt_app):
    api = FakeApi()
    settings = make_settings(api)
    offered: list[str] = []
    settings.updateOffered.connect(offered.append)

    settings._auto_check()
    assert _pump_until(lambda: offered == ["9.9.9"])
    assert settings.update["available"] is True


def test_no_offer_when_version_is_current(qt_app):
    api = FakeApi(available=False)
    settings = make_settings(api)
    offered: list[str] = []
    settings.updateOffered.connect(offered.append)

    settings._auto_check()
    assert _pump_until(lambda: api.checks == 1)
    _pump_until(lambda: False, 0.3)
    assert offered == []


def test_failed_check_is_silent_and_repeats_when_network_returns(qt_app):
    """Без сети проверка молчит, а когда связь появилась — предлагает обновиться."""
    api = FakeApi()
    api.offline_until = 1  # первая проверка не удастся
    settings = make_settings(api)
    offered: list[str] = []
    settings.updateOffered.connect(offered.append)

    settings._auto_check()
    assert _pump_until(lambda: api.checks == 1)
    _pump_until(lambda: False, 0.3)
    assert offered == [], "о сбое сети пользователю сообщать не нужно"

    settings._auto_check()  # как при появлении сети
    assert _pump_until(lambda: offered == ["9.9.9"])


def test_offer_is_shown_once(qt_app):
    api = FakeApi()
    settings = make_settings(api)
    offered: list[str] = []
    settings.updateOffered.connect(offered.append)

    settings._auto_check()
    assert _pump_until(lambda: offered == ["9.9.9"])
    settings._auto_check()
    settings._auto_check()
    _pump_until(lambda: False, 0.3)
    assert offered == ["9.9.9"] and api.checks == 1, "повторно дёргать не нужно"


def test_disabled_in_settings_means_no_requests(qt_app):
    api = FakeApi(check_updates=False)
    settings = make_settings(api)
    offered: list[str] = []
    settings.updateOffered.connect(offered.append)

    settings._auto_check()
    _pump_until(lambda: False, 0.3)
    assert api.checks == 0 and offered == []
