"""Автообновление лаунчера через собственный канал с подписанным манифестом.

1. ``check()`` — скачивает ``latest.json`` и ``latest.json.sig``, проверяет подпись Ed25519
   открытым ключом, вшитым в программу (``shared.version.UPDATE_PUBLIC_KEY``), и сравнивает версии;
2. ``download()`` — скачивает архив ``NexoraLauncher-<версия>-windows-amd64.zip``, считая SHA-256
   на лету, сверяет его и размер с манифестом и распаковывает в ``<data>/updates/<версия>``;
3. ``apply()`` — запускает маленький bat-скрипт, который дожидается выхода лаунчера,
   копирует новые файлы поверх папки программы и запускает её снова.

Доверие к обновлению держится на подписи: адрес канала и сам сайт могут быть подменены,
но без закрытого ключа выпускающего собрать принимаемый манифест нельзя. Архив проверяется
по SHA-256 из подписанного манифеста, поэтому подменить его отдельно тоже не выйдет.

Данные пользователя (инстансы, серверы, настройки) лежат в %LOCALAPPDATA% и %APPDATA%,
поэтому замена папки программы их не затрагивает. Обновление на месте возможно только
у собранного exe; при запуске из исходников предлагается открыть страницу релиза.
"""

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from backend.core.minecraft import with_network_retries
from backend.core.tasks import Task
from shared.fsutil import safe_extract_zip
from shared.paths import get_data_dir
from shared.version import APP_NAME, APP_VERSION, UPDATE_MANIFEST_URLS, UPDATE_PUBLIC_KEY, USER_AGENT

SIGNATURE_SUFFIX = ".sig"
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 64 * 1024


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
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)


def manifest_urls() -> list[str]:
    """Адреса манифеста по порядку. ``NEXORA_UPDATE_URL`` подменяет их (свой сервер, тесты)."""
    override = os.environ.get("NEXORA_UPDATE_URL", "").strip()
    return [override] if override else [url for url in UPDATE_MANIFEST_URLS if url]


def public_key() -> Ed25519PublicKey:
    """Открытый ключ канала обновлений."""
    try:
        raw = base64.b64decode(UPDATE_PUBLIC_KEY.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        raise BadRequestError("Открытый ключ канала обновлений повреждён") from e
    if len(raw) != 32:
        raise BadRequestError("Открытый ключ канала обновлений повреждён")
    return Ed25519PublicKey.from_public_bytes(raw)


def is_configured() -> bool:
    return bool(UPDATE_PUBLIC_KEY.strip())


def verify_signed(raw: bytes, signature: str) -> dict[str, Any]:
    """Проверяет подпись любого нашего файла с сайта и возвращает его содержимое.

    Этим же ключом подписаны манифест обновления и список языков: одна подпись — один источник
    доверия, и подменить любой из них, не имея закрытого ключа, нельзя.
    """
    try:
        signature_bytes = base64.b64decode(signature.strip(), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ExternalServiceError("Подпись обновления повреждена") from e
    try:
        public_key().verify(signature_bytes, raw)
    except InvalidSignature as e:
        raise ExternalServiceError("Подпись обновления не совпала — файл подменён или выпущен не нами") from e
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ExternalServiceError("Файл с сайта испорчен") from e
    if not isinstance(manifest, dict):
        raise ExternalServiceError("Файл с сайта испорчен")
    return manifest


def verify_manifest(raw: bytes, signature: str) -> dict[str, Any]:
    """Подписанный манифест обновления: в нём обязана быть версия."""
    manifest = verify_signed(raw, signature)
    if not parse_version(str(manifest.get("version", ""))):
        raise ExternalServiceError("В манифесте обновления нет версии")
    return manifest


def _fetch_manifest_from(client: httpx.Client, url: str) -> dict[str, Any]:
    """Скачивает манифест и его подпись с одного адреса и проверяет её."""
    raw = client.get(url)
    if raw.status_code != 200:
        raise ExternalServiceError(f"HTTP {raw.status_code}")
    if len(raw.content) > _MAX_MANIFEST_BYTES:
        raise ExternalServiceError("Манифест обновления подозрительно велик")
    signature = client.get(url + SIGNATURE_SUFFIX)
    if signature.status_code != 200:
        raise ExternalServiceError(f"нет подписи (HTTP {signature.status_code})")
    manifest = verify_manifest(raw.content, signature.text)
    manifest["_url"] = url
    return manifest


def fetch_manifest() -> dict[str, Any]:
    """Первый адрес, который ответил подписанным манифестом."""
    if not is_configured():
        raise BadRequestError("Канал обновлений не настроен: в сборке нет открытого ключа")
    errors: list[str] = []
    with _client() as client:
        for url in manifest_urls():
            try:
                return _fetch_manifest_from(client, url)
            except ExternalServiceError as e:
                errors.append(f"{url}: {e}")
                logger.debug(f"Канал обновлений недоступен — {url}: {e}")
            except httpx.HTTPError as e:
                errors.append(f"{url}: {e}")
                logger.debug(f"Канал обновлений недоступен — {url}: {e}")
    raise ExternalServiceError("Не удалось получить сведения об обновлении. " + "; ".join(errors))


def _archive_entry(manifest: dict[str, Any]) -> dict[str, Any]:
    entry = manifest.get("zip")
    if not isinstance(entry, dict) or not entry.get("file"):
        raise NotFoundError("В выпуске нет сборки для Windows")
    return entry


def _archive_url(manifest: dict[str, Any], entry: dict[str, Any]) -> str:
    """Адрес архива: либо абсолютный из манифеста, либо рядом с самим манифестом."""
    return entry.get("url") or urljoin(manifest["_url"], entry["file"])


def check() -> dict[str, Any]:
    """Сведения о последнем выпуске и о том, новее ли он текущей версии."""
    if not is_configured():
        logger.warning("Канал обновлений не настроен (UPDATE_PUBLIC_KEY пуст) — обновления не проверяются")
        raise BadRequestError("Канал обновлений не настроен: в сборке нет открытого ключа")
    result: dict[str, Any] = {"current": APP_VERSION, "latest": APP_VERSION, "available": False,
                              "notes": "", "url": "", "asset_url": "", "size": 0, "can_install": False,
                              "sha256": "", "channel": ""}
    manifest = fetch_manifest()
    latest = parse_version(str(manifest.get("version", "")))
    current = parse_version(APP_VERSION)
    entry = manifest.get("zip") if isinstance(manifest.get("zip"), dict) else {}
    result.update({
        "latest": ".".join(map(str, latest)) if latest else APP_VERSION,
        "available": bool(latest and current and latest > current),
        "notes": str(manifest.get("notes") or "").strip()[:4000],
        "url": str(manifest.get("page") or ""),
        "asset_url": _archive_url(manifest, entry) if entry.get("file") else "",
        "size": int(entry.get("size") or 0),
        "sha256": str(entry.get("sha256") or ""),
        "channel": manifest["_url"],
    })
    result["can_install"] = bool(result["available"] and result["asset_url"] and can_self_update())
    return result


def _download_archive(client: httpx.Client, url: str, target: Path, entry: dict[str, Any],
                      task: Task | None) -> None:
    """Скачивает архив во временный файл, считая SHA-256, и сверяет его с манифестом."""
    expected_hash = str(entry.get("sha256") or "").lower()
    expected_size = int(entry.get("size") or 0)
    if not _SHA256_RE.match(expected_hash):
        raise ExternalServiceError("В манифесте обновления нет SHA-256 архива")
    digest = hashlib.sha256()
    done = 0
    partial = target.with_suffix(".part")
    with client.stream("GET", url, timeout=120) as resp:
        if resp.status_code != 200:
            raise ExternalServiceError(f"Не удалось скачать обновление: HTTP {resp.status_code}")
        total = expected_size or int(resp.headers.get("content-length") or 0)
        if task and total:
            task.set_max(total)
        with open(partial, "wb") as file:
            for chunk in resp.iter_bytes(1 << 16):
                digest.update(chunk)
                file.write(chunk)
                done += len(chunk)
                if task:
                    task.check_cancelled()
                    if total:
                        task.set_progress(done)
    if expected_size and done != expected_size:
        partial.unlink(missing_ok=True)
        raise ExternalServiceError("Архив обновления скачан не полностью")
    if digest.hexdigest() != expected_hash:
        partial.unlink(missing_ok=True)
        raise ExternalServiceError("Контрольная сумма обновления не совпала — файл повреждён или подменён")
    partial.replace(target)


def download(task: Task | None = None) -> dict[str, Any]:
    """Скачивает, проверяет и распаковывает новую версию. Возвращает путь к готовой папке."""
    manifest = fetch_manifest()
    latest = parse_version(str(manifest.get("version", "")))
    current = parse_version(APP_VERSION)
    if not (latest and current and latest > current):
        raise BadRequestError("Установлена последняя версия")
    entry = _archive_entry(manifest)
    version = ".".join(map(str, latest))
    url = _archive_url(manifest, entry)

    updates_dir().mkdir(parents=True, exist_ok=True)
    target = updates_dir() / version
    archive = updates_dir() / f"{APP_NAME}-{version}.zip"
    if task:
        task.set_status(f"Загрузка {APP_NAME} {version}…")
    try:
        with _client() as client:
            with_network_retries(lambda: _download_archive(client, url, archive, entry, task), task, "обновления")
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
    logger.info(f"Обновление {version} проверено по подписи и SHA-256, готово к установке: {app_dir}")
    return {"version": version, "path": str(app_dir)}


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
