"""Java, модпаки из Modrinth, Microsoft-аккаунты (с заглушками сети)."""

import io
import json
import time
import zipfile

import pytest

from backend.core import auth as auth_module
from backend.core.auth import Account, AccountStore, AuthManager
from backend.core.errors import AuthRequiredError, ExternalServiceError
from backend.core.java_detector import parse_major


@pytest.mark.parametrize("version,major", [("1.8.0_381", 8), ("17.0.2", 17), ("21", 21), ("", 0),
                                           ("25-ea", 25)])
def test_parse_java_major(version, major):
    assert parse_major(version) == major


def _mrpack_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps({
            "formatVersion": 1, "game": "minecraft", "name": "Speedy", "versionId": "1",
            "files": [], "dependencies": {"minecraft": "1.20.1", "quilt-loader": "0.20.0"},
        }))
    return buffer.getvalue()


def test_install_modpack_from_modrinth(client, modrinth, wait_task, fake_minecraft, monkeypatch):
    import minecraft_launcher_lib as mll
    monkeypatch.setattr(mll.mrpack, "install_mrpack", lambda *a, **k: None)
    version = modrinth.add_project("speedy", "Speedy Pack", "speedy.mrpack", project_type="modpack")
    data = _mrpack_bytes()
    modrinth.files["speedy.mrpack"] = data
    import hashlib
    version["files"][0]["hashes"] = {"sha512": hashlib.sha512(data).hexdigest()}

    task = client.post("/api/v1/modpacks/install", json={"project_id": "speedy"}).json()
    result = wait_task(task["id"])
    assert result["status"] == "done", result["error"]
    instance = client.get("/api/v1/instances/Speedy Pack").json()
    assert instance["mod_loader"] == "quilt" and instance["version"] == "1.20.1"
    assert client.post("/api/v1/modpacks/install",
                       json={"project_id": "speedy", "new_name": "../x"}).status_code == 400


class FakeMsal:
    def __init__(self, result):
        self.result = result

    def acquire_token_by_refresh_token(self, refresh_token, scopes):
        return self.result


def _ms_account(expired: bool) -> Account:
    account = Account(id="ms1", username="Notch", uuid="069a79f4-44e9-4726-a5be-fca90e38aaf5",
                      auth_type="microsoft", added_at=time.time())
    account.set_tokens("old-access", "old-refresh", -10 if expired else 3600)
    AccountStore.save([account], "ms1")
    return account


def test_launch_credentials_refresh_expired_token(monkeypatch):
    _ms_account(expired=True)
    monkeypatch.setattr(AuthManager, "_msal_app",
                        staticmethod(lambda cid: FakeMsal({"access_token": "ms", "refresh_token": "new-refresh"})))
    monkeypatch.setattr(AuthManager, "_minecraft_login", staticmethod(lambda token: {
        "id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch", "skins": [],
        "mc_access_token": "fresh-mc-token", "mc_expires_in": 86400}))
    creds = AuthManager.get_launch_credentials("client")
    assert creds["token"] == "fresh-mc-token" and creds["username"] == "Notch"
    stored = AuthManager.get("ms1")
    assert stored.refresh_token == "new-refresh" and stored.expires_at > time.time()


def test_valid_token_is_not_refreshed(monkeypatch):
    _ms_account(expired=False)
    monkeypatch.setattr(AuthManager, "_msal_app", staticmethod(lambda cid: pytest.fail("refresh called")))
    assert AuthManager.get_launch_credentials("client")["token"] == "old-access"


def test_refresh_failure_requires_relogin(monkeypatch):
    _ms_account(expired=True)
    monkeypatch.setattr(AuthManager, "_msal_app",
                        staticmethod(lambda cid: FakeMsal({"error": "invalid_grant",
                                                           "error_description": "expired"})))
    with pytest.raises(AuthRequiredError):
        AuthManager.get_launch_credentials("client")


def test_xbox_errors_are_explained(monkeypatch):
    mll_ms = auth_module.mll.microsoft_account
    monkeypatch.setattr(mll_ms, "authenticate_with_xbl",
                        lambda token: {"Token": "x", "DisplayClaims": {"xui": [{"uhs": "h"}]}})
    monkeypatch.setattr(mll_ms, "authenticate_with_xsts", lambda token: {"XErr": 2148916233})
    with pytest.raises(ExternalServiceError, match="Xbox"):
        AuthManager._minecraft_login("token")

    monkeypatch.setattr(mll_ms, "authenticate_with_xsts", lambda token: {"Token": "xsts"})
    monkeypatch.setattr(mll_ms, "authenticate_with_minecraft", lambda uhs, token: {"access_token": "mc"})
    monkeypatch.setattr(mll_ms, "get_profile", lambda token: {"error": "NOT_FOUND"})
    with pytest.raises(ExternalServiceError, match="лицензии"):
        AuthManager._minecraft_login("token")
