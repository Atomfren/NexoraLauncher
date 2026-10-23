"""Языки, которые можно докачать с сайта.

Встроенных языков два — русский и английский. Остальные лежат на сайте отдельными файлами
и ставятся по кнопке: лаунчер скачивает пакет, проверяет его и кладёт в
``<config>/languages/<код>.json``. При следующем запуске язык доступен в настройках.

Доверие устроено так же, как у обновлений: список языков ``languages.json`` подписан нашим
ключом Ed25519, а SHA-256 каждого пакета берётся из этого подписанного списка. Подменить
перевод по дороге нельзя — иначе в интерфейс можно было бы подсунуть, например, просьбу
ввести пароль от аккаунта.

Формат пакета::

    {"code": "uk", "name": "Українська", "version": "1.0", "author": "кто перевёл",
     "strings": {"q.play": "Грати", ...}}
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from backend.core.self_update import SIGNATURE_SUFFIX, is_configured, verify_signed
from backend.core.tasks import Task
from shared import i18n
from shared.fsutil import atomic_write_text
from shared.paths import get_config_dir
from shared.version import LANGUAGE_INDEX_URLS, USER_AGENT

CODE_RE = re.compile(r"^[a-z]{2}(-[a-z]{2,8})?$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_INDEX_BYTES = 256 * 1024
_MAX_PACK_BYTES = 4 * 1024 * 1024


def languages_dir() -> Path:
    return get_config_dir() / "languages"


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)


def index_urls() -> list[str]:
    import os

    override = os.environ.get("NEXORA_LANGUAGES_URL", "").strip()
    return [override] if override else [url for url in LANGUAGE_INDEX_URLS if url]


# --- Пакеты на диске -----------------------------------------------------------------------------
def read_pack(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Читает пакет с диска. Возвращает сведения о языке и сами строки."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("пакет должен быть объектом JSON")
    code = str(data.get("code") or path.stem).strip().lower()
    if not CODE_RE.match(code):
        raise ValueError(f"недопустимый код языка: {code!r}")
    strings = data.get("strings")
    if not isinstance(strings, dict) or not strings:
        raise ValueError("в пакете нет строк")
    meta = {k: data.get(k, "") for k in ("code", "name", "version", "author")}
    meta["code"] = code
    return meta, {str(k): str(v) for k, v in strings.items() if isinstance(v, str)}


def load_installed() -> list[str]:
    """Подключает все пакеты с диска. Вызывается при старте backend."""
    loaded = []
    folder = languages_dir()
    if not folder.is_dir():
        return loaded
    for path in sorted(folder.glob("*.json")):
        try:
            meta, strings = read_pack(path)
            loaded.append(i18n.add_pack(meta, strings))
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Языковой пакет {path.name} пропущен: {e}")
    if loaded:
        logger.info(f"Докачанные языки: {', '.join(loaded)}")
    return loaded


def installed() -> list[dict[str, Any]]:
    return sorted(i18n.installed_packs().values(), key=lambda item: item["code"])


def remove(code: str) -> dict[str, Any]:
    """Удаляет язык. Если он был выбран, язык интерфейса вернётся к русскому."""
    code = (code or "").strip().lower()
    path = languages_dir() / f"{code}.json"
    if code not in i18n.installed_packs() and not path.is_file():
        raise NotFoundError(f"Язык «{code}» не установлен")
    path.unlink(missing_ok=True)
    i18n.drop_pack(code)
    from shared.config import AppConfig

    config = AppConfig.load()
    if config.language == code:
        config.update(language="ru")
    logger.info(f"Язык {code} удалён")
    return {"code": code, "removed": True}


# --- Список на сайте -----------------------------------------------------------------------------
def catalog() -> dict[str, Any]:
    """Подписанный список языков с сайта: ``{"languages": [...], "_url": ...}``."""
    if not is_configured():
        raise BadRequestError("Канал обновлений не настроен: в сборке нет открытого ключа")
    errors: list[str] = []
    with _client() as client:
        for url in index_urls():
            try:
                raw = client.get(url)
                if raw.status_code != 200:
                    raise ExternalServiceError(f"HTTP {raw.status_code}")
                if len(raw.content) > _MAX_INDEX_BYTES:
                    raise ExternalServiceError("список языков подозрительно велик")
                signature = client.get(url + SIGNATURE_SUFFIX)
                if signature.status_code != 200:
                    raise ExternalServiceError(f"нет подписи (HTTP {signature.status_code})")
                data = verify_signed(raw.content, signature.text)
                items = data.get("languages")
                if not isinstance(items, list):
                    raise ExternalServiceError("в списке языков нет раздела languages")
                data["_url"] = url
                return data
            except (ExternalServiceError, httpx.HTTPError) as e:
                errors.append(f"{url}: {e}")
                logger.debug(f"Список языков недоступен — {url}: {e}")
    raise ExternalServiceError("Не удалось получить список языков. " + "; ".join(errors))


def available() -> list[dict[str, Any]]:
    """Языки с сайта с пометкой, что уже установлено и что обновилось."""
    data = catalog()
    here = i18n.installed_packs()
    result = []
    for entry in data["languages"]:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().lower()
        if not CODE_RE.match(code) or code in ("ru", "en"):
            continue
        mine = here.get(code)
        result.append({
            "code": code,
            "name": str(entry.get("name") or code),
            "version": str(entry.get("version") or ""),
            "author": str(entry.get("author") or ""),
            "translated": int(entry.get("translated") or 0),
            "total": int(entry.get("total") or len(i18n.pack_keys())),
            "size": int(entry.get("size") or 0),
            "installed": mine is not None,
            "update_available": bool(mine and str(entry.get("version") or "") != mine["version"]),
        })
    return sorted(result, key=lambda item: item["name"].lower())


def _entry(code: str) -> tuple[dict[str, Any], str]:
    data = catalog()
    for entry in data["languages"]:
        if isinstance(entry, dict) and str(entry.get("code", "")).lower() == code:
            return entry, str(data["_url"])
    raise NotFoundError(f"Языка «{code}» нет на сайте")


def install(code: str, task: Task | None = None) -> dict[str, Any]:
    """Скачивает языковой пакет, проверяет его и подключает."""
    code = (code or "").strip().lower()
    if not CODE_RE.match(code):
        raise BadRequestError(f"Недопустимый код языка: {code!r}")
    if code in ("ru", "en"):
        raise BadRequestError("Этот язык встроен в лаунчер")

    entry, index_url = _entry(code)
    file_name = str(entry.get("file") or "")
    expected_hash = str(entry.get("sha256") or "").lower()
    if not file_name:
        raise ExternalServiceError("В списке языков нет файла пакета")
    if not _SHA256_RE.match(expected_hash):
        raise ExternalServiceError("В списке языков нет SHA-256 пакета")

    url = str(entry.get("url") or "") or urljoin(index_url, file_name)
    if task:
        task.set_status(f"Загрузка перевода «{entry.get('name', code)}»…")
    with _client() as client:
        response = client.get(url)
    if response.status_code != 200:
        raise ExternalServiceError(f"Не удалось скачать язык: HTTP {response.status_code}")
    content = response.content
    if len(content) > _MAX_PACK_BYTES:
        raise ExternalServiceError("Языковой пакет подозрительно велик")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise ExternalServiceError("Контрольная сумма перевода не совпала — файл повреждён или подменён")

    try:
        data = json.loads(content.decode("utf-8"))
        meta, strings = read_pack_data(data, code)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        raise ExternalServiceError(f"Языковой пакет испорчен: {e}") from e

    languages_dir().mkdir(parents=True, exist_ok=True)
    atomic_write_text(languages_dir() / f"{code}.json",
                      json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    i18n.add_pack(meta, strings)
    logger.info(f"Язык {code} установлен: строк {len(strings)}")
    return {"code": code, "name": meta.get("name", code), "translated": len(strings),
            "total": len(i18n.pack_keys())}


def read_pack_data(data: Any, code: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Разбирает содержимое пакета (уже прочитанный JSON)."""
    if not isinstance(data, dict):
        raise ValueError("пакет должен быть объектом JSON")
    if str(data.get("code", code)).lower() != code:
        raise ValueError("код языка в пакете не совпадает со списком")
    strings = data.get("strings")
    if not isinstance(strings, dict) or not strings:
        raise ValueError("в пакете нет строк")
    meta = {"code": code, "name": data.get("name", code), "version": data.get("version", ""),
            "author": data.get("author", "")}
    return meta, {str(k): str(v) for k, v in strings.items() if isinstance(v, str)}


def state(online: bool = True) -> dict[str, Any]:
    """Сводка для интерфейса: встроенные, установленные и доступные языки.

    ``online=False`` — только то, что уже есть на диске: так интерфейс получает список
    установленных языков мгновенно, не дожидаясь сайта.
    """
    builtin = [{"code": code, "name": name, "builtin": True} for code, name in i18n.BUILTIN_NAMES.items()]
    if not online:
        return {"builtin": builtin, "installed": installed(), "available": [], "error": ""}
    try:
        online = available()
        error = ""
    except (ExternalServiceError, BadRequestError) as e:
        online, error = [], str(e)
    return {"builtin": builtin, "installed": installed(), "available": online, "error": error}
