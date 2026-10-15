"""Клиент API Modrinth (синхронный, с кэшем и проверкой хэшей)."""

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import ExternalServiceError, NotFoundError
from shared.version import USER_AGENT

MODRINTH_API = "https://api.modrinth.com/v2"
PROJECT_TYPES = ("mod", "modpack", "resourcepack", "shader", "plugin")
# Совместимые «загрузчики» Modrinth: Quilt грузит Fabric-моды, Paper/Purpur — Bukkit/Spigot-плагины
LOADER_FAMILIES = {
    "quilt": ["quilt", "fabric"],
    "paper": ["paper", "spigot", "bukkit"],
    "purpur": ["purpur", "paper", "spigot", "bukkit"],
}
SORT_INDEXES = ("relevance", "downloads", "follows", "newest", "updated")
_CACHE_TTL = 300
_CACHE_MAX = 512


class ModrinthClient:
    """HTTP клиент Modrinth. Один экземпляр на процесс (потокобезопасен)."""

    def __init__(self, base_url: str = MODRINTH_API, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            transport=transport,
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()

    def close(self) -> None:
        self.client.close()

    # --- Низкоуровневые запросы -----------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None, cache: bool = True) -> Any:
        key = path + "?" + json.dumps(params or {}, sort_keys=True)
        if cache:
            with self._cache_lock:
                hit = self._cache.get(key)
                if hit and time.time() - hit[0] < _CACHE_TTL:
                    return hit[1]
        try:
            resp = self.client.get(path, params=params)
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Modrinth недоступен: {e}") from e
        if resp.status_code == 404:
            raise NotFoundError("Проект или версия не найдены на Modrinth")
        if resp.status_code == 429:
            raise ExternalServiceError("Слишком много запросов к Modrinth, повторите позже")
        if resp.status_code >= 400:
            raise ExternalServiceError(f"Modrinth вернул ошибку {resp.status_code}")
        data = resp.json()
        if cache:
            with self._cache_lock:
                if len(self._cache) >= _CACHE_MAX:
                    self._cache.clear()
                self._cache[key] = (time.time(), data)
        return data

    # --- API ------------------------------------------------------------------
    def search(
        self,
        query: str = "",
        project_type: str = "mod",
        game_version: str | None = None,
        loader: str | None = None,
        limit: int = 20,
        offset: int = 0,
        index: str = "relevance",
        side: str = "client",
        category: str | None = None,
    ) -> dict[str, Any]:
        facets: list[list[str]] = [[f"project_type:{project_type}"]]
        if category:
            facets.append([f"categories:{category}"])
        if game_version:
            facets.append([f"versions:{game_version}"])
        if loader:
            loaders = LOADER_FAMILIES.get(loader, [loader])
            facets.append([f"categories:{name}" for name in loaders])
        if project_type in ("mod", "modpack"):
            facets.append([f"{side}_side:required", f"{side}_side:optional"])
        params = {
            "query": query,
            "limit": limit,
            "offset": offset,
            "index": index if index in SORT_INDEXES else "relevance",
            "facets": json.dumps(facets),
        }
        return self._get("/search", params)

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._get(f"/project/{project_id}")

    def get_projects(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        return self._get("/projects", {"ids": json.dumps(sorted(set(ids)))})

    def get_project_versions(
        self,
        project_id: str,
        game_version: str | None = None,
        loaders: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loaders:
            params["loaders"] = json.dumps(loaders)
        # Версии не кэшируем: обновление мода должно видеть свежий релиз
        return self._get(f"/project/{project_id}/version", params, cache=False)

    def get_version(self, version_id: str) -> dict[str, Any]:
        return self._get(f"/version/{version_id}", cache=False)

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        try:
            resp = self.client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Modrinth недоступен: {e}") from e
        if resp.status_code >= 400:
            raise ExternalServiceError(f"Modrinth вернул ошибку {resp.status_code}")
        return resp.json()

    def versions_by_hashes(self, hashes: list[str], algorithm: str = "sha1") -> dict[str, dict[str, Any]]:
        """Определяет версии Modrinth по хэшам файлов: {hash: version}. Неизвестные хэши отсутствуют."""
        if not hashes:
            return {}
        return self._post("/version_files", {"hashes": hashes, "algorithm": algorithm})

    def latest_versions_by_hashes(self, hashes: list[str], loaders: list[str] | None,
                                  game_versions: list[str], algorithm: str = "sha1") -> dict[str, dict[str, Any]]:
        """Последние совместимые версии для файлов: {hash: version}."""
        if not hashes:
            return {}
        body: dict[str, Any] = {"hashes": hashes, "algorithm": algorithm, "game_versions": game_versions}
        if loaders:
            body["loaders"] = loaders
        return self._post("/version_files/update", body)

    def download_file(self, file_info: dict[str, Any], dest: Path, task=None) -> Path:
        """Скачивает файл версии с проверкой SHA-512/SHA-1. Пишет во временный файл."""
        url = file_info["url"]
        hashes = file_info.get("hashes") or {}
        algo = "sha512" if "sha512" in hashes else "sha1" if "sha1" in hashes else None
        hasher = hashlib.new(algo) if algo else None
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            with self.client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise ExternalServiceError(f"Ошибка загрузки {dest.name}: HTTP {resp.status_code}")
                total = int(resp.headers.get("content-length") or file_info.get("size") or 0)
                if task and total:
                    task.set_max(total)
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(64 * 1024):
                        f.write(chunk)
                        if hasher:
                            hasher.update(chunk)
                        done += len(chunk)
                        if task and total:
                            task.set_progress(done)
            if hasher and hasher.hexdigest() != hashes[algo]:
                raise ExternalServiceError(f"Контрольная сумма {dest.name} не совпала")
            tmp.replace(dest)
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Ошибка загрузки {dest.name}: {e}") from e
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        logger.info(f"Скачан {dest.name}")
        return dest


def pick_primary_file(version: dict[str, Any]) -> dict[str, Any]:
    files = version.get("files") or []
    if not files:
        raise NotFoundError("У версии нет файлов")
    return next((f for f in files if f.get("primary")), files[0])


_client: ModrinthClient | None = None
_client_lock = threading.Lock()


def get_modrinth() -> ModrinthClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ModrinthClient()
        return _client


def set_modrinth(client: ModrinthClient | None) -> None:
    """Подмена клиента (для тестов)."""
    global _client
    with _client_lock:
        _client = client
