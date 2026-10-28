"""Вход Microsoft: откуда берётся Client ID приложения Azure и что видит игрок без него.

Приложение Azure регистрируется один раз на весь лаунчер (см. docs/microsoft-login.md),
его идентификатор вписывается в ``shared.version.MS_CLIENT_ID`` перед сборкой. Игроку
заводить ничего не нужно — поэтому важно, чтобы порядок поиска не сломался незаметно.
"""

import pytest

from backend.core.auth import AuthManager
from backend.core.errors import BadRequestError

BUILT_IN = "00000000-1111-2222-3333-444444444444"
FROM_ENV = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MINE = "99999999-8888-7777-6666-555555555555"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("NEXORA_MS_CLIENT_ID", raising=False)


def test_built_in_id_is_used_when_player_set_nothing(monkeypatch):
    monkeypatch.setattr("backend.core.auth.MS_CLIENT_ID", BUILT_IN)
    assert AuthManager.resolve_client_id() == BUILT_IN
    assert AuthManager.microsoft_available() is True


def test_player_setting_wins_over_everything(monkeypatch):
    monkeypatch.setattr("backend.core.auth.MS_CLIENT_ID", BUILT_IN)
    monkeypatch.setenv("NEXORA_MS_CLIENT_ID", FROM_ENV)
    assert AuthManager.resolve_client_id(MINE) == MINE


def test_environment_wins_over_the_build(monkeypatch):
    """Так проверяют новое приложение Azure до выпуска, не пересобирая лаунчер."""
    monkeypatch.setattr("backend.core.auth.MS_CLIENT_ID", BUILT_IN)
    monkeypatch.setenv("NEXORA_MS_CLIENT_ID", FROM_ENV)
    assert AuthManager.resolve_client_id() == FROM_ENV


def test_spaces_around_the_id_do_not_break_login(monkeypatch):
    """Идентификатор копируют из портала Azure — вместе с пробелом или переводом строки."""
    monkeypatch.setattr("backend.core.auth.MS_CLIENT_ID", "")
    assert AuthManager.resolve_client_id(f"  {MINE}\n") == MINE


def test_without_any_id_login_is_refused_with_a_way_out(monkeypatch):
    """Отказ обязан называть выход: аккаунт Nexora работает и без приложения Azure."""
    monkeypatch.setattr("backend.core.auth.MS_CLIENT_ID", "")
    assert AuthManager.microsoft_available() is False
    with pytest.raises(BadRequestError) as failure:
        AuthManager._msal_app("")
    message = str(failure.value)
    assert "Nexora" in message and "Client ID" in message


def test_settings_tell_the_window_whether_microsoft_works(client, monkeypatch):
    monkeypatch.setattr("backend.core.auth.MS_CLIENT_ID", "")
    assert client.get("/api/v1/settings/").json()["ms_available"] is False

    assert client.patch("/api/v1/settings/", json={"ms_client_id": MINE}).status_code == 200
    assert client.get("/api/v1/settings/").json()["ms_available"] is True
