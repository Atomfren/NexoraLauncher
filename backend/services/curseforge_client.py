"""Официальный API CurseForge — запасной путь для сборок CurseForge (All The Mods и др.).

Нужен ключ с console.curseforge.com («Настройки → Источники сборок»), хранится зашифрованным.
Если автор мода запретил раздачу через сторонние программы, CurseForge не даёт ссылку:
такие файлы лаунчер не обходит, а перечисляет, чтобы их скачали вручную.
"""

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError
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


def api_key() -> str:
    enc = AppConfig.load().curseforge_key_enc
    return TokenVault.decrypt(enc) if enc else ""


def available() -> bool:
    return bool(api_key())


def _client() -> httpx.Client:
    key = api_key()
    if not key:
        raise BadRequestError("Не указан ключ API CurseForge (Настройки → Источники сборок)")
    headers = {"x-api-key": key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    return httpx.Client(base_url=API, headers=headers, timeout=httpx.Timeout(30.0, connect=10.0),
                        follow_redirects=True)


def _check(resp: httpx.Response) -> Any:
    if resp.status_code == 403:
        raise BadRequestError("CurseForge отклонил ключ API — проверьте его в настройках")
    if resp.status_code >= 400:
        raise ExternalServiceError(f"CurseForge: HTTP {resp.status_code}")
    return resp.json().get("data")


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
