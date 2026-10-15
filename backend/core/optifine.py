"""Поддержка OptiFine.

Автор OptiFine запрещает распространять файлы и прямые ссылки в обход страницы загрузки,
поэтому лаунчер:
1. показывает список версий с официальной страницы https://optifine.net/downloads;
2. открывает страницу загрузки нужной версии в браузере;
3. сам находит скачанный файл в папке «Загрузки» (или пользователь выбирает его вручную);
4. устанавливает его.

Установка зависит от загрузчика инстанса:
- Vanilla — как официальный установщик OptiFine: ``optifine.Patcher`` создаёт библиотеку
  OptiFine из ванильного клиента, рядом кладётся launchwrapper, а профиль версии
  ``<mc>-OptiFine_<редакция>`` наследует ванильный и запускается через
  ``net.minecraft.launchwrapper.Launch --tweakClass optifine.OptiFineTweaker``;
- Forge — OptiFine работает как обычный мод: jar кладётся в папку mods;
- Fabric / Quilt / NeoForge — OptiFine не поддерживается (для Fabric нужен OptiFabric,
  которого нет на Modrinth); вместо него лаунчер предлагает Sodium + Iris.
"""

import html
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError
from backend.core.instance import Instance, InstanceManager
from backend.core.tasks import Task
from shared.fsutil import atomic_write_json, read_json, validate_name
from shared.paths import get_data_dir, get_minecraft_dir
from shared.version import USER_AGENT

DOWNLOADS_PAGE = "https://optifine.net/downloads"
MIRROR_PAGE = "https://optifine.net/adloadx?f={filename}"
SUPPORTED_LOADERS = ("vanilla", "forge")
_CACHE_TTL = 3600
_PATCH_TIMEOUT = 300

_FILE_RE = re.compile(r"^(?P<preview>preview_)?OptiFine_(?P<mc>\d+(?:\.\d+)+)_(?P<edition>[A-Za-z0-9_]+)\.jar$")
_CLASS_VERSION_RE = re.compile(rb"OptiFine_(\d+(?:\.\d+)+)_([A-Z0-9]+_[A-Z0-9]+_[A-Z0-9]+(?:_pre\d+)?)")
_SECTION_RE = re.compile(r"<h2>Minecraft ([^<]+)</h2>(.*?)(?=<h2>Minecraft |\Z)", re.S)
_ROW_RE = re.compile(
    r"<tr class='downloadLine[^']*'>.*?colFile'>(?P<title>[^<]*)</td>.*?adloadx\?f=(?P<file>[^\"&]+)"
    r".*?colForge'>(?P<forge>[^<]*)</td>.*?colDate'>(?P<date>[^<]*)</td>", re.S)

_versions_cache: tuple[float, list[dict[str, Any]]] | None = None


# --- Список версий с optifine.net ------------------------------------------------------------
def parse_downloads_page(text: str) -> list[dict[str, Any]]:
    result = []
    for _section_title, body in _SECTION_RE.findall(text):
        for row in _ROW_RE.finditer(body):
            filename = html.unescape(row.group("file")).strip()
            match = _FILE_RE.match(filename)
            if not match:
                continue
            forge = row.group("forge").strip()
            result.append({
                "filename": filename,
                "mc_version": match.group("mc"),
                "edition": match.group("edition"),
                "title": html.unescape(row.group("title")).strip(),
                "preview": bool(match.group("preview")),
                "forge": forge.removeprefix("Forge ").strip() if forge.lower().startswith("forge") else "",
                "date": row.group("date").strip(),
                "page_url": MIRROR_PAGE.format(filename=filename),
            })
    return result


def list_versions(mc_version: str | None = None, force: bool = False) -> list[dict[str, Any]]:
    global _versions_cache
    if force or not _versions_cache or time.time() - _versions_cache[0] > _CACHE_TTL:
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
                resp = client.get(DOWNLOADS_PAGE)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            if _versions_cache:
                return _filter(_versions_cache[1], mc_version)
            raise ExternalServiceError(f"Сайт OptiFine недоступен: {e}") from e
        _versions_cache = (time.time(), parse_downloads_page(resp.text))
    return _filter(_versions_cache[1], mc_version)


def _filter(versions: list[dict[str, Any]], mc_version: str | None) -> list[dict[str, Any]]:
    return [v for v in versions if not mc_version or v["mc_version"] == mc_version]


# --- Файл OptiFine ------------------------------------------------------------------------------
def inspect_jar(path: Path) -> dict[str, Any]:
    """Проверяет, что это установщик OptiFine, и определяет версию игры и редакцию."""
    if not path.is_file():
        raise BadRequestError(f"Файл не найден: {path}")
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if not any(n.startswith(("optifine/", "net/optifine/")) for n in names):
                raise BadRequestError("Это не файл OptiFine")
            mc_version = edition = ""
            if match := _FILE_RE.match(path.name):
                mc_version, edition = match.group("mc"), match.group("edition")
            else:  # файл переименован — версия есть внутри класса Config
                for name in ("net/optifine/Config.class", "notch/net/optifine/Config.class",
                             "srg/net/optifine/Config.class", "Config.class"):
                    if name in names and (found := _CLASS_VERSION_RE.search(zf.read(name))):
                        mc_version, edition = found.group(1).decode(), found.group(2).decode()
                        break
            patcher = "optifine/Patcher.class" in names
    except zipfile.BadZipFile as e:
        raise BadRequestError("Файл OptiFine повреждён") from e
    if not mc_version:
        raise BadRequestError("Не удалось определить версию OptiFine")
    return {"path": str(path), "filename": f"OptiFine_{mc_version}_{edition}.jar", "mc_version": mc_version,
            "edition": edition, "size": path.stat().st_size, "patcher": patcher}


def downloads_dirs() -> list[Path]:
    home = Path.home()
    return [p for p in (home / "Downloads", home / "Загрузки") if p.is_dir()]


def find_downloaded(mc_version: str | None = None) -> list[dict[str, Any]]:
    """Файлы OptiFine в папке «Загрузки» (новые сверху)."""
    found = []
    for folder in downloads_dirs():
        for path in folder.glob("*OptiFine_*.jar"):
            match = _FILE_RE.match(path.name)
            if not match or (mc_version and match.group("mc") != mc_version):
                continue
            found.append({"path": str(path), "filename": path.name, "mc_version": match.group("mc"),
                          "edition": match.group("edition"), "size": path.stat().st_size,
                          "modified": path.stat().st_mtime})
    return sorted(found, key=lambda f: f["modified"], reverse=True)


def cache_dir() -> Path:
    return get_data_dir() / "optifine"


def _cached_jar(filename: str) -> Path:
    validate_name(filename, max_length=128)
    return cache_dir() / filename


# --- Установка -----------------------------------------------------------------------------------
def launch_id_for(mc_version: str, edition: str) -> str:
    return f"{mc_version}-OptiFine_{edition}"


def _mods_jars(instance: Instance) -> list[Path]:
    if not instance.mods_dir.is_dir():
        return []
    return [p for p in instance.mods_dir.iterdir() if p.is_file() and "OptiFine_" in p.name
            and p.name.removesuffix(".disabled").endswith(".jar")]


def install(name: str, source: Path, task: Task | None = None) -> dict[str, Any]:
    """Ставит OptiFine из скачанного файла в инстанс."""
    instance = InstanceManager.get(name)
    if instance.mod_loader not in SUPPORTED_LOADERS:
        raise BadRequestError(
            "OptiFine работает только на Vanilla и Forge. Для Fabric и Quilt поставьте Sodium + Iris — "
            "они быстрее и поддерживают шейдеры.")
    info = inspect_jar(source)
    if info["mc_version"] != instance.version:
        raise BadRequestError(f"Этот OptiFine для Minecraft {info['mc_version']}, "
                              f"а инстанс — {instance.version}")
    cached = _cached_jar(info["filename"])
    cached.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != cached.resolve():
        shutil.copy2(source, cached)
    instance = InstanceManager.update(name, optifine=info["filename"])
    if instance.mod_loader == "forge":
        _install_forge(instance, cached)
    else:
        install_vanilla(instance, task)
    logger.info(f"OptiFine {info['edition']} установлен в «{name}»")
    return {"filename": info["filename"], "edition": info["edition"]}


def _install_forge(instance: Instance, jar: Path) -> None:
    instance.mods_dir.mkdir(parents=True, exist_ok=True)
    for old in _mods_jars(instance):
        if old.name != jar.name:
            old.unlink()
    shutil.copy2(jar, instance.mods_dir / jar.name)


def ensure_installed(instance: Instance, task: Task | None = None) -> str | None:
    """Вызывается при подготовке инстанса. Возвращает ID версии для запуска (для Vanilla)."""
    if not instance.optifine:
        return None
    jar = _cached_jar(instance.optifine)
    if instance.mod_loader == "forge":
        if not any(p.name == jar.name for p in _mods_jars(instance)) and jar.exists():
            _install_forge(instance, jar)
        return None
    if instance.mod_loader != "vanilla":
        return None
    match = _FILE_RE.match(instance.optifine)
    launch_id = launch_id_for(match.group("mc"), match.group("edition")) if match else ""
    from backend.core.minecraft import MinecraftManager
    if launch_id and MinecraftManager().is_version_installed(launch_id) and _library_path(
            match.group("mc"), match.group("edition")).exists():
        return launch_id
    return install_vanilla(instance, task)


def _library_path(mc_version: str, edition: str) -> Path:
    version = f"{mc_version}_{edition}"
    return get_minecraft_dir() / "libraries" / "optifine" / "OptiFine" / version / f"OptiFine-{version}.jar"


def install_vanilla(instance: Instance, task: Task | None = None) -> str:
    """Делает то же, что официальный установщик OptiFine, но без окон."""
    from backend.core.minecraft import MinecraftManager

    jar = _cached_jar(instance.optifine)
    if not jar.exists():
        raise BadRequestError("Файл OptiFine не найден — установите OptiFine заново")
    info = inspect_jar(jar)
    mc_version, edition = info["mc_version"], info["edition"]
    mc = MinecraftManager()
    mc.install_version(mc_version, task)
    minecraft_dir = get_minecraft_dir()
    vanilla_jar = minecraft_dir / "versions" / mc_version / f"{mc_version}.jar"
    library = _library_path(mc_version, edition)
    library.parent.mkdir(parents=True, exist_ok=True)

    if task:
        task.set_status(f"Установка OptiFine {edition.replace('_', ' ')}…")
    if info["patcher"]:
        java = mc._ensure_runtime(mc_version, task) or "java"
        kwargs: dict[str, Any] = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            result = subprocess.run([java, "-cp", str(jar), "optifine.Patcher", str(vanilla_jar), str(jar),
                                     str(library)], capture_output=True, text=True, timeout=_PATCH_TIMEOUT,
                                    encoding="utf-8", errors="replace", **kwargs)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ExternalServiceError(f"Не удалось запустить установщик OptiFine: {e}") from e
        if result.returncode != 0 or not library.exists():
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            raise ExternalServiceError("Установщик OptiFine завершился с ошибкой: " + " | ".join(tail))
    else:  # очень старые версии — библиотекой служит сам файл
        shutil.copy2(jar, library)

    libraries = [{"name": f"optifine:OptiFine:{mc_version}_{edition}"}]
    with zipfile.ZipFile(jar) as zf:
        names = set(zf.namelist())
        if "launchwrapper-of.txt" in names:
            lw_version = zf.read("launchwrapper-of.txt").decode().strip()
            lw_target = minecraft_dir / "libraries" / "optifine" / "launchwrapper-of" / lw_version / \
                f"launchwrapper-of-{lw_version}.jar"
            lw_target.parent.mkdir(parents=True, exist_ok=True)
            lw_target.write_bytes(zf.read(f"launchwrapper-of-{lw_version}.jar"))
            libraries.append({"name": f"optifine:launchwrapper-of:{lw_version}"})
        elif "launchwrapper-2.0.jar" in names:
            lw_target = minecraft_dir / "libraries" / "optifine" / "launchwrapper" / "2.0" / "launchwrapper-2.0.jar"
            lw_target.parent.mkdir(parents=True, exist_ok=True)
            lw_target.write_bytes(zf.read("launchwrapper-2.0.jar"))
            libraries.append({"name": "optifine:launchwrapper:2.0"})
        else:
            libraries.append({"name": "net.minecraft:launchwrapper:1.12"})

    parent = read_json(minecraft_dir / "versions" / mc_version / f"{mc_version}.json") or {}
    launch_id = launch_id_for(mc_version, edition)
    profile: dict[str, Any] = {
        # jar — ванильный клиент берётся из родительской версии (как в профилях Forge)
        "id": launch_id, "inheritsFrom": mc_version, "jar": mc_version, "type": parent.get("type", "release"),
        "time": parent.get("time", ""), "releaseTime": parent.get("releaseTime", ""),
        "mainClass": "net.minecraft.launchwrapper.Launch", "libraries": libraries,
    }
    if "arguments" in parent:
        profile["arguments"] = {"game": ["--tweakClass", "optifine.OptiFineTweaker"]}
    else:
        profile["minecraftArguments"] = (parent.get("minecraftArguments", "") +
                                         " --tweakClass optifine.OptiFineTweaker").strip()
    atomic_write_json(minecraft_dir / "versions" / launch_id / f"{launch_id}.json", profile)

    fresh = Instance.load(instance.name) or instance
    fresh.launch_version_id = launch_id
    fresh.save()
    instance.launch_version_id = launch_id
    return launch_id


def remove(name: str) -> None:
    instance = InstanceManager.get(name)
    for jar in _mods_jars(instance):
        jar.unlink()
    InstanceManager.update(name, optifine="", launch_version_id="" if instance.mod_loader == "vanilla"
                           else instance.launch_version_id)


def status(name: str) -> dict[str, Any]:
    instance = InstanceManager.get(name)
    match = _FILE_RE.match(instance.optifine) if instance.optifine else None
    return {"installed": bool(instance.optifine), "filename": instance.optifine,
            "edition": match.group("edition") if match else "",
            "supported": instance.mod_loader in SUPPORTED_LOADERS, "mod_loader": instance.mod_loader,
            "mc_version": instance.version}
