"""Официальный API CurseForge: отдельные моды (поиск, версии, установка) и сборки.

Нужен ключ с console.curseforge.com («Настройки → Источники сборок»), хранится зашифрованным.
Для сборок это запасной путь (основной — API FTB), для отдельных модов — единственный.

Идентификаторы CurseForge числовые, поэтому внутри лаунчера они везде носят приставку
``curseforge:``: проект — ``curseforge:<modId>``, версия — ``curseforge:<fileId>``. Так моды
CurseForge и Modrinth лежат в одном ``content.json`` и не путаются между собой.

Если автор мода запретил раздачу через сторонние программы, CurseForge не даёт ссылку
(``downloadUrl`` пустой): такие файлы лаунчер не обходит, а честно отправляет на сайт.
"""

import hashlib
import json
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from backend.core.tasks import Task
from shared.config import AppConfig
from shared.crypto import TokenVault
from shared.paths import get_cache_dir
from shared.version import USER_AGENT

API = "https://api.curseforge.com/v1"
_MINECRAFT = 432
_MODPACKS = 4471
# classId проекта → папка внутри .minecraft
_FOLDERS = {6: "mods", 12: "resourcepacks", 6552: "shaderpacks", 6945: "datapacks"}

# Приставка к числовым ID CurseForge внутри лаунчера
PREFIX = "curseforge:"
# Тип контента лаунчера → classId CurseForge (плагинов у CurseForge нет)
CLASS_IDS = {"mod": 6, "resourcepack": 12, "shader": 6552}
# Загрузчик → modLoaderType CurseForge
LOADER_IDS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
LOADER_NAMES = {v: k for k, v in LOADER_IDS.items()}
# Порядок сортировки Modrinth → sortField CurseForge
# (2 — популярность, 3 — последнее обновление, 6 — всего загрузок, 11 — дата выхода)
SORT_FIELDS = {"relevance": 2, "downloads": 6, "follows": 2, "newest": 11, "updated": 3}
# releaseType файла → тип версии в терминах Modrinth
RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}
# relationType зависимости: 3 — обязательная, 2 — необязательная, 5 — несовместимая
_REQUIRED, _INCOMPATIBLE = 3, 5
_CACHE_TTL = 300
_CACHE_MAX = 256
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
# Транспорт httpx для тестов (подменяет сеть целиком, включая CDN)
_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Подмена HTTP-транспорта (для тестов). Сбрасывает кэш ответов."""
    global _transport
    _transport = transport
    with _cache_lock:
        _cache.clear()


def api_key() -> str:
    enc = AppConfig.load().curseforge_key_enc
    return TokenVault.decrypt(enc) if enc else ""


def available() -> bool:
    return bool(api_key())


NO_KEY_MESSAGE = (
    "Каталог CurseForge требует ключ API. Получите бесплатный ключ на console.curseforge.com "
    "(«API Keys») и вставьте его в «Настройки → Источники сборок»."
)


def require_key() -> None:
    """Понятное объяснение вместо пустого списка, если ключа нет."""
    if not available():
        raise BadRequestError(NO_KEY_MESSAGE)


def _client() -> httpx.Client:
    key = api_key()
    if not key:
        raise BadRequestError(NO_KEY_MESSAGE)
    headers = {"x-api-key": key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    return httpx.Client(base_url=API, headers=headers, timeout=httpx.Timeout(30.0, connect=10.0),
                        follow_redirects=True, transport=_transport)


def _payload(resp: httpx.Response) -> dict:
    if resp.status_code == 403:
        raise BadRequestError("CurseForge отклонил ключ API — проверьте его в настройках")
    if resp.status_code == 404:
        raise NotFoundError("Проект или файл не найдены на CurseForge")
    if resp.status_code == 429:
        raise ExternalServiceError("Слишком много запросов к CurseForge, повторите позже")
    if resp.status_code >= 400:
        raise ExternalServiceError(f"CurseForge: HTTP {resp.status_code}")
    data = resp.json()
    return data if isinstance(data, dict) else {"data": data}


def _check(resp: httpx.Response) -> Any:
    return _payload(resp).get("data")


def _get(path: str, params: dict[str, Any] | None = None, cache: bool = True) -> dict:
    """GET к API CurseForge: возвращает весь ответ (вместе с pagination)."""
    key = path + "?" + json.dumps(params or {}, sort_keys=True, default=str)
    if cache:
        with _cache_lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < _CACHE_TTL:
                return hit[1]
    with _client() as client:
        try:
            resp = client.get(path, params=params)
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"CurseForge недоступен: {e}") from e
    payload = _payload(resp)
    if cache:
        with _cache_lock:
            if len(_cache) >= _CACHE_MAX:
                _cache.clear()
            _cache[key] = (time.time(), payload)
    return payload


def _post(path: str, body: dict[str, Any]) -> Any:
    with _client() as client:
        try:
            resp = client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"CurseForge недоступен: {e}") from e
    return _check(resp)


# --- Идентификаторы -------------------------------------------------------------------------------
def is_curseforge(any_id: str | None) -> bool:
    return bool(any_id) and str(any_id).startswith(PREFIX)


def numeric_id(any_id: str | int) -> int:
    """«curseforge:238222» → 238222. Непохожее на ID CurseForge — ошибка запроса."""
    raw = str(any_id)
    raw = raw[len(PREFIX):] if raw.startswith(PREFIX) else raw
    if not raw.isdigit():
        raise BadRequestError(f"Непонятный идентификатор CurseForge: {any_id}")
    return int(raw)


def tagged_id(value: int | str) -> str:
    return f"{PREFIX}{value}"


def _row(mod: dict) -> dict[str, Any]:
    latest = (mod.get("latestFilesIndexes") or [{}])[0]
    loader = {1: "forge", 4: "fabric", 5: "quilt", 6: "neoforge"}.get(latest.get("modLoader"), "")
    return {
        "project_id": f"curseforge:{mod['id']}", "slug": mod.get("slug", ""), "title": mod.get("name", ""),
        "author": ", ".join(a.get("name", "") for a in (mod.get("authors") or [])[:2]),
        "description": mod.get("summary", ""), "downloads": int(mod.get("downloadCount") or 0),
        "categories": [c.get("name", "") for c in (mod.get("categories") or [])[:4]],
        "game_versions": [latest["gameVersion"]] if latest.get("gameVersion") else [],
        "loaders": [loader] if loader else [], "icon_url": (mod.get("logo") or {}).get("url", ""),
        "gallery": [s.get("url", "") for s in (mod.get("screenshots") or [])[:8]], "provider": "curseforge",
        "versions": [],
    }


def search(term: str, limit: int = 20) -> list[dict[str, Any]]:
    with _client() as client:
        data = _check(client.get("/mods/search", params={
            "gameId": _MINECRAFT, "classId": _MODPACKS, "searchFilter": term, "sortField": 2, "sortOrder": "desc",
            "pageSize": limit}))
    return [_row(m) for m in data or []]


# --- Каталог отдельных модов ----------------------------------------------------------------------
def _authors(mod: dict) -> str:
    return ", ".join(a.get("name", "") for a in (mod.get("authors") or [])[:2])


def _game_versions(mod: dict) -> list[str]:
    """Версии игры из latestFilesIndexes: там и номера версий, и загрузчик каждого файла."""
    seen = {i["gameVersion"] for i in mod.get("latestFilesIndexes") or [] if i.get("gameVersion")}
    return sorted(seen)


def _mod_loaders(mod: dict) -> list[str]:
    ids = {i.get("modLoader") for i in mod.get("latestFilesIndexes") or []}
    return [name for key, name in sorted(LOADER_NAMES.items()) if key in ids]


def mod_row(mod: dict) -> dict[str, Any]:
    """Карточка проекта CurseForge в терминах каталога лаунчера (как у Modrinth)."""
    class_id = mod.get("classId")
    project_type = next((name for name, cid in CLASS_IDS.items() if cid == class_id), "mod")
    return {
        "project_id": tagged_id(mod["id"]),
        "slug": mod.get("slug", ""),
        "title": mod.get("name", ""),
        "description": mod.get("summary", ""),
        "project_type": project_type,
        "author": _authors(mod),
        "categories": [c.get("name", "") for c in (mod.get("categories") or [])[:6] if c.get("name")],
        "downloads": int(mod.get("downloadCount") or 0),
        # У CurseForge нет «подписчиков», ближайшее по смыслу — thumbsUpCount
        "follows": int(mod.get("thumbsUpCount") or 0),
        "icon_url": (mod.get("logo") or {}).get("url", ""),
        "game_versions": _game_versions(mod),
        "loaders": _mod_loaders(mod),
        "gallery": [s.get("url", "") for s in (mod.get("screenshots") or []) if s.get("url")][:6],
        "page_url": (mod.get("links") or {}).get("websiteUrl") or "",
        "provider": "curseforge",
    }


def file_row(file: dict) -> dict[str, Any]:
    """Файл CurseForge в терминах «версии проекта» Modrinth."""
    names = [v.lower() for v in file.get("gameVersions") or []]
    blocked = not file.get("downloadUrl")
    return {
        "id": tagged_id(file["id"]),
        "project_id": tagged_id(file.get("modId", 0)),
        "name": file.get("displayName", "") or file.get("fileName", ""),
        "version_number": file.get("displayName", "") or file.get("fileName", ""),
        "version_type": RELEASE_TYPES.get(file.get("releaseType"), "release"),
        "game_versions": [v for v in file.get("gameVersions") or [] if v.lower() not in LOADER_IDS],
        "loaders": [name for name in LOADER_IDS if name in names],
        "date_published": file.get("fileDate", ""),
        "downloads": int(file.get("downloadCount") or 0),
        "files": [{"filename": file.get("fileName", ""), "size": int(file.get("fileLength") or 0),
                   "primary": True, "blocked": blocked}],
        # Пустой downloadUrl = автор запретил скачивание сторонними программами
        "blocked": blocked,
    }


def search_mods(query: str = "", content_type: str = "mod", game_version: str | None = None,
                loader: str | None = None, limit: int = 20, offset: int = 0,
                index: str = "relevance") -> dict[str, Any]:
    """Поиск отдельных модов, ресурспаков и шейдеров. Возвращает {results, total}."""
    if content_type not in CLASS_IDS:
        raise BadRequestError(f"CurseForge не отдаёт контент типа «{content_type}»")
    params: dict[str, Any] = {
        "gameId": _MINECRAFT, "classId": CLASS_IDS[content_type], "searchFilter": query,
        "sortField": SORT_FIELDS.get(index, SORT_FIELDS["relevance"]), "sortOrder": "desc",
        "pageSize": min(max(limit, 1), 50), "index": min(offset, 9_000),
    }
    if game_version:
        params["gameVersion"] = game_version
    if loader and content_type == "mod":
        # Модов под Quilt на CurseForge почти нет, зато он грузит Fabric-моды
        loader_type = LOADER_IDS.get("fabric" if loader == "quilt" else loader)
        if loader_type:
            params["modLoaderType"] = loader_type
    payload = _get("/mods/search", params)
    total = int((payload.get("pagination") or {}).get("totalCount") or 0)
    return {"results": [mod_row(m) for m in payload.get("data") or []], "total": total}


def get_mod(project_id: str | int) -> dict[str, Any]:
    """Сырой проект CurseForge по ID (с приставкой или без)."""
    data = _get(f"/mods/{numeric_id(project_id)}").get("data")
    if not data:
        raise NotFoundError("Проект не найден на CurseForge")
    return data


def get_mods(project_ids: list[str | int]) -> list[dict[str, Any]]:
    """Несколько проектов одним запросом (нужно для проверки обновлений)."""
    ids = sorted({numeric_id(i) for i in project_ids})
    if not ids:
        return []
    return _post("/mods", {"modIds": ids}) or []


def mod_files(project_id: str | int, game_version: str | None = None, loader: str | None = None,
              limit: int = 50) -> list[dict[str, Any]]:
    """Файлы проекта, свежие сначала. Фильтры CurseForge применяет сам."""
    params: dict[str, Any] = {"pageSize": min(max(limit, 1), 50)}
    if game_version:
        params["gameVersion"] = game_version
    if loader:
        params["modLoaderType"] = LOADER_IDS.get("fabric" if loader == "quilt" else loader)
    # Файлы не кэшируем: обновление мода должно видеть свежий релиз
    files = _get(f"/mods/{numeric_id(project_id)}/files", params, cache=False).get("data") or []
    return sorted(files, key=lambda f: f.get("fileDate", ""), reverse=True)


def get_file(file_id: str | int) -> dict[str, Any]:
    """Один файл по его ID (modId знать не нужно)."""
    files = _post("/mods/files", {"fileIds": [numeric_id(file_id)]}) or []
    if not files:
        raise NotFoundError("Файл не найден на CurseForge")
    return files[0]


def _matches(file: dict, game_version: str | None, loaders: list[str] | None) -> bool:
    names = [v.lower() for v in file.get("gameVersions") or []]
    if game_version and game_version.lower() not in names:
        return False
    if loaders and any(name in names for name in LOADER_IDS):
        return any(name in names for name in loaders)
    return True  # файл вообще не указывает загрузчик (так делают старые моды под Forge)


def pick_file(files: list[dict[str, Any]], game_version: str | None = None,
              loaders: list[str] | None = None) -> dict[str, Any]:
    """Подходящий файл: сначала релизы, внутри — самый свежий."""
    suitable = [f for f in files if _matches(f, game_version, loaders)]
    if not suitable:
        raise NotFoundError(f"На CurseForge нет файла под {' '.join(loaders or [])} {game_version or ''}".strip())
    releases = [f for f in suitable if f.get("releaseType") == 1]
    return sorted(releases or suitable, key=lambda f: f.get("fileDate", ""), reverse=True)[0]


def blocked_message(mod: dict, file: dict) -> str:
    """Честное объяснение для файлов, которые автор запретил скачивать сторонним программам."""
    link = (mod.get("links") or {}).get("websiteUrl") or "https://www.curseforge.com/minecraft/mc-mods"
    name = file.get("displayName") or file.get("fileName") or mod.get("name", "мод")
    return (f"Автор запретил скачивание «{name}» через сторонние программы. "
            f"Скачайте файл вручную на {link} и добавьте его кнопкой «Добавить файл».")


def required_dependencies(file: dict) -> list[int]:
    """modId обязательных зависимостей файла."""
    return [int(d["modId"]) for d in file.get("dependencies") or []
            if d.get("relationType") == _REQUIRED and d.get("modId")]


def incompatible_dependencies(file: dict) -> list[int]:
    return [int(d["modId"]) for d in file.get("dependencies") or []
            if d.get("relationType") == _INCOMPATIBLE and d.get("modId")]


def file_sha1(file: dict) -> str:
    return next((str(h.get("value", "")).lower() for h in file.get("hashes") or [] if h.get("algo") == 1), "")


def download_file(file: dict, dest: Path, task: Task | None = None) -> Path:
    """Скачивает файл CurseForge с проверкой SHA-1. Ключ API нужен только самому API, не CDN."""
    url = file.get("downloadUrl")
    if not url:
        raise BadRequestError(blocked_message({}, file))
    expected = file_sha1(file)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    hasher = hashlib.sha1()
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(60.0, connect=10.0),
                          follow_redirects=True, transport=_transport) as cdn, \
                cdn.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise ExternalServiceError(f"Ошибка загрузки {dest.name}: HTTP {resp.status_code}")
            total = int(resp.headers.get("content-length") or file.get("fileLength") or 0)
            if task and total:
                task.set_max(total)
            done = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(256 * 1024):
                    f.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    if task and total:
                        task.set_progress(done)
        if expected and hasher.hexdigest() != expected:
            raise ExternalServiceError(f"Контрольная сумма {dest.name} не совпала")
        tmp.replace(dest)
    except httpx.HTTPError as e:
        raise ExternalServiceError(f"Ошибка загрузки {dest.name}: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)
    logger.info(f"Скачан {dest.name} с CurseForge")
    return dest


def install(project_id: int, file_id: int | None, new_name: str = "", task: Task | None = None):
    """Скачивает zip сборки, ставит моды из manifest.json и распаковывает overrides.

    Возвращает (сборка, имена модов, которые автор запретил скачивать автоматически).
    """
    from backend.core.ftb_packs import _client as plain_client
    from backend.core.ftb_packs import _download
    from backend.core.instance import InstanceManager, folder_for_title
    from backend.core.minecraft import MinecraftManager

    with _client() as client:
        mod = _check(client.get(f"/mods/{project_id}"))
        if file_id is None:
            files = _check(client.get(f"/mods/{project_id}/files", params={"pageSize": 50})) or []
            files = sorted(files, key=lambda f: f.get("fileDate", ""), reverse=True)
            stable = [f for f in files if f.get("releaseType") == 1]
            if not (stable or files):
                raise BadRequestError("У сборки нет файлов")
            pack_file = (stable or files)[0]
        else:
            pack_file = _check(client.get(f"/mods/{project_id}/files/{file_id}"))
        if not pack_file.get("downloadUrl"):
            raise BadRequestError("Автор запретил скачивание этой сборки через сторонние программы")
        archive = get_cache_dir() / "modpacks" / f"cf-{pack_file['id']}.zip"
        if task:
            task.set_status(f"Загрузка {mod.get('name', 'сборки')}…")
        with plain_client() as cdn:  # без ключа: он нужен только самому API
            _download(cdn, {"url": pack_file["downloadUrl"], "name": archive.name}, archive)
        with zipfile.ZipFile(archive) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        mc = (manifest.get("minecraft") or {}).get("version", "")
        primary = next((m["id"] for m in (manifest.get("minecraft") or {}).get("modLoaders", []) if m.get("primary")),
                       "")
        loader, _, loader_version = primary.partition("-")
        refs = [f for f in manifest.get("files") or [] if f.get("required", True)]
        resolved = _check(client.post("/mods/files", json={"fileIds": [f["fileID"] for f in refs]})) or []
        projects = _check(client.post("/mods", json={"modIds": list({f["projectID"] for f in refs})})) or []

    folder_of = {p["id"]: _FOLDERS.get(p.get("classId"), "mods") for p in projects}
    title = mod.get("name") or f"CurseForge {project_id}"
    name = new_name or folder_for_title(title, {i.name for i in InstanceManager.list_instances()})
    instance = InstanceManager.create(name, mc, loader if loader in ("forge", "neoforge", "fabric", "quilt")
                                      else "vanilla", loader_version, title="" if new_name else title)
    blocked: list[str] = []
    try:
        entries = []
        for f in resolved:
            sha1 = next((h["value"] for h in f.get("hashes") or [] if h.get("algo") == 1), "")
            if not f.get("downloadUrl"):
                blocked.append(f.get("displayName") or f.get("fileName", ""))
                continue
            entries.append({"url": f["downloadUrl"], "name": f["fileName"], "sha1": sha1,
                            "path": folder_of.get(f.get("modId"), "mods") + "/"})
        from backend.core.ftb_packs import _extract_overrides, download_files
        download_files(entries, instance.game_dir, task)
        _extract_overrides(archive, instance.game_dir)
        MinecraftManager().prepare_instance(instance, task)
    except Exception:
        shutil.rmtree(instance.path, ignore_errors=True)
        raise
    finally:
        Path(archive).unlink(missing_ok=True)
    if blocked:
        logger.warning(f"CurseForge: авторы запретили автоматическое скачивание: {', '.join(blocked)}")
    return InstanceManager.get(name), blocked
