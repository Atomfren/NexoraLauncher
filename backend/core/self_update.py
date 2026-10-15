"""Автообновление лаунчера через GitHub Releases.

1. ``check()`` — сравнивает текущую версию с последним релизом репозитория;
2. ``download()`` — скачивает архив сборки ``NexoraLauncher-<версия>-windows-amd64.zip``
   и распаковывает его в ``<data>/updates/<версия>``;
3. ``apply()`` — запускает маленький bat-скрипт, который дожидается выхода лаунчера,
   копирует новые файлы поверх папки программы и запускает её снова.

Данные пользователя (инстансы, серверы, настройки) лежат в %LOCALAPPDATA% и %APPDATA%,
поэтому замена папки программы их не затрагивает. Обновление на месте возможно только
у собранного exe; при запуске из исходников предлагается открыть страницу релиза.
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from backend.core.minecraft import with_network_retries
from backend.core.tasks import Task
from shared.fsutil import safe_extract_zip
from shared.paths import get_data_dir
from shared.version import APP_NAME, APP_VERSION, USER_AGENT

GITHUB_REPO = "Atomfren/NexoraLauncher"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_ASSET_RE = re.compile(r"^NexoraLauncher-[\w.\-]+-windows-amd64\.zip$")
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(text or "")
    return tuple(int(x) for x in match.groups()) if match else None  # type: ignore[return-value]


def is_frozen() -> bool:
    """Запущена собранная программа (PyInstaller), а не исходники."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def updates_dir() -> Path:
    return get_data_dir() / "updates"


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
                        timeout=30, follow_redirects=True)


def check() -> dict[str, Any]:
    """Информация о последнем релизе и о том, новее ли он текущей версии."""
    try:
        with _client() as client:
            resp = client.get(RELEASES_API)
    except httpx.HTTPError as e:
        raise ExternalServiceError(f"GitHub недоступен: {e}") from e
    result: dict[str, Any] = {"current": APP_VERSION, "latest": APP_VERSION, "available": False,
                              "notes": "", "url": "", "asset_url": "", "size": 0, "can_install": False}
    if resp.status_code == 404:  # релизов ещё нет
        return result
    if resp.status_code != 200:
        raise ExternalServiceError(f"GitHub вернул HTTP {resp.status_code}")
    release = resp.json()
    latest = parse_version(release.get("tag_name", ""))
    current = parse_version(APP_VERSION)
    asset = next((a for a in release.get("assets", []) if _ASSET_RE.match(a.get("name", ""))), None)
    result.update({
        "latest": ".".join(map(str, latest)) if latest else release.get("tag_name", ""),
        "available": bool(latest and current and latest > current),
        "notes": (release.get("body") or "").strip()[:4000],
        "url": release.get("html_url", ""),
        "asset_url": asset["browser_download_url"] if asset else "",
        "size": asset.get("size", 0) if asset else 0,
    })
    result["can_install"] = bool(result["available"] and asset and can_self_update())
    return result


def download(task: Task | None = None) -> dict[str, Any]:
    """Скачивает и распаковывает новую версию. Возвращает путь к готовой папке."""
    info = check()
    if not info["available"]:
        raise BadRequestError("Установлена последняя версия")
    if not info["asset_url"]:
        raise NotFoundError("В релизе нет сборки для Windows")
    target = updates_dir() / info["latest"]
    archive = updates_dir() / f"{APP_NAME}-{info['latest']}.zip"
    updates_dir().mkdir(parents=True, exist_ok=True)

    def fetch() -> None:
        with _client() as client, client.stream("GET", info["asset_url"], timeout=120) as resp:
            if resp.status_code != 200:
                raise ExternalServiceError(f"Не удалось скачать обновление: HTTP {resp.status_code}")
            total = int(resp.headers.get("content-length") or info["size"] or 0)
            done = 0
            if task and total:
                task.set_max(total)
            partial = archive.with_suffix(".part")
            with open(partial, "wb") as file:
                for chunk in resp.iter_bytes(1 << 16):
                    file.write(chunk)
                    done += len(chunk)
                    if task:
                        task.check_cancelled()
                        if total:
                            task.set_progress(done)
            if info["size"] and done != info["size"]:
                partial.unlink(missing_ok=True)
                raise ExternalServiceError("Архив обновления скачан не полностью")
            partial.replace(archive)

    if task:
        task.set_status(f"Загрузка {APP_NAME} {info['latest']}…")
    try:
        with_network_retries(fetch, task, "обновления")
    except httpx.HTTPError as e:
        raise ExternalServiceError(f"Не удалось скачать обновление: {e}") from e

    if task:
        task.set_status("Распаковка…")
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as zf:
        safe_extract_zip(zf, target)
    archive.unlink(missing_ok=True)
    app_dir = next((p.parent for p in target.rglob(f"{APP_NAME}.exe")), None)
    if app_dir is None:
        shutil.rmtree(target, ignore_errors=True)
        raise ExternalServiceError(f"В архиве обновления нет {APP_NAME}.exe")
    logger.info(f"Обновление {info['latest']} готово к установке: {app_dir}")
    return {"version": info["latest"], "path": str(app_dir)}


def updater_script(source: Path, dest: Path, pid: int, cleanup: Path) -> str:
    """bat-скрипт: ждёт завершения лаунчера, копирует файлы и запускает новую версию."""
    exe = dest / f"{APP_NAME}.exe"
    # Полные пути: в PATH могут оказаться одноимённые утилиты (например, find/timeout из Git)
    sys32 = "%SystemRoot%\\System32"
    return "\r\n".join([
        "@echo off",
        f"{sys32}\\chcp.com 65001 >nul",
        ":wait",
        f'{sys32}\\tasklist.exe /FI "PID eq {pid}" /NH 2>nul | {sys32}\\find.exe " {pid} " >nul',
        f"if not errorlevel 1 ({sys32}\\PING.EXE -n 2 127.0.0.1 >nul & goto wait)",
        f'{sys32}\\Robocopy.exe "{source}" "{dest}" /E /R:5 /W:1 /NFL /NDL /NJH /NJS >nul',
        f'start "" "{exe}"',
        f'rmdir /S /Q "{cleanup}"',
        '(goto) 2>nul & del "%~f0"',
        "",
    ])


def can_self_update() -> bool:
    """Обновление на месте — только у собранной версии под Windows."""
    return is_frozen() and os.name == "nt"


def apply(prepared_path: str) -> dict[str, Any]:
    """Запускает установку подготовленного обновления. Лаунчер после этого нужно закрыть."""
    if not can_self_update():
        raise BadRequestError("Обновление на месте доступно только для собранной версии под Windows")
    source = Path(prepared_path).resolve()
    if updates_dir().resolve() not in source.parents or not (source / f"{APP_NAME}.exe").exists():
        raise BadRequestError("Обновление не найдено — скачайте его заново")
    script = updates_dir() / "apply_update.bat"
    version_dir = next(p for p in [source, *source.parents] if p.parent == updates_dir().resolve())
    script.write_text(updater_script(source, install_dir(), os.getpid(), version_dir), encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
    logger.info("Установщик обновления запущен, лаунчер закрывается")
    return {"restart": True}
