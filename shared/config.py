"""Конфигурация приложения (shared)."""

import threading
from dataclasses import asdict, dataclass, fields
from typing import Any, Self

from shared.fsutil import atomic_write_json, read_json
from shared.paths import get_config_dir

SCHEMA_VERSION = 2

# Устаревшие ключи схемы v1, которые больше не используются
_LEGACY_KEYS = {"_ms_client_id", "_ms_refresh_token", "_curseforge_api_key", "color_theme",
                "window_width", "window_height", "jvm_profile", "last_username", "last_version"}

_lock = threading.Lock()


@dataclass
class AppConfig:
    """Глобальные настройки NexoraLauncher.

    Параметры инстанса (память, Java, разрешение) могут переопределять
    глобальные значения; 0 / пустая строка означает «как в настройках».
    """

    language: str = "ru"
    appearance_mode: str = "dark"
    java_path: str = ""
    max_memory: int = 4096
    min_memory: int = 512
    jvm_args: str = ""
    game_width: int = 1280
    game_height: int = 720
    fullscreen: bool = False
    # ID приложения Azure для входа через Microsoft (не секрет)
    ms_client_id: str = ""
    # Ключ API CurseForge (запасной путь для сборок CurseForge), зашифрован TokenVault
    curseforge_key_enc: str = ""
    last_instance: str = ""
    # Скрывать лаунчер после запуска игры
    hide_on_launch: bool = True
    # Проверять обновления лаунчера при запуске
    check_updates: bool = True
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Нормализует значения."""
        self.language = self.language if self.language in ("ru", "en") else "ru"
        self.appearance_mode = self.appearance_mode if self.appearance_mode in ("dark", "light") else "dark"
        self.max_memory = max(512, min(65536, int(self.max_memory)))
        self.min_memory = max(256, min(self.max_memory, int(self.min_memory)))
        self.game_width = max(320, min(7680, int(self.game_width)))
        self.game_height = max(240, min(4320, int(self.game_height)))
        self.java_path = (self.java_path or "").strip()
        self.jvm_args = (self.jvm_args or "").strip()
        self.ms_client_id = (self.ms_client_id or "").strip()

    @staticmethod
    def _path():
        return get_config_dir() / "config.json"

    @classmethod
    def _migrate(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Миграция старых схем конфигурации."""
        version = data.get("schema_version", data.get("_schema_version", 1))
        if version < 2:
            if "window_width" in data and "game_width" not in data:
                data["game_width"] = data["window_width"]
            if "window_height" in data and "game_height" not in data:
                data["game_height"] = data["window_height"]
            if data.get("ms_client_id", "").startswith("gAAAA"):
                data["ms_client_id"] = ""
        for key in _LEGACY_KEYS | {"_schema_version"}:
            data.pop(key, None)
        data["schema_version"] = SCHEMA_VERSION
        return data

    @classmethod
    def load(cls) -> Self:
        """Загружает конфигурацию (повреждённый файл → значения по умолчанию)."""
        with _lock:
            data = read_json(cls._path(), default=None)
        if not isinstance(data, dict):
            return cls()
        data = cls._migrate(data)
        known = {f.name for f in fields(cls)}
        try:
            return cls(**{k: v for k, v in data.items() if k in known})
        except (TypeError, ValueError):
            return cls()

    def save(self) -> None:
        """Атомарно сохраняет конфигурацию."""
        self.__post_init__()
        with _lock:
            atomic_write_json(self._path(), asdict(self))

    def update(self, **changes: Any) -> Self:
        """Применяет изменения (известные поля) и сохраняет."""
        known = {f.name for f in fields(self)} - {"schema_version"}
        for key, value in changes.items():
            if key in known and value is not None:
                setattr(self, key, value)
        self.save()
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
