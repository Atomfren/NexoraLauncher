"""Установка версий Minecraft / загрузчиков и сборка команды запуска."""

import shlex
import threading
import time
from pathlib import Path
from typing import Any

import minecraft_launcher_lib as mll
import requests
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from backend.core.instance import Instance
from backend.core.tasks import Task
from shared.config import AppConfig
from shared.fsutil import read_json
from shared.paths import get_minecraft_dir
from shared.version import APP_NAME, APP_VERSION

_VERSIONS_TTL = 600
_NETWORK_ATTEMPTS = 4
# Вывод игры в UTF-8 (иначе на Windows кириллица в логах превращается в «????»)
_UTF8_OUTPUT = ["-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
                "-Dsun.stdout.encoding=UTF-8", "-Dsun.stderr.encoding=UTF-8"]
_install_lock = threading.Lock()


def with_network_retries(fn, task: Task | None = None, what: str = "файлов игры"):
    """Повторяет установку при сетевых сбоях (уже скачанные файлы не перекачиваются)."""
    for attempt in range(1, _NETWORK_ATTEMPTS + 1):
        try:
            return fn()
        except (requests.exceptions.RequestException, ConnectionError, TimeoutError) as e:
            if attempt == _NETWORK_ATTEMPTS:
                raise ExternalServiceError(
                    f"Ошибка сети при загрузке {what}. Проверьте подключение и повторите попытку. ({e})"
                ) from e
            delay = 2 * attempt
            logger.warning(f"Сетевая ошибка (попытка {attempt}/{_NETWORK_ATTEMPTS}), повтор через {delay} с: {e}")
            if task:
                task.set_status(f"Сбой сети, повтор через {delay} с (попытка {attempt + 1})…")
            time.sleep(delay)


class MinecraftManager:
    """Работа с общей директорией Minecraft."""

    _versions_cache: tuple[float, list[dict[str, str]]] | None = None
    _loader_cache: dict[tuple[str, str, bool], tuple[float, list[str]]] = {}

    @property
    def minecraft_dir(self) -> Path:
        path = get_minecraft_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    # --- Списки версий -------------------------------------------------------
    def get_available_versions(self, force: bool = False) -> list[dict[str, str]]:
        cache = MinecraftManager._versions_cache
        if cache and not force and time.time() - cache[0] < _VERSIONS_TTL:
            return cache[1]
        try:
            raw = mll.utils.get_version_list()
        except Exception as e:  # noqa: BLE001 — сетевые ошибки requests/json
            if cache:
                return cache[1]
            raise ExternalServiceError(f"Не удалось получить список версий Mojang: {e}") from e
        versions = [
            {
                "id": v["id"],
                "type": v.get("type", "unknown"),
                "release_time": v["releaseTime"].isoformat() if v.get("releaseTime") else "",
            }
            for v in raw
        ]
        MinecraftManager._versions_cache = (time.time(), versions)
        return versions

    def latest_release(self) -> str:
        return next(v["id"] for v in self.get_available_versions() if v["type"] == "release")

    def get_installed_versions(self) -> list[dict[str, str]]:
        versions_dir = self.minecraft_dir / "versions"
        if not versions_dir.exists():
            return []
        result = []
        for path in sorted(versions_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            data = read_json(path / f"{path.name}.json")
            if not isinstance(data, dict) or not self.is_version_installed(path.name):
                continue
            result.append({
                "id": path.name,
                "type": data.get("type", "release"),
                "release_time": data.get("releaseTime", ""),
                "inherits_from": data.get("inheritsFrom", ""),
            })
        return result

    def is_version_installed(self, version_id: str) -> bool:
        """Версия считается установленной, если есть её json и jar базовой версии."""
        version_dir = self.minecraft_dir / "versions" / version_id
        data = read_json(version_dir / f"{version_id}.json")
        if not isinstance(data, dict):
            return False
        if parent := data.get("inheritsFrom"):
            return parent != version_id and self.is_version_installed(parent)
        return (version_dir / f"{version_id}.jar").exists()

    def get_loader_versions(self, loader: str, mc_version: str, stable_only: bool = True) -> list[str]:
        key = (loader, mc_version, stable_only)
        cached = MinecraftManager._loader_cache.get(key)
        if cached and time.time() - cached[0] < _VERSIONS_TTL:
            return cached[1]
        mod_loader = self._mod_loader(loader)
        try:
            if not mod_loader.is_minecraft_version_supported(mc_version):
                return []
            versions = list(mod_loader.get_loader_versions(mc_version, stable_only))
        except Exception as e:  # noqa: BLE001
            raise ExternalServiceError(f"Не удалось получить версии {loader}: {e}") from e
        MinecraftManager._loader_cache[key] = (time.time(), versions)
        return versions

    @staticmethod
    def _mod_loader(loader: str):
        try:
            return mll.mod_loader.get_mod_loader(loader)
        except Exception as e:  # noqa: BLE001
            raise BadRequestError(f"Неизвестный загрузчик: {loader}") from e

    # --- Установка -------------------------------------------------------------
    def _ensure_runtime(self, version_id: str, task: Task | None) -> str | None:
        """Гарантирует наличие Java-рантайма Mojang для версии; возвращает путь к java."""
        data = read_json(self.minecraft_dir / "versions" / version_id / f"{version_id}.json") or {}
        component = (data.get("javaVersion") or {}).get("component")
        if not component:
            return None
        exe = mll.runtime.get_executable_path(component, self.minecraft_dir)
        if exe is None:
            if task:
                task.set_status(f"Установка Java ({component})…")
            with_network_retries(lambda: mll.runtime.install_jvm_runtime(
                component, self.minecraft_dir, callback=task.callback_dict() if task else None
            ), task, "Java")
            exe = mll.runtime.get_executable_path(component, self.minecraft_dir)
        return exe

    def install_version(self, version_id: str, task: Task | None = None, force: bool = False) -> str:
        """Устанавливает ванильную версию (с ассетами, библиотеками и Java)."""
        with _install_lock:
            if force or not self.is_version_installed(version_id):
                logger.info(f"Установка Minecraft {version_id}")
                if task:
                    task.set_status(f"Установка Minecraft {version_id}…")
                try:
                    with_network_retries(lambda: mll.install.install_minecraft_version(
                        version_id, self.minecraft_dir, callback=task.callback_dict() if task else None
                    ), task)
                except mll.exceptions.VersionNotFound as e:
                    raise NotFoundError(f"Версия Minecraft '{version_id}' не найдена") from e
            self._ensure_runtime(version_id, task)
        return version_id

    def install_loader(self, loader: str, mc_version: str, loader_version: str = "",
                       task: Task | None = None) -> tuple[str, str]:
        """Устанавливает загрузчик модов. Возвращает (версия загрузчика, ID версии для запуска)."""
        mod_loader = self._mod_loader(loader)
        try:
            supported = mod_loader.is_minecraft_version_supported(mc_version)
        except Exception as e:  # noqa: BLE001
            raise ExternalServiceError(f"Сервис {mod_loader.get_name()} недоступен: {e}") from e
        if not supported:
            raise BadRequestError(f"{mod_loader.get_name()} не поддерживает Minecraft {mc_version}")
        if not loader_version:
            loader_version = mod_loader.get_latest_loader_version(mc_version)
        launch_id = mod_loader.get_installed_version(mc_version, loader_version)
        if self.is_version_installed(launch_id):
            self._ensure_runtime(launch_id, task)
            return loader_version, launch_id

        self.install_version(mc_version, task)
        java = self._ensure_runtime(mc_version, task) or None
        with _install_lock:
            logger.info(f"Установка {loader} {loader_version} для {mc_version}")
            if task:
                task.set_status(f"Установка {mod_loader.get_name()} {loader_version}…")
            launch_id = with_network_retries(lambda: mod_loader.install(
                mc_version, self.minecraft_dir, loader_version=loader_version,
                callback=task.callback_dict() if task else None, java=java,
            ), task, mod_loader.get_name())
        return loader_version, launch_id

    def prepare_instance(self, instance: Instance, task: Task | None = None, force: bool = False) -> str:
        """Устанавливает всё нужное для инстанса и возвращает ID версии для запуска."""
        from backend.core import optifine

        if not instance.is_modded:
            launch_id = self.install_version(instance.version, task, force=force)
            if instance.optifine:
                launch_id = optifine.ensure_installed(instance, task) or launch_id
        else:
            if (instance.launch_version_id and not force
                    and self.is_version_installed(instance.launch_version_id)):
                self._ensure_runtime(instance.launch_version_id, task)
                if instance.optifine:
                    optifine.ensure_installed(instance, task)
                return instance.launch_version_id
            if force:
                self.install_version(instance.version, task, force=True)
            loader_version, launch_id = self.install_loader(
                instance.mod_loader, instance.version, instance.loader_version, task
            )
            instance.loader_version = loader_version
            if instance.optifine:
                optifine.ensure_installed(instance, task)
        if instance.launch_version_id != launch_id:
            instance.launch_version_id = launch_id
            fresh = Instance.load(instance.name)
            if fresh:
                fresh.loader_version = instance.loader_version
                fresh.launch_version_id = launch_id
                fresh.save()
        return launch_id

    # --- Запуск -------------------------------------------------------------------
    def build_command(self, instance: Instance, launch_id: str, credentials: dict[str, str],
                      config: AppConfig, server: str = "", port: int = 25565) -> list[str]:
        """Собирает команду запуска с учётом настроек инстанса и глобальных."""
        max_mem = instance.max_memory or config.max_memory
        min_mem = min(instance.min_memory or config.min_memory, max_mem)
        jvm_args = [f"-Xmx{max_mem}M", f"-Xms{min_mem}M"] + _UTF8_OUTPUT
        extra = instance.jvm_args or config.jvm_args
        if extra:
            try:
                jvm_args += shlex.split(extra, posix=True)
            except ValueError as e:
                raise BadRequestError(f"Некорректные аргументы JVM: {e}") from e

        width = instance.width or config.game_width
        height = instance.height or config.game_height
        options: dict[str, Any] = {
            "username": credentials["username"],
            "uuid": credentials["uuid"],
            "token": credentials["token"],
            "launcherName": APP_NAME,
            "launcherVersion": APP_VERSION,
            "gameDirectory": str(instance.game_dir),
            "jvmArguments": jvm_args,
            "customResolution": True,
            "resolutionWidth": str(width),
            "resolutionHeight": str(height),
        }
        java_path = instance.java_path or config.java_path
        if java_path:
            if not Path(java_path).exists():
                raise BadRequestError(f"Java не найдена: {java_path}")
            options["executablePath"] = java_path
        if server:
            options["server"] = server
            options["port"] = str(port)
            options["quickPlayMultiplayer"] = f"{server}:{port}"

        try:
            command = mll.command.get_minecraft_command(launch_id, self.minecraft_dir, options)
        except mll.exceptions.VersionNotFound as e:
            raise NotFoundError(f"Версия '{launch_id}' не установлена") from e
        if instance.fullscreen or (config.fullscreen and not instance.width):
            command.append("--fullscreen")
        return command
