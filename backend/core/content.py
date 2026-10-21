"""Контент инстанса: моды, ресурспаки, шейдеры (Modrinth) и миры."""

import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.errors import BadRequestError, ConflictError, NotFoundError
from backend.core.instance import Instance, InstanceManager
from backend.core.tasks import Task
from backend.services.modrinth_client import LOADER_FAMILIES, get_modrinth, pick_primary_file
from shared.fsutil import (
    UnsafePathError,
    atomic_write_json,
    dir_size,
    read_json,
    remove_tree,
    safe_extract_zip,
    safe_join,
    sanitize_name,
    validate_name,
)

# Тип контента Modrinth → папка внутри .minecraft
# plugin — плагины Paper/Purpur (только для выделенных серверов)
CONTENT_DIRS = {"mod": "mods", "resourcepack": "resourcepacks", "shader": "shaderpacks", "plugin": "plugins"}
_EXTENSIONS = (".jar", ".zip")
_DISABLED = ".disabled"
_meta_lock = threading.RLock()


def _check_type(content_type: str) -> str:
    if content_type not in CONTENT_DIRS:
        raise BadRequestError(f"Неизвестный тип контента: {content_type}")
    return CONTENT_DIRS[content_type]


def _content_file(instance: Instance, content_type: str, filename: str) -> Path:
    folder = instance.game_dir / _check_type(content_type)
    try:
        validate_name(filename, max_length=255)
        return safe_join(folder, filename)
    except UnsafePathError as e:
        raise BadRequestError(str(e)) from e


def compatible_loaders(instance: Instance, content_type: str) -> list[str] | None:
    """Какие «загрузчики» Modrinth подходят инстансу для данного типа контента."""
    if content_type == "mod":
        if not instance.is_modded:
            raise BadRequestError("Для модов нужен инстанс с загрузчиком (Fabric, Forge, Quilt, NeoForge)")
        return LOADER_FAMILIES.get(instance.mod_loader, [instance.mod_loader])
    if content_type == "plugin":
        if instance.mod_loader not in ("paper", "purpur"):
            raise BadRequestError("Плагины работают только на серверах Paper и Purpur")
        return LOADER_FAMILIES[instance.mod_loader]
    if content_type == "resourcepack":
        return ["minecraft"]
    return None  # шейдеры: iris / optifine / canvas — не фильтруем


class ContentManager:
    """Установка и управление контентом инстанса."""

    # --- Метаданные (какой файл из какого проекта Modrinth) -------------------
    @staticmethod
    def meta_path(instance: Instance) -> Path:
        return instance.path / "content.json"

    @staticmethod
    def load_meta(instance: Instance) -> dict[str, dict[str, Any]]:
        data = read_json(ContentManager.meta_path(instance), default={})
        return data if isinstance(data, dict) else {}

    @staticmethod
    def save_meta(instance: Instance, meta: dict[str, dict[str, Any]]) -> None:
        atomic_write_json(ContentManager.meta_path(instance), meta)

    # --- Список ----------------------------------------------------------------
    @staticmethod
    def list_installed(instance_name: str, content_type: str) -> list[dict[str, Any]]:
        instance = InstanceManager.get(instance_name)
        folder = instance.game_dir / _check_type(content_type)
        if not folder.exists():
            return []
        meta = ContentManager.load_meta(instance)
        items = []
        for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            enabled = not path.name.endswith(_DISABLED)
            base_name = path.name[: -len(_DISABLED)] if not enabled else path.name
            if path.is_dir() and content_type != "shader":
                continue
            if path.is_file() and not base_name.lower().endswith(_EXTENSIONS):
                continue
            info = meta.get(f"{content_type}/{base_name}", {})
            items.append({
                "filename": path.name,
                "name": info.get("title") or Path(base_name).stem,
                "enabled": enabled,
                "size": path.stat().st_size if path.is_file() else dir_size(path),
                "project_id": info.get("project_id", ""),
                "version_id": info.get("version_id", ""),
                "version_number": info.get("version_number", ""),
                "icon_url": info.get("icon_url", ""),
            })
        return items

    @staticmethod
    def set_enabled(instance_name: str, content_type: str, filename: str, enabled: bool) -> dict[str, Any]:
        instance = InstanceManager.get(instance_name)
        path = _content_file(instance, content_type, filename)
        if not path.exists():
            raise NotFoundError(f"Файл '{filename}' не найден")
        is_enabled = not path.name.endswith(_DISABLED)
        if enabled != is_enabled:
            new_name = path.name + _DISABLED if not enabled else path.name[: -len(_DISABLED)]
            target = path.with_name(new_name)
            if target.exists():
                raise ConflictError(f"Файл '{new_name}' уже существует")
            path.rename(target)
            path = target
        return {"filename": path.name, "enabled": enabled}

    @staticmethod
    def remove(instance_name: str, content_type: str, filename: str) -> None:
        instance = InstanceManager.get(instance_name)
        path = _content_file(instance, content_type, filename)
        if not path.exists():
            raise NotFoundError(f"Файл '{filename}' не найден")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        base_name = path.name[: -len(_DISABLED)] if path.name.endswith(_DISABLED) else path.name
        with _meta_lock:
            meta = ContentManager.load_meta(instance)
            if meta.pop(f"{content_type}/{base_name}", None) is not None:
                ContentManager.save_meta(instance, meta)

    @staticmethod
    def add_local_file(instance_name: str, content_type: str, source: Path) -> dict[str, Any]:
        """Копирует локальный файл (.jar/.zip) в папку контента инстанса."""
        instance = InstanceManager.get(instance_name)
        if not source.is_file() or not source.name.lower().endswith(_EXTENSIONS):
            raise BadRequestError("Нужен файл .jar или .zip")
        target = _content_file(instance, content_type, source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return {"filename": target.name}

    # --- Установка из Modrinth -----------------------------------------------------
    @staticmethod
    def _select_version(instance: Instance, content_type: str, project_id: str,
                        version_id: str | None) -> dict[str, Any]:
        modrinth = get_modrinth()
        if version_id:
            return modrinth.get_version(version_id)
        loaders = compatible_loaders(instance, content_type)
        versions = modrinth.get_project_versions(project_id, instance.version, loaders)
        if not versions and content_type != "mod":
            # Ресурспаки и шейдеры часто не указывают все версии игры
            versions = modrinth.get_project_versions(project_id, None, loaders)
        if not versions:
            raise NotFoundError(
                f"Нет версии, совместимой с {instance.mod_loader} {instance.version}"
            )
        releases = [v for v in versions if v.get("version_type") == "release"]
        return (releases or versions)[0]

    @staticmethod
    def install(instance_name: str, content_type: str, project_id: str,
                version_id: str | None = None, task: Task | None = None,
                with_dependencies: bool = True) -> list[dict[str, Any]]:
        """Устанавливает проект (и обязательные зависимости для модов). Возвращает установленное."""
        return ContentManager.install_into(InstanceManager.get(instance_name), content_type, project_id,
                                           version_id, task, with_dependencies)

    @staticmethod
    def install_into(target, content_type: str, project_id: str, version_id: str | None = None,
                     task: Task | None = None, with_dependencies: bool = True) -> list[dict[str, Any]]:
        """Установка в любую «цель» с полями name/path/game_dir/version/mod_loader/is_modded
        (инстанс или выделенный сервер)."""
        _check_type(content_type)
        installed: list[dict[str, Any]] = []
        visited: set[str] = set()
        ContentManager._install_one(target, content_type, project_id, version_id, task,
                                    with_dependencies and content_type in ("mod", "plugin"), visited, installed)
        return installed

    @staticmethod
    def _check_incompatible(instance: Instance, content_type: str, version: dict[str, Any], title: str) -> None:
        """Не даёт поставить мод, который автор пометил несовместимым с уже установленным."""
        installed = {info["project_id"]: info.get("title") or info["project_id"]
                     for key, info in ContentManager.load_meta(instance).items()
                     if key.startswith(f"{content_type}/") and info.get("project_id")
                     and info["project_id"] != version["project_id"]}
        for dep in version.get("dependencies") or []:
            other = dep.get("project_id")
            if dep.get("dependency_type") == "incompatible" and other in installed:
                raise ConflictError(f"«{title}» несовместим с установленным «{installed[other]}». "
                                    f"Удалите «{installed[other]}» или выберите другой мод.")

    @staticmethod
    def _install_one(instance: Instance, content_type: str, project_id: str, version_id: str | None,
                     task: Task | None, with_deps: bool, visited: set[str],
                     installed: list[dict[str, Any]]) -> None:
        if project_id in visited:
            return
        visited.add(project_id)
        modrinth = get_modrinth()
        version = ContentManager._select_version(instance, content_type, project_id, version_id)
        project_id = version["project_id"]
        visited.add(project_id)
        project = modrinth.get_project(project_id)
        title = project.get("title", project_id)
        ContentManager._check_incompatible(instance, content_type, version, title)
        if task:
            task.set_status(f"Загрузка {title}…")

        folder = instance.game_dir / CONTENT_DIRS[content_type]
        file_info = pick_primary_file(version)
        try:
            validate_name(file_info["filename"], max_length=255)
        except UnsafePathError as e:
            raise BadRequestError(f"Недопустимое имя файла от Modrinth: {e}") from e

        with _meta_lock:
            meta = ContentManager.load_meta(instance)
            # Удаляем старую версию того же проекта
            for key, info in list(meta.items()):
                if info.get("project_id") == project_id and key.startswith(f"{content_type}/"):
                    old_name = key.split("/", 1)[1]
                    if old_name != file_info["filename"]:
                        for candidate in (folder / old_name, folder / (old_name + _DISABLED)):
                            candidate.unlink(missing_ok=True)
                    meta.pop(key)

        modrinth.download_file(file_info, folder / file_info["filename"], task)
        with _meta_lock:
            meta = ContentManager.load_meta(instance)
            meta[f"{content_type}/{file_info['filename']}"] = {
                "project_id": project_id,
                "version_id": version["id"],
                "version_number": version.get("version_number", ""),
                "title": title,
                "icon_url": project.get("icon_url") or "",
                "installed_at": datetime.now().isoformat(timespec="seconds"),
            }
            ContentManager.save_meta(instance, meta)
        installed.append({"project_id": project_id, "title": title, "filename": file_info["filename"]})
        logger.info(f"Установлен {content_type} '{title}' в '{instance.name}'")

        if not with_deps:
            return
        installed_projects = {i.get("project_id") for i in ContentManager.load_meta(instance).values()}
        for dep in version.get("dependencies") or []:
            if dep.get("dependency_type") != "required":
                continue
            dep_project = dep.get("project_id")
            dep_version = dep.get("version_id")
            if not dep_project and dep_version:
                dep_project = modrinth.get_version(dep_version)["project_id"]
            if not dep_project or dep_project in installed_projects:
                continue
            try:
                ContentManager._install_one(instance, content_type, dep_project, dep_version, task,
                                            True, visited, installed)
            except NotFoundError as e:
                logger.warning(f"Зависимость {dep_project} не установлена: {e}")

    # --- Миры --------------------------------------------------------------------
    @staticmethod
    def _saves_dir(instance: Instance) -> Path:
        return instance.game_dir / "saves"

    @staticmethod
    def list_worlds(instance_name: str) -> list[dict[str, Any]]:
        instance = InstanceManager.get(instance_name)
        saves = ContentManager._saves_dir(instance)
        if not saves.exists():
            return []
        worlds = []
        for path in saves.iterdir():
            level = path / "level.dat"
            if not path.is_dir() or not level.exists():
                continue
            worlds.append({
                "name": path.name,
                "size": dir_size(path),
                "last_played": datetime.fromtimestamp(level.stat().st_mtime).isoformat(timespec="seconds"),
                "has_icon": (path / "icon.png").exists(),
                "path": str(path),
            })
        return sorted(worlds, key=lambda w: w["last_played"], reverse=True)

    @staticmethod
    def _world_path(instance: Instance, world: str) -> Path:
        try:
            validate_name(world, max_length=128)
            return safe_join(ContentManager._saves_dir(instance), world)
        except UnsafePathError as e:
            raise BadRequestError(str(e)) from e

    @staticmethod
    def delete_world(instance_name: str, world: str) -> None:
        instance = InstanceManager.get(instance_name)
        path = ContentManager._world_path(instance, world)
        if not (path / "level.dat").exists():
            raise NotFoundError(f"Мир '{world}' не найден")
        remove_tree(path)

    @staticmethod
    def export_world(instance_name: str, world: str, dest: Path) -> Path:
        instance = InstanceManager.get(instance_name)
        path = ContentManager._world_path(instance, world)
        if not (path / "level.dat").exists():
            raise NotFoundError(f"Мир '{world}' не найден")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in path.rglob("*"):
                if file.is_file() and file.name != "session.lock":
                    zf.write(file, Path(world) / file.relative_to(path))
        return dest

    @staticmethod
    def import_world(instance_name: str, archive: Path) -> dict[str, Any]:
        """Импортирует мир из .zip (level.dat может лежать в корне или во вложенной папке)."""
        instance = InstanceManager.get(instance_name)
        if not archive.is_file():
            raise BadRequestError(f"Файл не найден: {archive}")
        try:
            zf = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as e:
            raise BadRequestError("Файл не является zip-архивом") from e
        with zf:
            level_entries = [n for n in zf.namelist() if n.replace("\\", "/").endswith("level.dat")]
            if not level_entries:
                raise BadRequestError("В архиве нет мира (level.dat)")
            prefix = min(level_entries, key=len).replace("\\", "/")[: -len("level.dat")]
            base = prefix.rstrip("/").split("/")[-1] if prefix else archive.stem
            name = sanitize_name(base, fallback="World")
            saves = ContentManager._saves_dir(instance)
            candidate, i = name, 2
            while (saves / candidate).exists():
                candidate = f"{name} ({i})"
                i += 1
            safe_extract_zip(zf, saves / candidate, strip_prefix=prefix)
        return {"name": candidate}
