"""Аккаунт Nexora: вход, регистрация, скин и плащ с сервера аккаунтов.

Сервер (PHP на хостинге) здесь подменён: httpx ходит в поддельный транспорт, который
отвечает так же, как настоящий API — те же адреса, те же коды и формат ошибок.
"""

import hashlib
import os

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

API = "https://nexora.test/api/v1"
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)   # для сервера-двойника важно только начало файла


def _url(sha: str) -> str:
    return f"https://nexora.test/textures/{sha[:2]}/{sha}.png"


class FakeServer:
    """Сервер аккаунтов в памяти: один игрок, один токен, скин и плащ."""

    def __init__(self):
        self.password = "очень-длинный-пароль"
        self.token = "token-1"
        self.expires = "2099-01-01T00:00:00+00:00"
        self.account = {"username": "Player_1", "uuid": "914e9094-dd43-376a-a052-b63bf94389aa",
                        "email": "player@example.com", "skin_model": "classic",
                        "skin_url": None, "cape_url": None}
        self.textures: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.registered: list[dict] = []

    # --- ответы -------------------------------------------------------------------------
    @staticmethod
    def _error(status: int, code: str, message: str) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "message": message}})

    def _session(self) -> httpx.Response:
        return httpx.Response(200, json={"token": self.token, "expires_at": self.expires,
                                         "account": self.account})

    def _store(self, kind: str, data: bytes, model: str = "") -> httpx.Response:
        sha = hashlib.sha256(data).hexdigest()
        self.textures[sha] = data
        self.account[f"{kind}_url"] = _url(sha)
        if model:
            self.account["skin_model"] = model
        return httpx.Response(200, json={"account": self.account})

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace("/api/v1", "", 1)
        self.calls.append(f"{request.method} {path}")
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        needs_token = path.startswith("/account") or path in ("/auth/refresh", "/auth/logout")
        if needs_token and token != self.token:
            return self._error(401, "auth_required", "Сессия истекла — войдите заново")

        if path == "/auth/login":
            body = request.read().decode()
            if self.password not in body:
                return self._error(401, "bad_credentials", "Неверный ник или пароль")
            return self._session()
        if path == "/auth/register":
            import json
            body = json.loads(request.read())
            if body["username"] == self.account["username"]:
                return self._error(409, "already_exists", "Такой ник или адрес почты уже занят")
            self.registered.append(body)
            self.account = {**self.account, "username": body["username"], "email": body["email"]}
            return httpx.Response(201, json={"account": self.account})
        if path == "/auth/refresh":
            self.token = "token-2"
            return self._session()
        if path == "/auth/logout":
            self.token = ""
            return httpx.Response(200, json={"status": "ok"})
        if path == "/account":
            return httpx.Response(200, json={"account": self.account})
        if path in ("/account/skin", "/account/cape"):
            kind = path.rsplit("/", 1)[1]
            if request.method == "DELETE":
                self.account[f"{kind}_url"] = None
                return httpx.Response(200, json={"account": self.account})
            model = request.url.params.get("model", "") if kind == "skin" else ""
            return self._store(kind, request.read(), model)

        if request.url.path.startswith("/textures/"):
            sha = request.url.path.rsplit("/", 1)[1].removesuffix(".png")
            data = self.textures.get(sha)
            return httpx.Response(200, content=data) if data else httpx.Response(404)
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "Нет такого адреса"}})


@pytest.fixture
def server(monkeypatch):
    """Поддельный сервер аккаунтов вместо nexoralauncher.ru."""
    from backend.core import nexora_account
    fake = FakeServer()
    monkeypatch.setenv("NEXORA_API_URL", API)

    def client() -> httpx.Client:
        return httpx.Client(base_url=API, transport=httpx.MockTransport(fake.handle))

    monkeypatch.setattr(nexora_account, "_client", client)
    return fake


@pytest.fixture
def logged_in(client, server):
    """Вход выполнен, аккаунт добавлен и активен. Возвращает его id."""
    response = client.post("/api/v1/auth/nexora/login",
                           json={"login": "Player_1", "password": server.password})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_login_adds_account(client, server, logged_in):
    account = client.get("/api/v1/auth/profile").json()
    assert account["auth_type"] == "nexora" and account["username"] == "Player_1"
    assert account["active"] is True and account["expired"] is False
    assert account["email"] == "player@example.com"
    # Пароль нигде не сохраняется — в файле аккаунтов только зашифрованный токен
    from shared.paths import get_config_dir
    saved = (get_config_dir() / "accounts.json").read_text(encoding="utf-8")
    assert server.password not in saved and server.token not in saved


def test_login_with_wrong_password_shows_server_message(client, server):
    response = client.post("/api/v1/auth/nexora/login", json={"login": "Player_1", "password": "неверный"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный ник или пароль"


def test_register_conflict(client, server):
    response = client.post("/api/v1/auth/nexora/register",
                           json={"username": "Player_1", "email": "a@b.cc", "password": "длинный-пароль"})
    assert response.status_code == 409
    assert "занят" in response.json()["detail"]


def test_register_then_login(client, server):
    response = client.post("/api/v1/auth/nexora/register",
                           json={"username": "Steve_2", "email": "steve@example.com",
                                 "password": server.password})
    assert response.status_code == 201, response.text
    assert response.json()["username"] == "Steve_2"
    assert server.registered and server.registered[0]["email"] == "steve@example.com"
    # Регистрация заканчивается входом: токен уже есть, пароль второй раз не спрашиваем
    assert "POST /auth/login" in server.calls


def test_skin_and_cape_go_to_server_and_come_back(client, server, logged_in, tmp_path):
    skin, cape = tmp_path / "skin.png", tmp_path / "cape.png"
    skin.write_bytes(PNG)
    cape.write_bytes(PNG + b"cape")

    info = client.put(f"/api/v1/auth/accounts/{logged_in}/skin",
                      json={"path": str(skin), "slim": True}).json()
    assert info["source"] == "nexora" and info["slim"] is True
    # Файл приехал обратно с сервера и лежит в кэше под именем-хэшем
    assert info["skin"].endswith(hashlib.sha256(PNG).hexdigest() + ".png")
    from pathlib import Path
    assert Path(info["skin"]).read_bytes() == PNG

    info = client.put(f"/api/v1/auth/accounts/{logged_in}/cape", json={"path": str(cape)}).json()
    assert info["cape"].endswith(hashlib.sha256(PNG + b"cape").hexdigest() + ".png")
    assert server.account["skin_model"] == "slim"

    # Своей копии рядом с лаунчером не остаётся: источник правды — сервер
    from shared.paths import get_data_dir
    assert not (get_data_dir() / "skins" / logged_in / "skin.png").exists()


def test_reset_clears_textures_on_server(client, server, logged_in, tmp_path, monkeypatch):
    skin = tmp_path / "skin.png"
    skin.write_bytes(PNG)
    client.put(f"/api/v1/auth/accounts/{logged_in}/skin", json={"path": str(skin), "slim": False})

    info = client.delete(f"/api/v1/auth/accounts/{logged_in}/skin").json()
    assert server.account["skin_url"] is None and server.account["cape_url"] is None
    assert info["source"] == "default" and info["cape"] == ""


def test_texture_downloaded_once(client, server, logged_in, tmp_path):
    skin = tmp_path / "skin.png"
    skin.write_bytes(PNG)
    client.put(f"/api/v1/auth/accounts/{logged_in}/skin", json={"path": str(skin), "slim": False})
    downloads = [c for c in server.calls if c.startswith("GET /textures/")]
    client.get(f"/api/v1/auth/accounts/{logged_in}/skin")
    client.get(f"/api/v1/auth/accounts/{logged_in}/skin")
    assert [c for c in server.calls if c.startswith("GET /textures/")] == downloads


def test_expired_session_asks_to_sign_in_again(client, server, logged_in, tmp_path, monkeypatch):
    from backend.core.auth import AccountStore
    accounts, active = AccountStore.load()
    for account in accounts:
        account.expires_at = 0.0          # сессия кончилась, пока лаунчер был закрыт
    AccountStore.save(accounts, active)

    assert client.get("/api/v1/auth/profile").json()["expired"] is True
    skin = tmp_path / "skin.png"
    skin.write_bytes(PNG)
    response = client.put(f"/api/v1/auth/accounts/{logged_in}/skin", json={"path": str(skin), "slim": False})
    assert response.status_code == 401 and "Войдите" in response.json()["detail"]


def test_session_refreshed_before_it_runs_out(client, server, logged_in):
    import time

    from backend.core.auth import AccountStore, AuthManager
    accounts, active = AccountStore.load()
    accounts[0].expires_at = time.time() + 2 * 86400    # осталось два дня — пора продлевать
    AccountStore.save(accounts, active)

    token = AuthManager.nexora_token(AuthManager.get(logged_in))
    assert token == "token-2" and "POST /auth/refresh" in server.calls
    assert AuthManager.get(logged_in).access_token == "token-2"


def test_remove_account_closes_session_on_server(client, server, logged_in):
    assert client.delete(f"/api/v1/auth/accounts/{logged_in}").status_code == 204
    assert "POST /auth/logout" in server.calls
    assert client.get("/api/v1/auth/accounts").json() == []


def test_server_down_is_reported_plainly(client, monkeypatch):
    from backend.core import nexora_account
    monkeypatch.setenv("NEXORA_API_URL", API)

    def broken() -> httpx.Client:
        def fail(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("нет связи")
        return httpx.Client(base_url=API, transport=httpx.MockTransport(fail))

    monkeypatch.setattr(nexora_account, "_client", broken)
    response = client.post("/api/v1/auth/nexora/login", json={"login": "Player_1", "password": "пароль"})
    assert response.status_code == 502
    assert response.json()["detail"] == "Нет связи с сервером аккаунтов Nexora"


# --- Окно входа в интерфейсе ------------------------------------------------------------------
def _pump_until(predicate, timeout: float = 10.0) -> bool:
    import time

    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def qt_app():
    import sys

    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_dialog_signs_in_and_model_gets_the_skin(qt_app, server, tmp_path, monkeypatch):
    """Путь целиком: окно «Добавить аккаунт» → вход Nexora → скин с сервера в 3D-модели."""
    from PySide6.QtCore import QMetaObject

    from frontend.backend_runner import EmbeddedBackend
    from frontend.quick.app import QuickUi
    from frontend.services.api_client import ApiClient

    skin = tmp_path / "skin.png"
    skin.write_bytes(PNG)

    backend = EmbeddedBackend()
    backend.start()
    api = ApiClient(backend.base_url, backend.token)
    ui = None
    try:
        ui = QuickUi(api, dark=True)
        warnings: list[str] = []
        ui.engine.warnings.connect(lambda items: warnings.extend(w.toString() for w in items))
        assert ui.show()
        shell = ui.shell

        dialog = ui.window.findChild(object, "addAccount")
        assert dialog is not None
        QMetaObject.invokeMethod(dialog, "open")
        assert dialog.property("mode") == "nexora"          # вкладка Nexora открыта сразу
        assert dialog.property("acceptEnabled") is False    # пустую форму отправить нельзя

        # Пользователь набрал ник и пароль и нажал «Войти»
        shell.addNexoraAccount("Player_1", server.password)
        assert _pump_until(lambda: shell.nexora.get("state") == "done")
        assert _pump_until(lambda: shell.account.get("name") == "Player_1")
        assert shell.account["kind"] == "Nexora"

        # Скин, загруженный в лаунчере, уходит на сервер и возвращается в 3D-модель
        shell.chooseSkin(str(skin), True)
        assert _pump_until(lambda: shell.skin.get("source") == "nexora")
        assert shell.skin["slim"] is True
        assert shell.skin["skin"].endswith(hashlib.sha256(PNG).hexdigest() + ".png")
        assert not [w for w in warnings if "qml" in w.lower()], warnings
    finally:
        if ui is not None:
            ui.close()
        api.close()
        backend.stop()
