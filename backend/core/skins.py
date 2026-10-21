"""Скины и плащи аккаунтов для 3D-модели персонажа в лаунчере.

Откуда берётся скин (по порядку):

1. свой файл, выбранный в лаунчере (``<data>/skins/<id аккаунта>/skin.png`` и ``cape.png``);
2. Microsoft-аккаунт — скин из профиля Minecraft;
3. офлайн-ник — скин и плащ лицензионного игрока с тем же ником (публичное API Mojang);
4. Стив или Алекс из установленной версии игры (как выбирает сама игра по UUID).

Свой скин виден только в лаунчере: офлайн-игра без модов скины не загружает.
"""

import base64
import json
import shutil
import time
import uuid as uuid_lib
import zipfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.auth import Account, AuthManager
from backend.core.errors import BadRequestError
from shared.fsutil import atomic_write_json, read_json
from shared.paths import get_cache_dir, get_data_dir, get_minecraft_dir
from shared.version import USER_AGENT

_PROFILE_URL = "https://api.mojang.com/users/profiles/minecraft/{name}"
_SESSION_URL = "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
_CACHE_TTL = 24 * 3600
_MISS_TTL = 6 * 3600  # «такого лицензионного ника нет» — проверим снова позже
_MAX_PNG = 2 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _custom_dir(account_id: str) -> Path:
    safe = "".join(ch for ch in account_id if ch.isalnum() or ch in "-_")
    if not safe:
        raise BadRequestError("Некорректный аккаунт")
    return get_data_dir() / "skins" / safe


def _cache_dir() -> Path:
    return get_cache_dir() / "skins"


def is_slim_default(player_uuid: str) -> bool:
    """Как игра выбирает Стива/Алекс для игрока без скина: по чётности хэша UUID."""
    try:
        value = uuid_lib.UUID(player_uuid).int
    except (ValueError, AttributeError, TypeError):
        return False
    # java.util.UUID.hashCode(): (int)(hilo >> 32) ^ (int) hilo, где hilo = most ^ least
    hilo = (value >> 64) ^ (value & ((1 << 64) - 1))
    return bool(((hilo >> 32) ^ hilo) & 1)


def _check_png(data: bytes) -> bytes:
    if not data.startswith(_PNG_MAGIC) or len(data) > _MAX_PNG:
        raise BadRequestError("Нужен PNG-файл скина (64×64 или 64×32)")
    return data


def _default_skin(slim: bool) -> Path | None:
    """Стив/Алекс из любого установленного jar игры (в кэш, чтобы не открывать jar каждый раз)."""
    name = "alex" if slim else "steve"
    cached = _cache_dir() / f"default-{name}.png"
    if cached.is_file():
        return cached
    versions = get_minecraft_dir() / "versions"
    jars = sorted(versions.glob("*/*.jar"), key=lambda p: p.stat().st_mtime, reverse=True) if versions.is_dir() else []
    candidates = (f"assets/minecraft/textures/entity/player/{'slim' if slim else 'wide'}/{name}.png",
                  f"assets/minecraft/textures/entity/{name}.png")
    for jar in jars[:10]:
        try:
            with zipfile.ZipFile(jar) as zf:
                names = set(zf.namelist())
                for entry in candidates:
                    if entry in names:
                        cached.parent.mkdir(parents=True, exist_ok=True)
                        cached.write_bytes(zf.read(entry))
                        return cached
        except (OSError, zipfile.BadZipFile):
            continue
    return None


def _http() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(10.0, connect=6.0),
                        follow_redirects=True)


def _download(client: httpx.Client, url: str, dest: Path) -> Path:
    resp = client.get(url)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_check_png(resp.content))
    return dest


def _mojang_textures(username: str) -> dict[str, Any]:
    """Скин и плащ лицензионного игрока с этим ником (кэш на сутки, при сбое сети — ещё попытка)."""
    result = _mojang_textures_once(username)
    if result.get("time") is None:
        result = _mojang_textures_once(username)
    return result


def _mojang_textures_once(username: str) -> dict[str, Any]:
    key = username.lower()
    folder = _cache_dir() / key
    meta_path = folder / "meta.json"
    meta = read_json(meta_path)
    if isinstance(meta, dict):
        ttl = _CACHE_TTL if meta.get("skin") else _MISS_TTL
        if time.time() - float(meta.get("time", 0)) < ttl:
            return meta
    try:
        with _http() as client:
            resp = client.get(_PROFILE_URL.format(name=username))
            if resp.status_code in (204, 404):
                result: dict[str, Any] = {"time": time.time()}
                atomic_write_json(meta_path, result)
                return result
            resp.raise_for_status()
            player = resp.json()["id"]
            profile = client.get(_SESSION_URL.format(uuid=player))
            profile.raise_for_status()
            prop = next(p for p in profile.json().get("properties", []) if p.get("name") == "textures")
            textures = json.loads(base64.b64decode(prop["value"])).get("textures", {})
            result = {"time": time.time(), "slim": False}
            if skin := textures.get("SKIN"):
                result["skin"] = str(_download(client, skin["url"], folder / "skin.png"))
                result["slim"] = (skin.get("metadata") or {}).get("model") == "slim"
            if cape := textures.get("CAPE"):
                result["cape"] = str(_download(client, cape["url"], folder / "cape.png"))
            atomic_write_json(meta_path, result)
            return result
    except (httpx.HTTPError, KeyError, StopIteration, ValueError, BadRequestError) as e:
        logger.debug(f"Скин «{username}» с Mojang не получен: {e}")
        # Старые данные из кэша лучше, чем ничего; без «time» — признак сбоя для повтора
        return {k: v for k, v in meta.items() if k != "time"} if isinstance(meta, dict) else {}


def _microsoft_skin(account: Account) -> dict[str, Any]:
    if not account.skin_url:
        return {}
    dest = _cache_dir() / f"ms-{account.id}.png"
    if dest.is_file() and time.time() - dest.stat().st_mtime < _CACHE_TTL:
        return {"skin": str(dest)}
    try:
        with _http() as client:
            return {"skin": str(_download(client, account.skin_url, dest))}
    except (httpx.HTTPError, BadRequestError) as e:
        logger.debug(f"Скин Microsoft не получен: {e}")
        return {"skin": str(dest)} if dest.is_file() else {}


def skin_info(account_id: str) -> dict[str, Any]:
    """Пути к скину и плащу аккаунта для 3D-модели: {skin, cape, slim, source}."""
    account = AuthManager.get(account_id)
    custom = _custom_dir(account.id)
    custom_meta = read_json(custom / "meta.json") or {}
    info: dict[str, Any] = {"skin": "", "cape": "", "slim": False, "source": "default"}

    if (custom / "skin.png").is_file():
        info.update(skin=str(custom / "skin.png"), slim=bool(custom_meta.get("slim")), source="custom")
    else:
        remote = _microsoft_skin(account) if account.auth_type == "microsoft" else _mojang_textures(account.username)
        if remote.get("skin"):
            info.update(skin=remote["skin"], slim=bool(remote.get("slim")), source="mojang")
            if remote.get("cape"):
                info["cape"] = remote["cape"]
    if (custom / "cape.png").is_file():
        info["cape"] = str(custom / "cape.png")
    if not info["skin"]:
        slim = is_slim_default(account.uuid)
        default = _default_skin(slim)
        info.update(skin=str(default) if default else "", slim=slim, source="default")
    return info


def set_custom_skin(account_id: str, source: Path, slim: bool) -> dict[str, Any]:
    account = AuthManager.get(account_id)
    if not source.is_file():
        raise BadRequestError(f"Файл не найден: {source}")
    _check_png(source.read_bytes())
    folder = _custom_dir(account.id)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, folder / "skin.png")
    atomic_write_json(folder / "meta.json", {"slim": bool(slim)})
    return skin_info(account.id)


def set_custom_cape(account_id: str, source: Path) -> dict[str, Any]:
    account = AuthManager.get(account_id)
    if not source.is_file():
        raise BadRequestError(f"Файл не найден: {source}")
    _check_png(source.read_bytes())
    folder = _custom_dir(account.id)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, folder / "cape.png")
    return skin_info(account.id)


def reset_custom(account_id: str) -> dict[str, Any]:
    """Убирает свой скин и плащ: снова скин с Mojang или по умолчанию."""
    account = AuthManager.get(account_id)
    shutil.rmtree(_custom_dir(account.id), ignore_errors=True)
    return skin_info(account.id)
