"""Импорт сборок из других лаунчеров: Prism Launcher, MultiMC, CurseForge.

Поддерживается:
- папка инстанса Prism/MultiMC (``instance.cfg`` + ``mmc-pack.json`` + ``.minecraft``/``minecraft``);
- архив экспорта Prism/MultiMC (.zip с теми же файлами);
- папка инстанса CurseForge App (``minecraftinstance.json``, файлы игры лежат рядом).

Файлы игры (моды, конфиги, миры, ресурспаки) копируются в новый инстанс NexoraLauncher,
а версия Minecraft и загрузчик устанавливаются заново — так сборка не зависит от
исходного лаунчера.
"""

import configparser
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.errors import BadRequestError
from backend.core.instance import Instance, InstanceManager, check_name
from backend.core.minecraft import MinecraftManager
from backend.core.tasks import Task
from shared.fsutil import safe_extract_zip, sanitize_name

# uid компонентов mmc-pack.json → загрузчик NexoraLauncher
_MMC_LOADERS = {
    "net.fabricmc.fabric-loader": "fabric",
    "org.quiltmc.quilt-loader": "quilt",
    "net.minecraftforge": "forge",
    "net.neoforged": "neoforge",
}
# Что не переносим: логи, кэши, служебные файлы других лаунчеров
_SKIP = {"logs", "crash-reports", ".cache", "natives", ".fabric", ".quilt", "minecraftinstance.json",
         "instance.cfg", "mmc-pack.json", "icon.png", ".curseclient", "profileImage"}


@dataclass
class ForeignInstance:
    source: str  # prism | multimc | curseforge
    name: str
    path: str
    game_dir: str
    version: str
    mod_loader: str = "vanilla"
    loader_version: str = ""
    max_memory: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_cfg(path: Path) -> dict[str, str]:
    """instance.cfg — INI без секции (MultiMC) или с секцией [General] (Prism)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.lstrip().startswith("["):
        text = "[General]\n" + text
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # type: ignore[assignment]
    try:
        parser.read_string(text)
    except configparser.Error:
        return {}
    return dict(parser["General"]) if parser.has_section("General") else {}


def _detect_mmc(folder: Path) -> ForeignInstance | None:
    pack, cfg = folder / "mmc-pack.json", folder / "instance.cfg"
    if not pack.is_file():
        return None
    try:
        components = json.loads(pack.read_text(encoding="utf-8")).get("components", [])
    except (OSError, json.JSONDecodeError):
        return None
    version, loader, loader_version = "", "vanilla", ""
    for component in components:
        uid = component.get("uid", "")
        if uid == "net.minecraft":
            version = component.get("version") or component.get("cachedVersion") or ""
        elif uid in _MMC_LOADERS:
            loader = _MMC_LOADERS[uid]
            loader_version = component.get("version") or component.get("cachedVersion") or ""
    if not version:
        return None
    settings = _read_cfg(cfg) if cfg.is_file() else {}
    game = next((folder / d for d in (".minecraft", "minecraft") if (folder / d).is_dir()), folder / ".minecraft")
    memory = 0
    if settings.get("OverrideMemory", "false").lower() == "true":
        try:
            memory = int(settings.get("MaxMemAlloc", "0"))
        except ValueError:
            memory = 0
    source = "prism" if "prism" in str(folder).lower() or "ManagedPack" in settings else "multimc"
    return ForeignInstance(source=source, name=settings.get("name") or folder.name, path=str(folder),
                           game_dir=str(game), version=version, mod_loader=loader,
                           loader_version=loader_version, max_memory=memory)


def _detect_curseforge(folder: Path) -> ForeignInstance | None:
    meta = folder / "minecraftinstance.json"
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    version = data.get("gameVersion") or ""
    if not version:
        return None
    loader, loader_version = "vanilla", ""
    base = (data.get("baseModLoader") or {}).get("name", "")  # «forge-47.2.0», «fabric-0.15.11-1.20.1»
    for key in ("neoforge", "forge", "fabric", "quilt"):
        if base.lower().startswith(key + "-"):
            loader = key
            loader_version = base[len(key) + 1:].removesuffix(f"-{version}")
            break
    memory = int(data.get("allocatedMemory") or 0) if data.get("isMemoryOverride") else 0
    return ForeignInstance(source="curseforge", name=data.get("name") or folder.name, path=str(folder),
                           game_dir=str(folder), version=version, mod_loader=loader,
                           loader_version=loader_version, max_memory=memory)


def detect(folder: Path) -> ForeignInstance | None:
    """Определяет, сборка ли это другого лаунчера."""
    if not folder.is_dir():
        return None
    return _detect_mmc(folder) or _detect_curseforge(folder)


def _known_roots() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    home = Path.home()
    roots = [appdata / "PrismLauncher" / "instances", appdata / "PolyMC" / "instances",
             home / "curseforge" / "minecraft" / "Instances",
             home / ".local" / "share" / "PrismLauncher" / "instances",
             home / "Library" / "Application Support" / "PrismLauncher" / "instances"]
    # Prism может хранить инстансы в другом месте — читаем его настройки
    cfg = appdata / "PrismLauncher" / "prismlauncher.cfg"
    if cfg.is_file():
        custom = _read_cfg(cfg).get("InstanceDir", "")
        if custom:
            path = Path(custom)
            roots.insert(0, path if path.is_absolute() else cfg.parent / path)
    return roots


def discover() -> list[dict[str, Any]]:
    """Сборки других лаунчеров, найденные на компьютере."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in _known_roots():
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            info = detect(folder)
            if info and info.path not in seen:
                seen.add(info.path)
                found.append(info.to_dict())
    return found


def _copy_game_files(source: Path, target: Path, task: Task | None) -> int:
    files = [p for p in source.rglob("*")
             if p.is_file() and not (_SKIP & set(p.relative_to(source).parts))]
    if task:
        task.set_status("Копирование файлов сборки…")
        task.set_max(max(1, len(files)))
    for i, file in enumerate(files):
        dest = target / file.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)
        if task:
            task.set_progress(i + 1)
    return len(files)


def import_folder(folder: Path, new_name: str = "", task: Task | None = None,
                  install: bool = True) -> Instance:
    info = detect(folder)
    if info is None:
        raise BadRequestError("Это не папка сборки Prism Launcher, MultiMC или CurseForge")
    name = new_name or InstanceManager.unique_name(sanitize_name(info.name))
    check_name(name)
    instance = InstanceManager.create(name, info.version, info.mod_loader, info.loader_version)
    try:
        if info.max_memory:
            instance = InstanceManager.update(name, max_memory=info.max_memory)
        count = _copy_game_files(Path(info.game_dir), instance.game_dir, task)
        if install:
            MinecraftManager().prepare_instance(instance, task)
    except Exception:
        shutil.rmtree(instance.path, ignore_errors=True)
        raise
    logger.info(f"Импорт из {info.source}: «{info.name}» → «{name}» ({count} файлов)")
    return Instance.load(name) or instance


def is_mmc_zip(zf: zipfile.ZipFile) -> bool:
    return any(n.replace("\\", "/").rsplit("/", 1)[-1] == "mmc-pack.json" and n.count("/") <= 1
               for n in zf.namelist())


def import_mmc_zip(path: Path, new_name: str = "", task: Task | None = None) -> Instance:
    """Архив экспорта Prism/MultiMC: распаковываем во временную папку и импортируем как папку."""
    with tempfile.TemporaryDirectory(prefix="nexora_import_") as tmp:
        if task:
            task.set_status("Распаковка архива…")
        with zipfile.ZipFile(path) as zf:
            packs = sorted((n for n in zf.namelist() if n.endswith("mmc-pack.json") and n.count("/") <= 1), key=len)
            prefix = packs[0][: -len("mmc-pack.json")]
            safe_extract_zip(zf, Path(tmp), strip_prefix=prefix)
        return import_folder(Path(tmp), new_name or "", task)
