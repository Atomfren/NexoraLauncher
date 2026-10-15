"""«Машина времени»: снимки модов и настроек инстанса с откатом в один клик.

Снимок — zip в ``<instance>/snapshots`` с модами, конфигами, options.txt и
настройками инстанса. Миры не входят (для них есть отдельный экспорт).
Автоснимки создаются перед рискованными операциями (обновление модов, смена
версии, «Турбо», откат) и хранятся в ограниченном количестве.
"""

import shutil
import threading
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.errors import NotFoundError
from backend.core.instance import Instance, InstanceManager
from shared.fsutil import atomic_write_json, read_json, safe_extract_zip

# Что входит в снимок (пути относительно папки инстанса)
_DIRS = (".minecraft/mods", ".minecraft/config", ".minecraft/defaultconfigs", ".minecraft/kubejs")
_FILES = ("instance.json", "content.json", ".minecraft/options.txt")
_KEEP_AUTO = 10
# Поля instance.json, которые откатываются; статистика игры остаётся текущей
_RESTORED_FIELDS = ("version", "mod_loader", "loader_version", "launch_version_id", "java_path",
                    "max_memory", "min_memory", "jvm_args", "width", "height", "fullscreen")
_lock = threading.Lock()


def _dir(instance: Instance) -> Path:
    return instance.path / "snapshots"


def _index_path(instance: Instance) -> Path:
    return _dir(instance) / "index.json"


def _load_index(instance: Instance) -> list[dict[str, Any]]:
    data = read_json(_index_path(instance), default=[])
    return data if isinstance(data, list) else []


def _save_index(instance: Instance, items: list[dict[str, Any]]) -> None:
    atomic_write_json(_index_path(instance), items)


def create(instance_name: str, label: str = "", auto: bool = False) -> dict[str, Any]:
    instance = InstanceManager.get(instance_name)
    root = instance.path
    snap_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    folder = _dir(instance)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{snap_id}.zip"
    mods = 0
    with _lock, zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in _FILES:
            path = root / rel
            if path.is_file():
                zf.write(path, rel)
        for rel in _DIRS:
            base = root / rel
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(root).as_posix())
                    if rel.endswith("mods") and path.parent == base:
                        mods += 1
        item = {
            "id": snap_id,
            "label": label or ("Автоснимок" if auto else "Снимок"),
            "auto": auto,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "size": archive.stat().st_size,
            "mods": mods,
            "version": instance.version,
            "mod_loader": instance.mod_loader,
        }
        items = _load_index(instance)
        items.insert(0, item)
        # Ограничиваем число автоснимков
        autos = [i for i in items if i.get("auto")]
        for old in autos[_KEEP_AUTO:]:
            (folder / f"{old['id']}.zip").unlink(missing_ok=True)
            items.remove(old)
        _save_index(instance, items)
    logger.info(f"Снимок '{item['label']}' инстанса '{instance_name}' создан")
    return item


def list_snapshots(instance_name: str) -> list[dict[str, Any]]:
    instance = InstanceManager.get(instance_name)
    return [i for i in _load_index(instance) if (_dir(instance) / f"{i['id']}.zip").exists()]


def _find(instance: Instance, snap_id: str) -> tuple[dict[str, Any], Path]:
    for item in _load_index(instance):
        if item["id"] == snap_id:
            archive = _dir(instance) / f"{snap_id}.zip"
            if archive.exists():
                return item, archive
    raise NotFoundError("Снимок не найден")


def restore(instance_name: str, snap_id: str) -> dict[str, Any]:
    """Откатывает инстанс к снимку (текущее состояние сохраняется автоснимком)."""
    instance = InstanceManager.get(instance_name)
    item, archive = _find(instance, snap_id)
    create(instance_name, f"Перед откатом к «{item['label']}»", auto=True)
    root = instance.path
    current = instance.to_dict()
    with _lock:
        for rel in _DIRS:
            shutil.rmtree(root / rel, ignore_errors=True)
        for rel in _FILES[2:]:
            (root / rel).unlink(missing_ok=True)
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
            safe_extract_zip(zf, root)
        restored = Instance.load(instance_name) if "instance.json" in names else None
        merged = dict(current)
        if restored:
            snapshot_data = restored.to_dict()
            merged.update({k: snapshot_data[k] for k in _RESTORED_FIELDS})
        atomic_write_json(root / "instance.json", merged)
    # Индекс модов устарел
    (root / ".nexora_modindex.json").unlink(missing_ok=True)
    logger.info(f"Инстанс '{instance_name}' откатан к снимку {snap_id}")
    return item


def delete(instance_name: str, snap_id: str) -> None:
    instance = InstanceManager.get(instance_name)
    _, archive = _find(instance, snap_id)
    with _lock:
        archive.unlink(missing_ok=True)
        _save_index(instance, [i for i in _load_index(instance) if i["id"] != snap_id])

