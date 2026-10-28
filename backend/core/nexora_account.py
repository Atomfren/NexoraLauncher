"""Аккаунт Nexora: связь с сервером аккаунтов и скинов на nexoralauncher.ru.

Сервер — PHP и MySQL на хостинге (его исходники лежат в ``nexora-site/api``). Он хранит
ник, почту, пароль, а ещё скин и плащ игрока, поэтому они видны на другом компьютере
и — с модом CustomSkinLoader — в самой игре.

Лаунчер держит у себя только токен сессии: он живёт 30 дней, шифруется ``TokenVault``
и лежит в ``accounts.json`` рядом с остальными аккаунтами. Пароль не сохраняется нигде.

Адрес сервера можно подменить переменной окружения ``NEXORA_API_URL`` — это нужно тестам
и тем, кто поднимает свой сервер аккаунтов.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import (
    AuthRequiredError,
    BadRequestError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from shared.version import USER_AGENT, WEBSITE_URL

_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
_MAX_TEXTURE = 512 * 1024          # столько же, сколько принимает сервер
# Токен продлеваем заранее: иначе игрок, заходящий раз в месяц, каждый раз вводит пароль
_REFRESH_BEFORE = 7 * 24 * 3600

# Коды ответа сервера → исключения лаунчера. Текст ошибки сервер присылает по-русски,
# и показываем мы именно его: он точнее, чем общая фраза про «ошибку сервиса».
_ERRORS = {
    400: BadRequestError,
    401: AuthRequiredError,
    403: AuthRequiredError,
    404: NotFoundError,
    405: BadRequestError,
    409: ConflictError,
    413: BadRequestError,
    429: BadRequestError,
}


def base_url() -> str:
    """Адрес API. По умолчанию — сайт лаунчера, но его можно подменить окружением."""
    return (os.environ.get("NEXORA_API_URL") or f"{WEBSITE_URL}/api/v1").rstrip("/")


def _client() -> httpx.Client:
    return httpx.Client(base_url=base_url(), headers={"User-Agent": USER_AGENT},
                        timeout=_TIMEOUT, follow_redirects=True)


def _auth(token: str) -> dict[str, str]:
    if not token:
        raise AuthRequiredError("Нужен вход в аккаунт Nexora")
    return {"Authorization": f"Bearer {token}"}


def _call(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with _client() as client:
            response = client.request(method, path, **kwargs)
    except httpx.HTTPError as error:
        logger.debug(f"Сервер аккаунтов недоступен: {error}")
        raise ExternalServiceError("Нет связи с сервером аккаунтов Nexora") from error

    if response.status_code == 204 or not response.content:
        if response.status_code >= 400:
            raise _ERRORS.get(response.status_code, ExternalServiceError)(
                f"Сервер аккаунтов ответил {response.status_code}")
        return {}
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}

    if response.status_code >= 400:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        message = str(error.get("message") or f"Сервер аккаунтов ответил {response.status_code}")
        raise _ERRORS.get(response.status_code, ExternalServiceError)(message)
    return data


def _expires_in(value: str) -> int:
    """Сколько секунд осталось до конца сессии (сервер присылает время по ISO 8601)."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 30 * 86400
    return max(0, int(moment.timestamp() - datetime.now(moment.tzinfo).timestamp()))


# --- Вход и регистрация ---------------------------------------------------------------------
def login(login_name: str, password: str) -> dict[str, Any]:
    """Вход по нику или почте. Возвращает ``{token, expires_in, account}``."""
    if not login_name.strip() or not password:
        raise BadRequestError("Введите ник (или почту) и пароль")
    data = _call("POST", "/auth/login", json={"login": login_name.strip(), "password": password})
    return {
        "token": str(data.get("token", "")),
        "expires_in": _expires_in(data.get("expires_at", "")),
        "account": data.get("account") or {},
    }


def register(username: str, email: str, password: str) -> dict[str, Any]:
    """Регистрация и сразу вход — чтобы не спрашивать пароль дважды."""
    _call("POST", "/auth/register", json={"username": username.strip(), "email": email.strip(),
                                          "password": password})
    return login(username, password)


def refresh(token: str) -> dict[str, Any]:
    """Продлить сессию: сервер гасит прежний токен и выдаёт новый."""
    data = _call("POST", "/auth/refresh", headers=_auth(token))
    return {
        "token": str(data.get("token", "")),
        "expires_in": _expires_in(data.get("expires_at", "")),
        "account": data.get("account") or {},
    }


def needs_refresh(expires_at: float, now: float) -> bool:
    """Пора ли продлевать сессию (и не поздно ли уже)."""
    return now < expires_at <= now + _REFRESH_BEFORE


def logout(token: str) -> None:
    """Закрыть сессию. Вызывается при удалении аккаунта и ошибкой наружу не выходит."""
    try:
        _call("POST", "/auth/logout", headers=_auth(token))
    except (AuthRequiredError, BadRequestError, NotFoundError, ExternalServiceError) as error:
        logger.debug(f"Сессия Nexora не закрыта на сервере: {error}")


def profile(token: str) -> dict[str, Any]:
    """Свежие данные аккаунта: ник, почта, ссылки на скин и плащ."""
    return _call("GET", "/account", headers=_auth(token)).get("account") or {}


# --- Скин и плащ ----------------------------------------------------------------------------
def _texture_bytes(source: Path) -> bytes:
    if not source.is_file():
        raise BadRequestError(f"Файл не найден: {source}")
    data = source.read_bytes()
    if len(data) > _MAX_TEXTURE:
        raise BadRequestError(f"Файл больше {_MAX_TEXTURE // 1024} КБ — это не скин, а что-то другое")
    return data


def upload_skin(token: str, source: Path, slim: bool) -> dict[str, Any]:
    """Загрузить скин. Сервер сам проверяет PNG и чистит его от лишних кусков."""
    data = _call("PUT", "/account/skin", headers={**_auth(token), "Content-Type": "image/png"},
                 params={"model": "slim" if slim else "classic"}, content=_texture_bytes(source))
    return data.get("account") or {}


def upload_cape(token: str, source: Path) -> dict[str, Any]:
    data = _call("PUT", "/account/cape", headers={**_auth(token), "Content-Type": "image/png"},
                 content=_texture_bytes(source))
    return data.get("account") or {}


def clear_textures(token: str) -> dict[str, Any]:
    """Убрать с сервера и скин, и плащ."""
    _call("DELETE", "/account/skin", headers=_auth(token))
    data = _call("DELETE", "/account/cape", headers=_auth(token))
    return data.get("account") or {}


def download(url: str, dest: Path) -> Path:
    """Скачать текстуру по ссылке с сервера в файл (имя задаёт вызывающий)."""
    try:
        with _client() as client:
            response = client.get(url)
            response.raise_for_status()
            content = response.content
    except httpx.HTTPError as error:
        raise ExternalServiceError(f"Текстура не скачалась: {error}") from error
    if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) > _MAX_TEXTURE:
        raise ExternalServiceError("Сервер прислал не PNG")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest
