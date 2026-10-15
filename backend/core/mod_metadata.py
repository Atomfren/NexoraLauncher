"""Чтение метаданных модов прямо из jar (Fabric, Quilt, Forge, NeoForge).

Нужно, чтобы понимать, какой файл отвечает за mod id из лога вылета, и чтобы
показывать понятные имена даже для модов, добавленных вручную.
"""

import hashlib
import io
import json
import re
import threading
import tomllib
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger

from shared.fsutil import atomic_write_json, read_json

_DISABLED = ".disabled"
_cache_lock = threading.Lock()


@dataclass
class ModInfo:
    """Мод, найденный в папке mods."""

    filename: str
    enabled: bool
    ids: list[str] = field(default_factory=list)
    name: str = ""
    version: str = ""
    loader: str = ""  # fabric | quilt | forge | neoforge | unknown
    sha1: str = ""
    sha512: str = ""
    size: int = 0
    depends: list[str] = field(default_factory=list)
    # ID модов, вложенных в jar (jar-in-jar): считаются установленными
    bundled: list[str] = field(default_factory=list)
    broken: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def file_hashes(path: Path) -> tuple[str, str]:
    sha1, sha512 = hashlib.sha1(), hashlib.sha512()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            sha1.update(chunk)
            sha512.update(chunk)
    return sha1.hexdigest(), sha512.hexdigest()


def _manifest_version(zf: zipfile.ZipFile) -> str:
    try:
        text = zf.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except KeyError:
        return ""
    match = re.search(r"^Implementation-Version:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _read_fabric(zf: zipfile.ZipFile, info: ModInfo) -> bool:
    try:
        data = json.loads(zf.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
    except (KeyError, ValueError):
        return False
    info.loader = "fabric"
    info.ids = [data.get("id", "")]
    info.ids += [p if isinstance(p, str) else p.get("id", "") for p in data.get("provides", [])]
    info.name = data.get("name") or data.get("id", "")
    info.version = str(data.get("version", ""))
    info.depends = list((data.get("depends") or {}).keys())
    info.bundled = _nested_fabric_ids(zf, data.get("jars") or [])
    return True


def _nested_fabric_ids(zf: zipfile.ZipFile, jars: list, depth: int = 0) -> list[str]:
    """ID модов из вложенных jar (Fabric jar-in-jar), рекурсивно."""
    ids: list[str] = []
    if depth > 3:
        return ids
    for entry in jars:
        name = entry.get("file") if isinstance(entry, dict) else None
        if not name:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(zf.read(name))) as nested:
                data = json.loads(nested.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
                ids.append(data.get("id", ""))
                ids += [p if isinstance(p, str) else p.get("id", "") for p in data.get("provides", [])]
                ids += _nested_fabric_ids(nested, data.get("jars") or [], depth + 1)
        except (KeyError, ValueError, zipfile.BadZipFile):
            continue
    return [i for i in ids if i]


def _read_quilt(zf: zipfile.ZipFile, info: ModInfo) -> bool:
    try:
        data = json.loads(zf.read("quilt.mod.json").decode("utf-8", "replace"), strict=False)
    except (KeyError, ValueError):
        return False
    loader = data.get("quilt_loader", {})
    info.loader = "quilt"
    info.ids = [loader.get("id", "")]
    info.name = (loader.get("metadata") or {}).get("name") or loader.get("id", "")
    info.version = str(loader.get("version", ""))
    deps = loader.get("depends") or []
    info.depends = [d if isinstance(d, str) else d.get("id", "") for d in deps]
    return True


def _read_forge(zf: zipfile.ZipFile, info: ModInfo) -> bool:
    for entry, loader in (("META-INF/neoforge.mods.toml", "neoforge"), ("META-INF/mods.toml", "forge")):
        try:
            data = tomllib.loads(zf.read(entry).decode("utf-8", "replace"))
        except KeyError:
            continue
        except tomllib.TOMLDecodeError:
            return False
        mods = data.get("mods") or []
        if not mods:
            return False
        info.loader = loader
        info.ids = [m.get("modId", "") for m in mods]
        info.name = mods[0].get("displayName") or mods[0].get("modId", "")
        version = str(mods[0].get("version", ""))
        info.version = _manifest_version(zf) if "${" in version else version
        deps = data.get("dependencies") or {}
        for mod_id in info.ids:
            for dep in deps.get(mod_id, []) if isinstance(deps, dict) else []:
                mandatory = dep.get("mandatory", dep.get("type", "required") == "required")
                if mandatory and dep.get("modId") not in ("minecraft", "forge", "neoforge"):
                    info.depends.append(dep.get("modId", ""))
        return True
    return False


def read_mod(path: Path, with_hashes: bool = True) -> ModInfo:
    """Читает один jar. Ошибки не бросает — возвращает то, что удалось узнать."""
    enabled = not path.name.endswith(_DISABLED)
    info = ModInfo(filename=path.name, enabled=enabled, size=path.stat().st_size, loader="unknown")
    try:
        with zipfile.ZipFile(path) as zf:
            _read_fabric(zf, info) or _read_quilt(zf, info) or _read_forge(zf, info)
    except (zipfile.BadZipFile, OSError) as e:
        info.broken = True
        logger.debug(f"Не удалось прочитать {path.name}: {e}")
    info.ids = [i for i in info.ids if i]
    info.depends = [d for d in info.depends if d]
    if not info.name:
        info.name = Path(path.name.removesuffix(_DISABLED)).stem
    if with_hashes:
        info.sha1, info.sha512 = file_hashes(path)
    return info


def scan_mods(mods_dir: Path) -> list[ModInfo]:
    """Все моды папки (с кэшем по имени/размеру/дате, чтобы не перечитывать сотни jar)."""
    if not mods_dir.is_dir():
        return []
    cache_path = mods_dir.parent.parent / ".nexora_modindex.json"
    with _cache_lock:
        cache = read_json(cache_path, default={})
        if not isinstance(cache, dict):
            cache = {}
        result, fresh_cache = [], {}
        for path in sorted(mods_dir.iterdir(), key=lambda p: p.name.lower()):
            base = path.name.removesuffix(_DISABLED)
            if not path.is_file() or not base.lower().endswith(".jar"):
                continue
            stat = path.stat()
            key = f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}"
            cached = cache.get(key)
            if cached:
                info = ModInfo(**cached)
            else:
                info = read_mod(path)
            fresh_cache[key] = info.to_dict()
            result.append(info)
        if fresh_cache != cache:
            try:
                atomic_write_json(cache_path, fresh_cache)
            except OSError:
                pass
    return result


def find_by_mod_id(mods: list[ModInfo], mod_id: str) -> ModInfo | None:
    mod_id = mod_id.lower()
    return next((m for m in mods if mod_id in (i.lower() for i in m.ids)), None)


def provided_ids(mods: list[ModInfo]) -> set[str]:
    """Все ID, которые дают включённые моды (с учётом вложенных)."""
    ids: set[str] = set()
    for mod in mods:
        if mod.enabled:
            ids.update(i.lower() for i in mod.ids + mod.bundled)
    return ids
