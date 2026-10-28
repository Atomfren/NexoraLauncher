"""Отпечаток вылета: чистка от личных данных, устойчивость подписи, согласие на отправку."""

import json
import time

import httpx
import pytest

from backend.core import crash_signature
from shared.i18n import t

# В логе нарочно собрано всё, что ни при каких условиях не должно уйти на сервер:
# ник игрока, путь с именем пользователя Windows, токен входа, IP, почта и UUID сессии.
DIRTY_LOG = """\
[20:10:01] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.11
[20:10:01] [main/INFO]: Loading 3 mods:
[20:10:01] [main/INFO]: Java is OpenJDK 64-Bit Server VM, version 17.0.9+9
[20:10:02] [main/INFO]: Setting user: Steve
[20:10:02] [main/INFO]: --accessToken eyJhbGciOiJIUzI1NiJ9.aaaaaaaaaaaaaaaaaaaaaaaa --uuid 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d
[20:10:02] [main/INFO]: Game dir C:\\Users\\Ivan\\AppData\\Roaming\\nexoralauncher\\instances\\My
[20:10:03] [main/INFO]: Connecting to 192.168.1.15 as steve@example.com
[20:10:20] [Render thread/ERROR]: Uncaught exception in render thread
java.lang.OutOfMemoryError: Java heap space at C:\\Users\\Ivan\\mods\\sodium.jar
\tat me.jellysquid.mods.sodium.client.render.Chunk.update(Chunk.java:42)
"""

# Тот же вылет у другого человека: ник, пути и версия загрузчика другие
OTHER_LOG = DIRTY_LOG.replace("Steve", "Alexandra").replace("Ivan", "Pyotr")

SECRETS = ("Steve", "Ivan", "eyJhbG", "192.168.1.15", "steve@example.com",
           "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d", "AppData", "Users")


def _instance_with_log(client, name: str, text: str = DIRTY_LOG):
    from backend.core.instance import Instance
    client.post("/api/v1/instances/", json={"name": name, "version": "1.20.1", "mod_loader": "fabric",
                                            "install": False})
    instance = Instance.load(name)
    instance.logs_dir.mkdir(parents=True, exist_ok=True)
    (instance.logs_dir / "2026-10-13_20-10-00.log").write_text(text, encoding="utf-8")
    return instance


@pytest.fixture
def no_network(monkeypatch):
    """Любая попытка выйти в сеть во время теста — это ошибка теста."""
    def forbidden(*_a, **_kw):
        raise AssertionError("отпечаток ушёл в сеть без согласия")

    monkeypatch.setattr(crash_signature.httpx, "Client", forbidden)


def test_scrub_removes_nick_path_and_token():
    text = ("Setting user: Steve token=eyJhbGciOiJIUzI1NiJ9.aaaaaaaaaaaaaaaaaaaaaaaa "
            "from C:\\Users\\Ivan\\mods\\x.jar and /home/ivan/.minecraft on 10.0.0.7 "
            "session 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d mail steve@example.com")
    clean = crash_signature.scrub(text, names={"Steve", "Ivan"})
    for secret in ("Steve", "Ivan", "ivan", "eyJhbG", "10.0.0.7", "steve@example.com",
                   "9b1deb4d", "C:\\Users"):
        assert secret not in clean, f"в отпечатке осталось «{secret}»: {clean}"
    # Полезное остаётся: по нему Доктор и узнаёт ошибку
    assert "Setting user" in clean


def test_scrub_keeps_versions_and_classes():
    clean = crash_signature.scrub("java.lang.OutOfMemoryError: Java heap space (Fabric 0.15.11, MC 1.20.1)",
                                  names=set())
    assert "java.lang.OutOfMemoryError" in clean and "0.15.11" in clean and "1.20.1" in clean


def test_signature_has_no_personal_data(client):
    from backend.core.auth import AuthManager
    AuthManager.offline_login("Steve")   # ник игрока лаунчер знает — значит, обязан его вычистить
    _instance_with_log(client, "Dirty")

    preview = crash_signature.preview("Dirty")
    text = preview["text"]
    for secret in SECRETS:
        assert secret not in text, f"в отпечатке осталось «{secret}»: {text}"
    signature = preview["signature"]
    assert signature["error_class"] == "java.lang.OutOfMemoryError"
    assert signature["rule"] == "memory" and signature["java"] == "17"
    assert (signature["minecraft"], signature["loader"], signature["loader_version"]) \
        == ("1.20.1", "fabric", "0.15.11")
    assert signature["outcome"] == "crashed" and signature["helped"] is None
    # Больше ничего: список полей закрытый, «на всякий случай» в него ничего не попадает
    assert tuple(signature) == crash_signature._FIELDS
    assert json.loads(text) == signature


def test_signature_is_the_same_for_the_same_crash(client):
    _instance_with_log(client, "A", DIRTY_LOG)
    _instance_with_log(client, "B", OTHER_LOG)
    first = crash_signature.build("A")["signature"]
    second = crash_signature.build("B")["signature"]
    assert first == second and len(first) == 32


def test_signature_differs_for_another_error(client):
    _instance_with_log(client, "Oom", DIRTY_LOG)
    _instance_with_log(client, "Mixin", DIRTY_LOG.replace(
        "java.lang.OutOfMemoryError: Java heap space",
        "org.spongepowered.asm.mixin.throwables.MixinApplyError: apply failed"))
    assert crash_signature.build("Oom")["signature"] != crash_signature.build("Mixin")["signature"]


def test_preview_endpoint_does_not_send_anything(client, no_network):
    _instance_with_log(client, "Preview")
    response = client.get("/api/v1/instances/Preview/doctor/signature")
    assert response.status_code == 200
    data = response.json()
    assert data["fields"] == list(crash_signature._FIELDS)
    assert "Ivan" not in data["text"]


def test_send_without_consent_is_refused(client, no_network):
    _instance_with_log(client, "NoConsent")
    response = client.post("/api/v1/instances/NoConsent/doctor/signature", json={})
    assert response.status_code == 400
    response = client.post("/api/v1/instances/NoConsent/doctor/signature", json={"consent": False, "helped": True})
    assert response.status_code == 400


def test_send_with_consent_posts_clean_signature(client, monkeypatch):
    _instance_with_log(client, "Sent")
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["url"] = str(request.url)
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok"})

    real = httpx.Client
    monkeypatch.setattr(crash_signature.httpx, "Client",
                        lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    response = client.post("/api/v1/instances/Sent/doctor/signature",
                           json={"consent": True, "helped": True, "fix": "set_memory"})
    assert response.status_code == 200 and response.json()["sent"] is True
    assert sent["url"].endswith("/crash-signatures")
    body = sent["body"]
    assert body["helped"] is True and body["fix"] == "set_memory"
    assert "ip" not in body and "user" not in body and "path" not in body
    for secret in SECRETS:
        assert secret not in json.dumps(body, ensure_ascii=False)


def test_server_error_is_reported(client, monkeypatch):
    _instance_with_log(client, "Broken")
    real = httpx.Client
    monkeypatch.setattr(crash_signature.httpx, "Client", lambda *a, **kw: real(
        *a, **{**kw, "transport": httpx.MockTransport(lambda _r: httpx.Response(500, json={}))}))
    response = client.post("/api/v1/instances/Broken/doctor/signature", json={"consent": True})
    assert response.status_code == 502


def test_log_without_errors_has_nothing_to_send(client, no_network):
    _instance_with_log(client, "Clean", "[20:10:01] [main/INFO]: Loading Minecraft 1.20.1\n")
    assert client.get("/api/v1/instances/Clean/doctor/signature").status_code == 400
    assert client.post("/api/v1/instances/Clean/doctor/signature", json={"consent": True}).status_code == 400


# --- Интерфейс: показать → спросить → отправить ------------------------------------------------
def _pump_until(predicate, timeout: float = 5.0) -> bool:
    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


class _FakeShell:
    def __init__(self):
        self.toasts: list[tuple[str, str]] = []

    def toast(self, message: str, kind: str = "ok") -> None:
        self.toasts.append((message, kind))


class _FakeApi:
    def __init__(self):
        self.previews: list[tuple] = []
        self.sent: list[tuple] = []

    def crash_signature(self, name, helped=None, fix=""):
        self.previews.append((name, helped, fix))
        return {"text": '{"signature": "abc"}'}

    def send_crash_signature(self, name, helped=None, fix=""):
        self.sent.append((name, helped, fix))
        return {"sent": True}


def test_bridge_never_sends_without_the_send_button():
    pytest.importorskip("PySide6.QtQuick")
    import sys

    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    from frontend.quick.doctor import CrashReport
    QApplication.instance() or QApplication(sys.argv)

    class FakeLibrary(QObject):
        selectedChanged = Signal()   # noqa: N815 — имя сигнала как в Qt-мосте

        def __init__(self):
            super().__init__()
            self.selected = "Dirty"

    api, shell, library = _FakeApi(), _FakeShell(), FakeLibrary()
    crash = CrashReport(api, shell, library)
    assert crash.report == {"state": "idle"}

    # Пока отпечаток не показан, «Отправить» ничего не делает
    crash.send()
    assert api.sent == []

    crash.askHelped("set_memory")
    assert crash.report["state"] == "ask" and api.previews == []

    crash.prepare(1)
    assert _pump_until(lambda: crash.report["state"] == "ready")
    assert api.previews == [("Dirty", True, "set_memory")] and api.sent == []
    assert crash.report["text"] == '{"signature": "abc"}'

    crash.send()
    assert _pump_until(lambda: bool(api.sent))
    assert api.sent == [("Dirty", True, "set_memory")]
    assert _pump_until(lambda: crash.report["state"] == "idle")
    assert shell.toasts and shell.toasts[0][0] == t("q.crash_sent")

    # Отказ: отпечаток забывается, второй отправки не происходит
    crash.prepare(0)
    assert _pump_until(lambda: crash.report["state"] == "ready")
    crash.dismiss()
    crash.send()
    assert len(api.sent) == 1
