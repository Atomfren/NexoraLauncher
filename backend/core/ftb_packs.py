"""Сборки FTB и CurseForge (All The Mods и др.) через публичный API FTB.

API FTB (``api.feed-the-beast.com/v1/modpacks/public``) отдаёт и свои сборки, и сборки CurseForge:
поиск, описание, версии и манифест версии — список файлов с прямыми ссылками и SHA-1.
Конфиги и квесты сборок CurseForge приходят одной записью ``cf-extract``: это архив сборки,
из которого распаковывается папка ``overrides``.

Если API FTB недоступен для сборок CurseForge, а в настройках указан ключ CurseForge,
используется официальный API CurseForge (:mod:`backend.services.curseforge_client`).
"""

import hashlib
import shutil
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError, NexoraError
from backend.core.instance import InstanceManager, folder_for_title
from backend.core.minecraft import MinecraftManager
from backend.core.tasks import Task
from shared.fsutil import UnsafePathError, atomic_write_json, read_json, safe_extract_zip, safe_join
from shared.paths import get_cache_dir
from shared.version import USER_AGENT

API = "https://api.feed-the-beast.com/v1/modpacks/public"
PROVIDERS = ("ftb", "curseforge")
_LOADERS = ("neoforge", "forge", "fabric", "quilt")
_CACHE_TTL = 6 * 3600  # описания и манифесты меняются редко
_SEARCH_TTL = 3600
_PARALLEL = 8
_ATTEMPTS = 3
# Пустой поиск: для CurseForge — семейство All The Mods (самые популярные «большие» сборки)
_DEFAULT_CF_TERM = "all the mods"

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


# --- HTTP ----------------------------------------------------------------------------------------
def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(30.0, connect=10.0),
                        follow_redirects=True)


def _disk_path(path: str) -> Path:
    return get_cache_dir() / "ftb" / (hashlib.sha1(path.encode("utf-8")).hexdigest() + ".json")


def _get_json(path: str, ttl: float = _CACHE_TTL) -> Any:
    """GET к API FTB: кэш в памяти и на диске, повтор при сбое сети.

    Через медленный прокси запрос идёт секунды, поэтому ответы хранятся на диске: каталог открывается
    сразу, а без сети используется последняя сохранённая копия.
    """
    now = time.time()
    with _cache_lock:
        hit = _cache.get(path)
        if hit and now - hit[0] < ttl:
            return hit[1]
    disk = _disk_path(path)
    saved = read_json(disk)
    if isinstance(saved, dict) and "data" in saved and now - float(saved.get("time", 0)) < ttl:
        with _cache_lock:
            _cache[path] = (float(saved["time"]), saved["data"])
        return saved["data"]
    last: Exception | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            with _client() as client:
                resp = client.get(API + path)
            if resp.status_code == 404:
                raise BadRequestError("Сборка не найдена")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("status") == "error":
                raise BadRequestError(data.get("message") or data.get("error") or "Ошибка API FTB")
            with _cache_lock:
                _cache[path] = (time.time(), data)
            try:
                atomic_write_json(disk, {"time": time.time(), "data": data})
            except OSError as e:
                logger.debug(f"Кэш FTB не записан: {e}")
            return data
        except (httpx.HTTPError, ValueError) as e:
            last = e
            if attempt < _ATTEMPTS:
                time.sleep(attempt)
    if isinstance(saved, dict) and "data" in saved:
        logger.warning(f"API FTB недоступен, используется сохранённая копия: {last}")
        return saved["data"]
    raise ExternalServiceError(f"API FTB не отвечает: {last}")


def _base(provider: str) -> str:
    if provider not in PROVIDERS:
        raise BadRequestError(f"Неизвестный источник: {provider}")
    return "/modpack" if provider == "ftb" else "/curseforge"


# --- Каталог -------------------------------------------------------------------------------------
def _art(data: dict, kind: str) -> str:
    return next((a.get("url", "") for a in data.get("art") or [] if a.get("type") == kind), "")


def _latest(versions: list[dict]) -> dict | None:
    """Свежая стабильная версия (или просто свежая, если стабильных нет)."""
    ordered = sorted((v for v in versions if not v.get("private")), key=lambda v: v.get("updated", 0))
    releases = [v for v in ordered if v.get("type", "release") == "release"]
    return (releases or ordered or [None])[-1]


def _targets(targets: list[dict]) -> tuple[str, str, str]:
    """(версия Minecraft, загрузчик, версия загрузчика) из targets версии."""
    mc = next((t.get("version", "") for t in targets if t.get("type") == "game"), "")
    loader = next((t for t in targets if t.get("type") == "modloader"), {})
    name = (loader.get("name") or "").lower()
    version = loader.get("version", "")
    if version.lower() in _LOADERS:  # в списке версий CurseForge вместо номера — имя загрузчика
        version = ""
    return mc, name if name in _LOADERS else "vanilla", version


def pack_row(provider: str, data: dict) -> dict[str, Any]:
    """Строка каталога в формате, похожем на поиск Modrinth."""
    latest = _latest(data.get("versions") or []) or {}
    mc, loader, _ = _targets(latest.get("targets") or [])
    authors = ", ".join(a.get("name", "") for a in (data.get("authors") or [])[:2])
    return {
        "project_id": f"{provider}:{data['id']}", "slug": data.get("slug", ""),
        "title": " ".join((data.get("name") or "").split()),
        "author": authors, "description": data.get("synopsis") or "",
        "downloads": int(data.get("installs") or 0),
        "categories": [t.get("name", "") for t in (data.get("tags") or [])[:4]],
        "game_versions": [mc] if mc else [], "loaders": [loader] if loader != "vanilla" else [],
        "icon_url": _art(data, "square") or _art(data, "thumbnail"),
        "gallery": [a.get("url", "") for a in data.get("art") or [] if a.get("type") == "screenshot"][:8],
        "provider": provider,
        "versions": [{"id": v["id"], "name": v.get("name", "").removesuffix(".zip"), "type": v.get("type", ""),
                      "updated": v.get("updated", 0), "mc": _targets(v.get("targets") or [])[0]}
                     for v in sorted(data.get("versions") or [], key=lambda v: v.get("updated", 0), reverse=True)
                     if not v.get("private")][:20],
    }


def pack(provider: str, pack_id: int) -> dict[str, Any]:
    return _get_json(f"{_base(provider)}/{int(pack_id)}")


def search(provider: str, term: str, limit: int = 20) -> list[dict[str, Any]]:
    """Поиск сборок FTB или CurseForge. Пустой запрос — избранное и популярное."""
    term = " ".join((term or "").split())
    if provider == "curseforge" and not term:
        term = _DEFAULT_CF_TERM
    try:
        if term:
            found = _get_json(f"/modpack/search/{max(limit, 10)}?term={quote(term)}", _SEARCH_TTL)
            ids = found.get("packs" if provider == "ftb" else "curseforge") or []
        else:
            featured = _get_json(f"/modpack/featured/{limit}", _SEARCH_TTL).get("packs") or []
            popular = _get_json(f"/modpack/popular/installs/{limit}", _SEARCH_TTL).get("packs") or []
            ids = list(dict.fromkeys(featured + popular))
    except ExternalServiceError:
        if provider == "curseforge":
            from backend.services import curseforge_client
            if curseforge_client.available():
                return curseforge_client.search(term, limit)
        raise
    ids = ids[:limit]

    def load(pack_id: int) -> dict | None:
        try:
            return pack_row(provider, pack(provider, pack_id))
        except NexoraError as e:
            logger.debug(f"Сборка {provider}:{pack_id} пропущена: {e}")
            return None

    with ThreadPoolExecutor(max_workers=_PARALLEL) as pool:
        rows = list(pool.map(load, ids))
    return [r for r in rows if r]


# --- Установка -----------------------------------------------------------------------------------
def _file_target(game_dir: Path, entry: dict) -> Path:
    rel = (entry.get("path") or "./").replace("\\", "/").lstrip("/")
    rel = rel[2:] if rel.startswith("./") else rel
    try:
        return safe_join(game_dir, *[p for p in rel.split("/") if p and p != "."], entry["name"])
    except UnsafePathError as e:
        raise BadRequestError(f"Недопустимый путь в манифесте: {rel}{entry.get('name')}") from e


def _download(client: httpx.Client, entry: dict, dest: Path) -> Path:
    """Скачивает файл манифеста с проверкой SHA-1; повторы и запасные зеркала."""
    expected = (entry.get("sha1") or (entry.get("hashes") or {}).get("sha1") or "").lower()
    if dest.is_file() and expected and hashlib.sha1(dest.read_bytes()).hexdigest() == expected:
        return dest  # уже скачан (повторная установка после сбоя)
    urls = [entry["url"], *(entry.get("mirrors") or [])]
    last: Exception | None = None
    for attempt in range(_ATTEMPTS):
        url = urls[attempt % len(urls)]
        tmp = dest.with_name(dest.name + ".part")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            hasher = hashlib.sha1()
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(256 * 1024):
                        f.write(chunk)
                        hasher.update(chunk)
            if expected and hasher.hexdigest() != expected:
                raise ExternalServiceError(f"Контрольная сумма {dest.name} не совпала")
            tmp.replace(dest)
            return dest
        except (httpx.HTTPError, ExternalServiceError, OSError) as e:
            last = e
            time.sleep(1 + attempt)
        finally:
            tmp.unlink(missing_ok=True)
    raise ExternalServiceError(f"Не удалось скачать {entry.get('name')}: {last}")


def _extract_overrides(archive: Path, game_dir: Path) -> None:
    """Архив сборки CurseForge: содержимое папки overrides (конфиги, квесты, скрипты) — в игру."""
    with zipfile.ZipFile(archive) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        prefix = "overrides/"
        try:
            import json
            manifest = json.loads(zf.read("manifest.json"))
            prefix = (manifest.get("overrides") or "overrides").strip("/") + "/"
        except (KeyError, ValueError):
            pass
        if any(n.startswith(prefix) for n in names):
            safe_extract_zip(zf, game_dir, strip_prefix=prefix)


def download_files(files: list[dict], game_dir: Path, task: Task | None = None) -> None:
    """Скачивает все файлы версии (кроме серверных и необязательных) параллельно."""
    wanted = [f for f in files if not f.get("serveronly") and not f.get("optional") and f.get("url")]
    extract = [f for f in wanted if f.get("type") == "cf-extract"]
    regular = [f for f in wanted if f.get("type") != "cf-extract"]
    if task:
        task.set_max(len(wanted))
        task.set_progress(0)
    done = 0
    lock = threading.Lock()

    # Пути проверяем и папки создаём заранее, в одном потоке: resolve() на Windows ненадёжен,
    # пока соседние потоки создают те же папки
    targets = {id(entry): _file_target(game_dir, entry) for entry in regular}
    for folder in {t.parent for t in targets.values()}:
        folder.mkdir(parents=True, exist_ok=True)

    def one(entry: dict) -> None:
        nonlocal done
        _download(client, entry, targets[id(entry)])
        with lock:
            done += 1
            if task:
                task.set_progress(done)
                task.set_status(f"Загрузка файлов сборки: {done} из {len(wanted)}")

    with _client() as client, ThreadPoolExecutor(max_workers=_PARALLEL) as pool:
        futures = [pool.submit(one, entry) for entry in regular]
        for future in as_completed(futures):
            if task:
                task.check_cancelled()
            future.result()
        for entry in extract:
            archive = get_cache_dir() / "modpacks" / f"cf-{entry.get('id', 'pack')}.zip"
            if task:
                task.set_status("Загрузка конфигов и квестов сборки…")
            _download(client, dict(entry, path="./", name=archive.name), archive)
            try:
                _extract_overrides(archive, game_dir)
            finally:
                archive.unlink(missing_ok=True)
            done += 1
            if task:
                task.set_progress(done)


def install(provider: str, pack_id: int, version_id: int | None = None, new_name: str = "",
            task: Task | None = None):
    """Новая сборка из FTB или CurseForge. Возвращает (сборка, моды для ручного скачивания)."""
    try:
        data = pack(provider, pack_id)
    except ExternalServiceError:
        if provider == "curseforge":
            from backend.services import curseforge_client
            if curseforge_client.available():
                return curseforge_client.install(int(pack_id), version_id, new_name, task)
        raise
    version = next((v for v in data.get("versions") or [] if v.get("id") == version_id), None) if version_id \
        else _latest(data.get("versions") or [])
    if not version:
        raise BadRequestError("У сборки нет доступных версий")
    if task:
        task.set_status(f"Получение списка файлов «{data.get('name', pack_id)}»…")
    manifest = _get_json(f"{_base(provider)}/{int(pack_id)}/{int(version['id'])}")
    mc, loader, loader_version = _targets(manifest.get("targets") or [])
    if not mc:
        raise BadRequestError("В сборке не указана версия Minecraft")

    title = " ".join((data.get("name") or "").split()) or f"Pack {pack_id}"
    existing = {i.name for i in InstanceManager.list_instances()}
    name = new_name or folder_for_title(title, existing)
    instance = InstanceManager.create(name, mc, loader, loader_version, title="" if new_name else title)
    try:
        memory = (manifest.get("specs") or {}).get("recommended")
        if memory:
            instance = InstanceManager.update(name, max_memory=int(memory))
        download_files(manifest.get("files") or [], instance.game_dir, task)
        atomic_write_json(instance.path / "pack.json", {
            "provider": provider, "pack_id": int(pack_id), "version_id": int(version["id"]),
            "version": manifest.get("name") or version.get("name", ""), "name": title,
        })
        MinecraftManager().prepare_instance(instance, task)
    except Exception:
        shutil.rmtree(instance.path, ignore_errors=True)
        raise
    logger.info(f"Сборка {provider}:{pack_id} «{title}» установлена как «{name}»")
    return InstanceManager.get(name), []
