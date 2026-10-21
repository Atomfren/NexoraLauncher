"""Управление инстансами Minecraft.

Структура инстанса::

    <instances>/<name>/instance.json   — настройки
    <instances>/<name>/.minecraft/     — игровая папка (моды, миры, настройки игры)
    <instances>/<name>/logs/           — логи запусков из лаунчера

Версии, библиотеки, ассеты и Java-рантаймы общие: ``shared.paths.get_minecraft_dir()``.
"""

import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.errors import BadRequestError, ConflictError, NotFoundError
from shared.fsutil import (
    UnsafePathError,
    atomic_write_json,
    processes_using,
    read_json,
    remove_tree,
    safe_join,
    validate_name,
)
from shared.paths import get_instances_dir

MOD_LOADERS = ("vanilla", "fabric", "quilt", "forge", "neoforge")
# Папка удаляемой сборки переименовывается так, пока не сотрётся полностью
_TRASH_PREFIX = ".deleting-"

_lock = threading.RLock()


def check_name(name: str) -> str:
    """Проверяет имя инстанса; при ошибке — 400."""
    try:
        return validate_name(name)
    except UnsafePathError as e:
        raise BadRequestError(str(e)) from e


def instance_path(name: str) -> Path:
    """Путь к папке инстанса с защитой от path traversal."""
    check_name(name)
    try:
        return safe_join(get_instances_dir(), name)
    except UnsafePathError as e:
        raise BadRequestError(str(e)) from e



def clean_title(title: str, folder: str) -> str:
    """Отображаемое имя: пусто, если совпадает с именем папки."""
    title = " ".join((title or "").split())[:64]
    return "" if title == folder else title


def folder_for_title(title: str, existing: set[str] | None = None) -> str:
    """Имя папки для произвольного названия: само название, если оно допустимо, иначе очищенное."""
    from shared.fsutil import sanitize_name
    title = " ".join((title or "").split())
    taken = {n.lower() for n in existing} if existing is not None else None
    try:
        base = validate_name(title)
    except UnsafePathError:
        base = sanitize_name(title, fallback="Instance")
    name, i = base, 2
    while (name.lower() in taken) if taken is not None else instance_path(name).exists():
        name = f"{base} ({i})"
        i += 1
    return name


@dataclass
class Instance:
    """Инстанс Minecraft."""

    name: str
    version: str
    mod_loader: str = "vanilla"
    loader_version: str = ""
    # ID установленной версии для запуска (например, fabric-loader-0.16.9-1.21.1)
    launch_version_id: str = ""
    # Переопределения глобальных настроек (0 / "" — использовать глобальные)
    java_path: str = ""
    max_memory: int = 0
    min_memory: int = 0
    jvm_args: str = ""
    width: int = 0
    height: int = 0
    fullscreen: bool = False
    # Установленный OptiFine (имя файла, например OptiFine_1.20.1_HD_U_I6.jar) — только Vanilla и Forge
    optifine: str = ""
    # Отображаемое имя, если оно не годится для папки (например, «Create: Above & Beyond»)
    title: str = ""
    created_at: str = ""
    last_played: str = ""
    play_count: int = 0
    total_play_seconds: int = 0

    def __post_init__(self) -> None:
        if self.mod_loader not in MOD_LOADERS:
            raise BadRequestError(f"Неизвестный загрузчик: {self.mod_loader}")
        self.created_at = self.created_at or datetime.now().isoformat(timespec="seconds")

    # --- Пути ---------------------------------------------------------------
    @property
    def path(self) -> Path:
        return instance_path(self.name)

    @property
    def game_dir(self) -> Path:
        return self.path / ".minecraft"

    @property
    def mods_dir(self) -> Path:
        return self.game_dir / "mods"

    @property
    def logs_dir(self) -> Path:
        return self.path / "logs"

    def ensure_dirs(self) -> None:
        self.game_dir.mkdir(parents=True, exist_ok=True)

    # --- Сериализация -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instance":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        with _lock:
            self.ensure_dirs()
            atomic_write_json(self.path / "instance.json", self.to_dict())

    @classmethod
    def load(cls, name: str) -> "Instance | None":
        config_path = instance_path(name) / "instance.json"
        data = read_json(config_path)
        if not isinstance(data, dict):
            return None
        data["name"] = name  # имя всегда совпадает с папкой
        try:
            return cls.from_dict(data)
        except (TypeError, BadRequestError) as e:
            logger.warning(f"Повреждённый instance.json в '{name}': {e}")
            return None

    @property
    def display_name(self) -> str:
        return self.title or self.name

    @property
    def is_modded(self) -> bool:
        return self.mod_loader != "vanilla"

    def record_session(self, seconds: int) -> None:
        """Обновляет статистику после завершения игры."""
        with _lock:
            fresh = Instance.load(self.name) or self
            fresh.total_play_seconds += max(0, int(seconds))
            fresh.save()


BACKGROUND_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
_BACKGROUND_MAX_BYTES = 40 * 1024 * 1024


def background_file(instance: "Instance") -> Path | None:
    """Своё фото на фоне сборки (лежит в папке сборки как background-<время>.<расширение>)."""
    try:
        files = [p for p in instance.path.glob("background-*") if p.suffix.lower() in BACKGROUND_EXTENSIONS]
    except OSError:
        return None
    return max(files, key=lambda p: p.name) if files else None


def set_background(name: str, source: Path) -> Path:
    """Копирует локальное фото в папку сборки и делает его фоном (старое удаляется)."""
    instance = InstanceManager.get(name)
    if source.suffix.lower() not in BACKGROUND_EXTENSIONS:
        raise BadRequestError("Выберите картинку: PNG, JPG, BMP, WEBP или GIF")
    if not source.is_file():
        raise BadRequestError(f"Файл не найден: {source}")
    if source.stat().st_size > _BACKGROUND_MAX_BYTES:
        raise BadRequestError("Картинка слишком большая (больше 40 МБ)")
    old = list(instance.path.glob("background-*"))
    target = instance.path / f"background-{datetime.now():%Y%m%d%H%M%S%f}{source.suffix.lower()}"
    shutil.copyfile(source, target)
    for path in old:
        path.unlink(missing_ok=True)
    return target


def clear_background(name: str) -> None:
    instance = InstanceManager.get(name)
    for path in instance.path.glob("background-*"):
        path.unlink(missing_ok=True)


class InstanceManager:
    """Операции над набором инстансов."""

    @staticmethod
    def list_instances() -> list[Instance]:
        root = get_instances_dir()
        if not root.exists():
            return []
        result = []
        for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_dir():
                continue
            try:
                instance = Instance.load(path.name)
            except BadRequestError:
                continue
            if instance:
                result.append(instance)
        return result

    @staticmethod
    def get(name: str) -> Instance:
        instance = Instance.load(name)
        if instance is None:
            raise NotFoundError(f"Инстанс '{name}' не найден")
        return instance

    @staticmethod
    def create(name: str, version: str, mod_loader: str = "vanilla", loader_version: str = "",
               title: str = "") -> Instance:
        path = instance_path(name)
        with _lock:
            if path.exists():
                raise ConflictError(f"Инстанс '{name}' уже существует")
            instance = Instance(name=name, version=version, mod_loader=mod_loader,
                                loader_version=loader_version, title=clean_title(title, name))
            instance.save()
        logger.info(f"Инстанс '{name}' создан ({mod_loader} {version})")
        return instance

    @staticmethod
    def update(name: str, **changes: Any) -> Instance:
        instance = InstanceManager.get(name)
        editable = {f.name for f in fields(Instance)} - {"name", "created_at", "play_count",
                                                          "total_play_seconds", "last_played"}
        loader_changed = game_changed = False
        for key, value in changes.items():
            if key in editable and value is not None:
                if key in ("version", "mod_loader", "loader_version") and getattr(instance, key) != value:
                    loader_changed = True
                    game_changed = game_changed or key != "loader_version"
                setattr(instance, key, value)
        if game_changed and instance.optifine and "optifine" not in changes:
            # OptiFine привязан к версии игры и загрузчику — после смены он не подходит
            logger.info(f"OptiFine снят с '{name}' после смены версии или загрузчика")
            instance.optifine = ""
            if instance.mods_dir.is_dir():
                for jar in instance.mods_dir.glob("*OptiFine_*.jar*"):
                    jar.unlink()
        if instance.mod_loader not in MOD_LOADERS:
            raise BadRequestError(f"Неизвестный загрузчик: {instance.mod_loader}")
        instance.title = clean_title(instance.title, instance.name)
        if loader_changed and "launch_version_id" not in changes:
            instance.launch_version_id = ""
        instance.save()
        return instance

    @staticmethod
    def rename(name: str, new_name: str) -> Instance:
        instance = InstanceManager.get(name)
        new_path = instance_path(new_name)
        with _lock:
            if new_path.exists() and new_path.resolve() != instance.path.resolve():
                raise ConflictError(f"Инстанс '{new_name}' уже существует")
            instance.path.rename(new_path)
        instance.name = new_name
        instance.title = ""  # имя папки теперь и есть название
        instance.save()
        return instance

    @staticmethod
    def duplicate(name: str, new_name: str) -> Instance:
        source = InstanceManager.get(name)
        target = instance_path(new_name)
        with _lock:
            if target.exists():
                raise ConflictError(f"Инстанс '{new_name}' уже существует")
            shutil.copytree(source.path, target, ignore=shutil.ignore_patterns("logs"))
        copy = InstanceManager.get(new_name)
        copy.created_at = datetime.now().isoformat(timespec="seconds")
        copy.play_count = 0
        copy.total_play_seconds = 0
        copy.last_played = ""
        if source.title:
            suffix = new_name[len(name):] if new_name.startswith(name) else ""
            copy.title = clean_title(source.title + suffix if suffix else "", new_name)
        copy.save()
        return copy

    @staticmethod
    def delete(name: str) -> None:
        """Удаляет сборку.

        Папка сначала переименовывается: на Windows это не получится, если её держит процесс
        (например, ещё работающая игра), — тогда сразу понятная ошибка, а сборка остаётся целой.
        Остатки, которые не удалось стереть сразу, дочищаются при следующем запуске.
        """
        path = instance_path(name)
        if not (path / "instance.json").exists():
            raise NotFoundError(f"Инстанс '{name}' не найден")
        trash = path.with_name(f"{_TRASH_PREFIX}{uuid.uuid4().hex[:8]}")
        for attempt in range(4):
            try:
                path.rename(trash)
                break
            except PermissionError as e:
                if attempt < 3:
                    time.sleep(0.3 * (attempt + 1))
                    continue
                holders = processes_using(path)
                if holders:
                    raise ConflictError(f"Сборку не удалить: её файлы заняты — {', '.join(holders)}. "
                                        "Закройте игру и попробуйте снова.") from e
                raise ConflictError("Сборку не удалить: файлы заняты другой программой "
                                    "(открыта папка в Проводнике, антивирус или игра). "
                                    "Закройте её и попробуйте снова.") from e
        try:
            remove_tree(trash)
        except OSError as e:
            logger.warning(f"Остатки сборки '{name}' будут удалены при следующем запуске: {e}")
        logger.info(f"Инстанс '{name}' удалён")

    @staticmethod
    def purge_leftovers() -> None:
        """Дочищает папки от прерванных удалений: корзину и папки без instance.json и без файлов."""
        root = get_instances_dir()
        if not root.is_dir():
            return
        for path in root.iterdir():
            if not path.is_dir():
                continue
            orphan = not (path / "instance.json").exists() and not any(p.is_file() for p in path.rglob("*"))
            if path.name.startswith(_TRASH_PREFIX) or orphan:
                try:
                    remove_tree(path, attempts=2)
                    logger.info(f"Удалены остатки: {path.name}")
                except OSError as e:
                    logger.debug(f"Остатки {path.name} пока заняты: {e}")

    @staticmethod
    def unique_name(base: str) -> str:
        """Подбирает свободное имя вида «Имя (2)»."""
        base = base.strip() or "Instance"
        name, i = base, 2
        while instance_path(name).exists():
            name = f"{base} ({i})"
            i += 1
        return name
