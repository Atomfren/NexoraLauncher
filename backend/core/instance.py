"""Управление инстансами Minecraft.

Структура инстанса::

    <instances>/<name>/instance.json   — настройки
    <instances>/<name>/.minecraft/     — игровая папка (моды, миры, настройки игры)
    <instances>/<name>/logs/           — логи запусков из лаунчера

Версии, библиотеки, ассеты и Java-рантаймы общие: ``shared.paths.get_minecraft_dir()``.
"""

import shutil
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.errors import BadRequestError, ConflictError, NotFoundError
from shared.fsutil import UnsafePathError, atomic_write_json, read_json, safe_join, validate_name
from shared.paths import get_instances_dir

MOD_LOADERS = ("vanilla", "fabric", "quilt", "forge", "neoforge")

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
    def is_modded(self) -> bool:
        return self.mod_loader != "vanilla"

    def record_session(self, seconds: int) -> None:
        """Обновляет статистику после завершения игры."""
        with _lock:
            fresh = Instance.load(self.name) or self
            fresh.total_play_seconds += max(0, int(seconds))
            fresh.save()


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
    def create(name: str, version: str, mod_loader: str = "vanilla", loader_version: str = "") -> Instance:
        path = instance_path(name)
        with _lock:
            if path.exists():
                raise ConflictError(f"Инстанс '{name}' уже существует")
            instance = Instance(name=name, version=version, mod_loader=mod_loader,
                                loader_version=loader_version)
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
        copy.save()
        return copy

    @staticmethod
    def delete(name: str) -> None:
        path = instance_path(name)
        if not (path / "instance.json").exists():
            raise NotFoundError(f"Инстанс '{name}' не найден")
        shutil.rmtree(path)
        logger.info(f"Инстанс '{name}' удалён")

    @staticmethod
    def unique_name(base: str) -> str:
        """Подбирает свободное имя вида «Имя (2)»."""
        base = base.strip() or "Instance"
        name, i = base, 2
        while instance_path(name).exists():
            name = f"{base} ({i})"
            i += 1
        return name
