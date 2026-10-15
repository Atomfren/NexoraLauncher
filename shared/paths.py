"""Управление путями (shared).

Все пути вычисляются при каждом вызове, поэтому переменная окружения
``NEXORA_HOME`` (портативный режим / тесты) подхватывается без перезапуска.
"""

import os
import sys
from pathlib import Path

from shared.version import APP_ID


def get_app_name() -> str:
    """Возвращает техническое имя приложения."""
    return APP_ID


def _portable_home() -> Path | None:
    home = os.environ.get("NEXORA_HOME")
    return Path(home) if home else None


def get_config_dir() -> Path:
    """Директория конфигурации."""
    if home := _portable_home():
        return home / "config"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_ID


def get_data_dir() -> Path:
    """Директория данных (инстансы, версии Minecraft, логи)."""
    if home := _portable_home():
        return home / "data"
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_ID


def get_cache_dir() -> Path:
    """Директория кэша (скачанные архивы, временные файлы)."""
    if home := _portable_home():
        return home / "cache"
    if os.name == "nt":
        return get_data_dir() / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_ID
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP_ID


def get_instances_dir() -> Path:
    """Директория инстансов."""
    return get_data_dir() / "instances"


def get_minecraft_dir() -> Path:
    """Общая директория Minecraft: versions, libraries, assets, runtime.

    Игровые файлы каждого инстанса (моды, миры, настройки) лежат отдельно,
    в ``<instance>/.minecraft``.
    """
    return get_data_dir() / ".minecraft"


def get_logs_dir() -> Path:
    """Директория логов лаунчера."""
    return get_data_dir() / "logs"


def get_models_dir() -> Path:
    """Директория моделей локального AI (*.gguf)."""
    return get_data_dir() / "models"


def ensure_directories() -> None:
    """Создаёт все необходимые директории."""
    for dir_path in (
        get_config_dir(),
        get_data_dir(),
        get_cache_dir(),
        get_instances_dir(),
        get_minecraft_dir(),
        get_logs_dir(),
        get_models_dir(),
    ):
        dir_path.mkdir(parents=True, exist_ok=True)


def get_resources_dir() -> Path:
    """Директория ресурсов приложения (иконки, переводы)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "resources"
    return Path(__file__).resolve().parent.parent / "resources"
