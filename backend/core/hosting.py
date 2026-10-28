"""Свой сервер без белого IP: выделенный сервер + публичный туннель e4mc.

Как это работает:
- ядро сервера на выбор: Fabric (моды), Vanilla, Paper или Purpur (плагины);
- на Fabric-сервер ставится мод e4mc: при старте он открывает исходящее соединение к
  ретранслятору e4mc и получает публичный домен вида ``xxx.e4mc.link`` —
  ни белый IP, ни проброс портов, ни аккаунт не нужны;
- лаунчер читает консоль сервера, находит строку ``Domain assigned: <домен>``
  и показывает адрес, который можно отправить друзьям;
- после каждой остановки мир сохраняется в резервную копию (``<data>/server-backups``),
  а при включённом расписании — ещё и раз в N часов, пока сервер работает;
- белый список и права оператора правятся из лаунчера: на запущенном сервере командой
  в консоль, на остановленном — прямо в ``whitelist.json`` и ``ops.json``.

Структура: ``<data>/servers/<имя>/`` — server.json (настройки лаунчера), ядро,
eula.txt, server.properties, mods/ или plugins/, world/ и т. д.
"""

import hashlib
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import minecraft_launcher_lib as mll
from loguru import logger

from backend.core.content import ContentManager
from backend.core.errors import BadRequestError, ConflictError, ExternalServiceError, NotFoundError
from backend.core.minecraft import with_network_retries
from backend.core.tasks import Task
from shared.fsutil import UnsafePathError, atomic_write_json, read_json, remove_tree, safe_join, validate_name
from shared.paths import get_data_dir, get_minecraft_dir
from shared.version import USER_AGENT

FABRIC_META = "https://meta.fabricmc.net/v2"
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_FILL = "https://fill.papermc.io/v3/projects/paper"
PURPUR_API = "https://api.purpurmc.org/v2/purpur"
MOJANG_PROFILE = "https://api.mojang.com/users/profiles/minecraft/"
SERVER_JAR = "fabric-server-launch.jar"
PLAIN_SERVER_JAR = "server.jar"
TUNNEL_MOD = "e4mc"
# Ядра сервера: fabric — моды (и туннель e4mc), paper/purpur — плагины, vanilla — без модификаций
CORES = ("fabric", "vanilla", "paper", "purpur")
_LOG_LINES = 3000
_STOP_TIMEOUT = 45
_SAVE_TIMEOUT = 30
BACKUP_FILES = ("server.properties", "whitelist.json", "ops.json", "banned-players.json", "banned-ips.json")
# Шаг расписания бэкапов: интервал задаётся в часах, проверка — раз в минуту.
# В тестах оба значения уменьшаются, чтобы не ждать настоящий час.
BACKUP_INTERVAL_SECONDS = 3600
BACKUP_TICK_SECONDS = 60
OP_LEVEL = 4  # уровень прав оператора по умолчанию (как в самом Minecraft)

_DOMAIN_RE = re.compile(r"Domain assigned: (?P<domain>[\w.\-]+)")
_DONE_RE = re.compile(r"\]: Done \(\d")
_SAVED_RE = re.compile(r"Saved the game|All dimensions are saved")
_JOIN_RE = re.compile(r"\]: (?P<name>\w{2,16}) joined the game")
_LEAVE_RE = re.compile(r"\]: (?P<name>\w{2,16}) left the game")
_NICK_RE = re.compile(r"^\w{3,16}$")

# Разбор строки консоли сервера — тем же подходом, что и логи игры в log_analyzer:
# [12:00:00] [Server thread/INFO]: сообщение
_CONSOLE_RE = re.compile(
    r"^\[(?P<time>[^\]]{1,40})\] \[(?P<thread>.+?)/(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]"
    r"(?: \[(?P<logger>[^\]]*)\]| \((?P<logger2>[^)]*)\))?:? ?(?P<msg>.*)$")
_CONSOLE_LEVELS = {"WARNING": "WARN", "FATAL": "ERROR", "TRACE": "DEBUG"}
# Строки стек-трейса и имена исключений: уровня у них нет, но это тоже ошибка
_TRACE_RE = re.compile(r"^(?:\s+at |\s*\.\.\. \d+ more|Caused by:|\s+Suppressed:|\t)")
_EXCEPTION_RE = re.compile(r"^(?:[a-z][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable)\b")

DEFAULT_PROPERTIES = {
    "motd": "Сервер на NexoraLauncher",
    "max-players": "10",
    "difficulty": "normal",
    "gamemode": "survival",
    "pvp": "true",
    "online-mode": "false",
    "white-list": "false",
    "enforce-whitelist": "false",
    "view-distance": "10",
    "simulation-distance": "10",
    "spawn-protection": "0",
    "allow-flight": "true",
    "level-seed": "",
    "hardcore": "false",
}
# Свойства, которые можно менять из лаунчера
EDITABLE_PROPERTIES = set(DEFAULT_PROPERTIES) | {"level-name", "enable-command-block", "allow-nether"}


def servers_dir() -> Path:
    return get_data_dir() / "servers"


def backups_dir() -> Path:
    return get_data_dir() / "server-backups"


def _server_path(name: str) -> Path:
    try:
        validate_name(name)
        return safe_join(servers_dir(), name)
    except UnsafePathError as e:
        raise BadRequestError(str(e)) from e


def _free_port(start: int = 25565) -> int:
    used = {s.port for s in HostingManager.all_servers()}
    for port in range(start, start + 200):
        if port in used:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise ConflictError("Нет свободного порта для сервера")


def _lan_ip() -> str:
    """Адрес компьютера в локальной сети.

    Адреса виртуальных адаптеров VPN/прокси (198.18.0.0/15, link-local) пропускаются —
    по ним друзья в той же сети не подключатся.
    """
    import ipaddress

    candidates: list[str] = []
    try:
        candidates += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            candidates.append(sock.getsockname()[0])
    except OSError:
        pass
    benchmark = ipaddress.ip_network("198.18.0.0/15")
    for value in candidates:
        ip = ipaddress.ip_address(value)
        if ip.is_private and not ip.is_loopback and not ip.is_link_local and ip not in benchmark:
            return value
    return "127.0.0.1"


def read_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    return result


def write_properties(path: Path, values: dict[str, str]) -> None:
    lines = ["# Minecraft server properties (NexoraLauncher)"]
    lines += [f"{k}={v}" for k, v in sorted(values.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class HostedServer:
    """Выделенный сервер."""

    name: str
    version: str
    core: str = "fabric"
    loader_version: str = ""  # версия Fabric или номер сборки Paper/Purpur
    max_memory: int = 3072
    port: int = 25565
    tunnel: bool = True
    eula_accepted: bool = False
    java_component: str = ""
    jvm_args: str = ""
    created_at: str = ""
    installed: bool = False
    auto_backup: bool = True
    backups_keep: int = 5
    backup_interval_hours: int = 0  # 0 — бэкапы по расписанию выключены

    # --- Совместимость с ContentManager.install_into -----------------------------
    @property
    def mod_loader(self) -> str:
        return self.core

    @property
    def is_modded(self) -> bool:
        return self.core == "fabric"

    @property
    def path(self) -> Path:
        return _server_path(self.name)

    @property
    def game_dir(self) -> Path:
        return self.path

    @property
    def mods_dir(self) -> Path:
        return self.path / "mods"

    # --- Особенности ядра --------------------------------------------------------------
    @property
    def jar_name(self) -> str:
        return SERVER_JAR if self.core == "fabric" else PLAIN_SERVER_JAR

    @property
    def content_type(self) -> str | None:
        """Что можно ставить на сервер: моды (Fabric), плагины (Paper/Purpur) или ничего."""
        return {"fabric": "mod", "paper": "plugin", "purpur": "plugin"}.get(self.core)

    @property
    def content_dir(self) -> Path:
        return self.path / ("plugins" if self.content_type == "plugin" else "mods")

    @property
    def tunnel_supported(self) -> bool:
        """Туннель e4mc — это мод, поэтому работает только на Fabric."""
        return self.core == "fabric"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "content_type": self.content_type, "tunnel_supported": self.tunnel_supported}

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path / "server.json", asdict(self))

    @classmethod
    def load(cls, name: str) -> "HostedServer | None":
        data = read_json(_server_path(name) / "server.json")
        if not isinstance(data, dict):
            return None
        known = {f.name for f in fields(cls)}
        data["name"] = name
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ServerRuntime:
    """Запущенный процесс сервера."""

    process: subprocess.Popen
    started_at: float
    log_path: Path
    state: str = "starting"  # starting | running | stopping | stopped | crashed
    address: str = ""
    players: set[str] = field(default_factory=set)
    lines: deque = field(default_factory=lambda: deque(maxlen=_LOG_LINES))
    exit_code: int | None = None
    saved: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)  # поток консоли завершён (и бэкап)
    backup_stop: threading.Event = field(default_factory=threading.Event)  # сигнал расписанию бэкапов


class HostingManager:
    """Создание и управление выделенными серверами."""

    _runtimes: dict[str, ServerRuntime] = {}
    _lock = threading.RLock()
    _java_cache: dict[str, str] = {}

    # --- Список / создание ----------------------------------------------------------
    @staticmethod
    def all_servers() -> list[HostedServer]:
        root = servers_dir()
        if not root.exists():
            return []
        result = []
        for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if path.is_dir():
                try:
                    server = HostedServer.load(path.name)
                except BadRequestError:
                    continue
                if server:
                    result.append(server)
        return result

    @staticmethod
    def get(name: str) -> HostedServer:
        server = HostedServer.load(name)
        if server is None:
            raise NotFoundError(f"Сервер «{name}» не найден")
        return server

    @staticmethod
    def create(name: str, version: str, max_memory: int = 3072, core: str = "fabric") -> HostedServer:
        if core not in CORES:
            raise BadRequestError(f"Неизвестное ядро сервера: {core}")
        path = _server_path(name)
        if path.exists():
            raise ConflictError(f"Сервер «{name}» уже существует")
        server = HostedServer(name=name, version=version, core=core, max_memory=max_memory, port=_free_port(),
                              tunnel=core == "fabric", created_at=datetime.now().isoformat(timespec="seconds"))
        server.save()
        properties = dict(DEFAULT_PROPERTIES)
        properties["server-port"] = str(server.port)
        properties["motd"] = f"{name} — NexoraLauncher"
        write_properties(path / "server.properties", properties)
        return server

    @staticmethod
    def _version_data(version: str) -> dict[str, Any]:
        """JSON версии Minecraft из манифеста Mojang (Java, ссылка на ванильный сервер)."""
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
            try:
                manifest = client.get(MOJANG_MANIFEST).json()
                entry = next((v for v in manifest["versions"] if v["id"] == version), None)
                if entry is None:
                    raise NotFoundError(f"Версия Minecraft «{version}» не найдена")
                return client.get(entry["url"]).json()
            except httpx.HTTPError as e:
                raise ExternalServiceError(f"Mojang недоступен: {e}") from e

    @staticmethod
    def _java_component(version: str) -> str:
        data = HostingManager._version_data(version)
        return (data.get("javaVersion") or {}).get("component", "jre-legacy")

    @staticmethod
    def _http_get(url: str) -> httpx.Response:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True) as client:
            return client.get(url)

    @staticmethod
    def _resolve_jar(server: HostedServer) -> tuple[str, str]:
        """(ссылка на ядро, версия загрузчика/сборки) для выбранного ядра."""
        core, version = server.core, server.version
        if core == "fabric":
            loader = mll.mod_loader.get_mod_loader("fabric")
            if not loader.is_minecraft_version_supported(version):
                raise BadRequestError(f"Fabric не поддерживает Minecraft {version}")
            loader_version = server.loader_version or loader.get_latest_loader_version(version)
            installer = mll.fabric.get_latest_installer_version()
            return f"{FABRIC_META}/versions/loader/{version}/{loader_version}/{installer}/server/jar", loader_version
        if core == "vanilla":
            download = (HostingManager._version_data(version).get("downloads") or {}).get("server")
            if not download:
                raise BadRequestError(f"У Minecraft {version} нет официального сервера")
            return download["url"], ""
        try:
            if core == "paper":
                resp = HostingManager._http_get(f"{PAPER_FILL}/versions/{version}/builds/latest")
                if resp.status_code == 404:
                    raise BadRequestError(f"Paper не поддерживает Minecraft {version}")
                resp.raise_for_status()
                build = resp.json()
                return build["downloads"]["server:default"]["url"], str(build["id"])
            # purpur
            resp = HostingManager._http_get(f"{PURPUR_API}/{version}/latest")
            if resp.status_code == 404:
                raise BadRequestError(f"Purpur не поддерживает Minecraft {version}")
            resp.raise_for_status()
            build = str(resp.json().get("build", "latest"))
            return f"{PURPUR_API}/{version}/{build}/download", build
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ExternalServiceError(f"Не удалось найти сборку {core.title()} для {version}: {e}") from e

    @staticmethod
    def install(name: str, task: Task | None = None) -> HostedServer:
        """Скачивает ядро сервера, Java и (для Fabric) мод-туннель e4mc."""
        server = HostingManager.get(name)
        title = server.core.title()
        if task:
            task.set_status(f"Загрузка ядра сервера {title}…")
        url, loader_version = HostingManager._resolve_jar(server)

        def download_jar() -> None:
            resp = HostingManager._http_get(url)
            if resp.status_code != 200:
                raise ExternalServiceError(f"Не удалось скачать ядро {title}: HTTP {resp.status_code}")
            (server.path / server.jar_name).write_bytes(resp.content)

        try:
            with_network_retries(download_jar, task, "ядра сервера")
        except httpx.HTTPError as e:
            raise ExternalServiceError(f"Не удалось скачать ядро {title}: {e}") from e
        server.loader_version = loader_version

        if task:
            task.set_status("Установка Java…")
        component = HostingManager._java_component(server.version)
        if mll.runtime.get_executable_path(component, get_minecraft_dir()) is None:
            with_network_retries(lambda: mll.runtime.install_jvm_runtime(
                component, get_minecraft_dir(), callback=task.callback_dict() if task else None), task, "Java")
        server.java_component = component

        if server.tunnel_supported:
            if task:
                task.set_status("Установка туннеля e4mc…")
            ContentManager.install_into(server, "mod", TUNNEL_MOD, task=task)
        server.installed = True
        server.save()
        logger.info(f"Сервер «{name}» установлен: {title} {loader_version}, Java {component}")
        return server

    @staticmethod
    def update(name: str, **changes: Any) -> HostedServer:
        server = HostingManager.get(name)
        for key in ("max_memory", "tunnel", "jvm_args", "auto_backup", "backups_keep", "backup_interval_hours"):
            if key in changes and changes[key] is not None:
                setattr(server, key, changes[key])
        if changes.get("eula_accepted"):
            server.eula_accepted = True
        server.save()
        return server

    @staticmethod
    def delete(name: str) -> None:
        if HostingManager.runtime(name):
            raise ConflictError("Сначала остановите сервер")
        server = HostingManager.get(name)
        remove_tree(server.path)

    # --- server.properties ----------------------------------------------------------------
    @staticmethod
    def properties(name: str) -> dict[str, str]:
        return read_properties(HostingManager.get(name).path / "server.properties")

    @staticmethod
    def update_properties(name: str, changes: dict[str, Any]) -> dict[str, str]:
        server = HostingManager.get(name)
        unknown = set(changes) - EDITABLE_PROPERTIES
        if unknown:
            raise BadRequestError(f"Нельзя изменить: {', '.join(sorted(unknown))}")
        # Параллельные PATCH не должны затирать изменения друг друга
        with HostingManager._lock:
            values = read_properties(server.path / "server.properties")
            for key, value in changes.items():
                value = str(value).lower() if isinstance(value, bool) else str(value)
                if "\n" in value or "\r" in value:
                    raise BadRequestError("Недопустимое значение")
                values[key] = value
            values["server-port"] = str(server.port)
            write_properties(server.path / "server.properties", values)
        return values

    # --- Запуск / остановка -------------------------------------------------------------
    @staticmethod
    def runtime(name: str) -> ServerRuntime | None:
        runtime = HostingManager._runtimes.get(name)
        return runtime if runtime and runtime.exit_code is None else None

    @staticmethod
    def start(name: str) -> dict[str, Any]:
        server = HostingManager.get(name)
        if not server.installed or not (server.path / server.jar_name).exists():
            raise BadRequestError("Сервер ещё не установлен")
        if not server.eula_accepted:
            raise BadRequestError("Нужно принять лицензионное соглашение Minecraft (EULA)")
        with HostingManager._lock:
            if HostingManager.runtime(name):
                raise ConflictError("Сервер уже запущен")
            java = mll.runtime.get_executable_path(server.java_component, get_minecraft_dir())
            if not java:
                raise BadRequestError("Java для сервера не установлена — переустановите сервер")
            (server.path / "eula.txt").write_text("# Принято в NexoraLauncher\neula=true\n", encoding="utf-8")
            has_tunnel = server.tunnel_supported and server.mods_dir.exists()
            tunnel_files = list(server.mods_dir.glob("e4mc*.jar*")) if has_tunnel else []
            for path in tunnel_files:  # включаем/выключаем туннель по настройке
                enabled_name = path.name.removesuffix(".disabled")
                target = path.with_name(enabled_name if server.tunnel else enabled_name + ".disabled")
                if target != path:
                    path.rename(target)
            command = HostingManager.build_command(server, java)
            logs_dir = server.path / "nexora-logs"
            logs_dir.mkdir(exist_ok=True)
            kwargs: dict[str, Any] = {}
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                command, cwd=str(server.path), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs,
            )
            runtime = ServerRuntime(process=process, started_at=time.time(),
                                    log_path=logs_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log")
            HostingManager._runtimes[name] = runtime
        threading.Thread(target=HostingManager._pump, args=(name, runtime), daemon=True,
                         name=f"server-{name}").start()
        threading.Thread(target=HostingManager._backup_schedule, args=(name, runtime), daemon=True,
                         name=f"server-backup-{name}").start()
        logger.info(f"Сервер «{name}» запускается (pid {process.pid})")
        return HostingManager.status(name)

    @staticmethod
    def _backup_schedule(name: str, runtime: ServerRuntime) -> None:
        """Бэкапы по расписанию, пока сервер работает.

        Настройки перечитываются на каждом круге, поэтому новый интервал применяется
        без перезапуска сервера. Сам бэкап просит мир сохраниться и ставит запись на паузу
        (это делает ``create_backup``), а лишние автокопии удаляются по лимиту ``backups_keep``.
        """
        last = time.time()
        while not runtime.backup_stop.wait(BACKUP_TICK_SECONDS):
            if runtime.exit_code is not None:
                return
            try:
                hours = HostingManager.get(name).backup_interval_hours
            except (NotFoundError, BadRequestError):
                return  # сервер удалён
            # Расписание выключено или мир ещё не загрузился — отсчёт начинаем заново
            if hours <= 0 or runtime.state != "running":
                last = time.time()
                continue
            if time.time() - last < hours * BACKUP_INTERVAL_SECONDS:
                continue
            last = time.time()
            try:
                create_backup(name, reason="auto")
            except Exception as e:  # noqa: BLE001 — расписание не должно падать из-за одной копии
                logger.warning(f"Бэкап по расписанию «{name}» не удался: {e}")

    @staticmethod
    def build_command(server: HostedServer, java: str) -> list[str]:
        try:
            extra = shlex.split(server.jvm_args)
        except ValueError as e:
            raise BadRequestError(f"Некорректные аргументы JVM: {e}") from e
        return [java, f"-Xmx{server.max_memory}M", f"-Xms{min(1024, server.max_memory)}M",
                "-Dstdout.encoding=UTF-8", "-Dsun.stdout.encoding=UTF-8", *extra, "-jar", server.jar_name, "nogui"]

    @staticmethod
    def _pump(name: str, runtime: ServerRuntime) -> None:
        try:
            with open(runtime.log_path, "w", encoding="utf-8") as log_file:
                assert runtime.process.stdout is not None
                for line in runtime.process.stdout:
                    line = line.rstrip("\n")
                    runtime.lines.append(line)
                    log_file.write(line + "\n")
                    log_file.flush()
                    if match := _DOMAIN_RE.search(line):
                        runtime.address = match.group("domain")
                        logger.info(f"Сервер «{name}»: публичный адрес {runtime.address}")
                    elif _SAVED_RE.search(line):
                        runtime.saved.set()
                    elif _DONE_RE.search(line) and runtime.state == "starting":
                        runtime.state = "running"
                    elif match := _JOIN_RE.search(line):
                        runtime.players.add(match.group("name"))
                    elif match := _LEAVE_RE.search(line):
                        runtime.players.discard(match.group("name"))
        except (OSError, ValueError) as e:
            logger.warning(f"Ошибка чтения консоли сервера «{name}»: {e}")
        runtime.exit_code = runtime.process.wait()
        runtime.backup_stop.set()  # расписание бэкапов больше не нужно
        runtime.state = "stopped" if runtime.exit_code == 0 or runtime.state == "stopping" else "crashed"
        runtime.players.clear()
        logger.info(f"Сервер «{name}» остановлен (код {runtime.exit_code})")
        try:
            server = HostingManager.get(name)
            if server.auto_backup and _world_dirs(server):
                create_backup(name, reason="auto")
        except Exception as e:  # noqa: BLE001 — резервная копия не должна ронять поток
            logger.warning(f"Не удалось сделать резервную копию «{name}»: {e}")
        finally:
            runtime.finished.set()

    @staticmethod
    def send_command(name: str, command: str) -> None:
        runtime = HostingManager.runtime(name)
        if runtime is None:
            raise BadRequestError("Сервер не запущен")
        command = command.strip().lstrip("/")
        if not command or "\n" in command:
            raise BadRequestError("Пустая или некорректная команда")
        try:
            assert runtime.process.stdin is not None
            runtime.process.stdin.write(command + "\n")
            runtime.process.stdin.flush()
        except (OSError, ValueError) as e:
            raise ConflictError(f"Консоль сервера недоступна: {e}") from e
        runtime.lines.append(f"> {command}")

    @staticmethod
    def stop(name: str, wait: bool = False) -> dict[str, Any]:
        runtime = HostingManager.runtime(name)
        if runtime is None:
            return HostingManager.status(name)
        runtime.state = "stopping"
        try:
            HostingManager.send_command(name, "stop")
        except (BadRequestError, ConflictError):
            runtime.process.terminate()

        def killer() -> None:
            try:
                runtime.process.wait(timeout=_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning(f"Сервер «{name}» не остановился за {_STOP_TIMEOUT} с — принудительно")
                runtime.process.kill()

        if wait:
            killer()
        else:
            threading.Thread(target=killer, daemon=True).start()
        return HostingManager.status(name)

    @staticmethod
    def stop_all() -> None:
        for name, runtime in list(HostingManager._runtimes.items()):
            if runtime.exit_code is None:
                HostingManager.stop(name, wait=True)
                runtime.finished.wait(120)  # даём дописать резервную копию

    # --- Состояние ---------------------------------------------------------------------------
    @staticmethod
    def status(name: str) -> dict[str, Any]:
        server = HostingManager.get(name)
        runtime = HostingManager._runtimes.get(name)
        state = runtime.state if runtime else "stopped"
        return {
            **server.to_dict(),
            "state": state,
            "public_address": runtime.address if runtime and runtime.exit_code is None else "",
            "lan_address": f"{_lan_ip()}:{server.port}",
            "local_address": f"127.0.0.1:{server.port}",
            "players": sorted(runtime.players) if runtime else [],
            "uptime_seconds": int(time.time() - runtime.started_at) if runtime and runtime.exit_code is None else 0,
            "exit_code": runtime.exit_code if runtime else None,
        }

    @staticmethod
    def console(name: str, lines: int = 300) -> list[str]:
        HostingManager.get(name)
        runtime = HostingManager._runtimes.get(name)
        return list(runtime.lines)[-lines:] if runtime else []


# --- Консоль с подсветкой --------------------------------------------------------------------
def classify_console_line(line: str) -> dict[str, Any]:
    """Строка консоли сервера → {text, time, level, kind, message, player}.

    ``kind`` — для подсветки в интерфейсе: command (наша команда), error, warn,
    join / leave (вход и выход игроков), ready (сервер поднялся), address (адрес туннеля),
    plain (всё остальное).
    """
    row: dict[str, Any] = {"text": line, "time": "", "level": "", "kind": "plain",
                           "message": line, "player": ""}
    if line.startswith("> "):  # команда, отправленная из лаунчера
        return {**row, "kind": "command", "message": line[2:]}
    if match := _CONSOLE_RE.match(line):
        level = match.group("level").upper()
        row["time"] = match.group("time")
        row["level"] = _CONSOLE_LEVELS.get(level, level)
        row["message"] = match.group("msg")
    elif _TRACE_RE.match(line) or _EXCEPTION_RE.match(line):
        row["level"] = "ERROR"  # продолжение стек-трейса — уровня в строке нет
    if row["level"] == "ERROR":
        row["kind"] = "error"
    elif row["level"] == "WARN":
        row["kind"] = "warn"
    if match := _JOIN_RE.search(line):
        row["kind"], row["player"] = "join", match.group("name")
    elif match := _LEAVE_RE.search(line):
        row["kind"], row["player"] = "leave", match.group("name")
    elif _DOMAIN_RE.search(line):
        row["kind"] = "address"
    elif _DONE_RE.search(line):
        row["kind"] = "ready"
    return row


def console_lines(name: str, lines: int = 300) -> list[dict[str, Any]]:
    """Консоль сервера, разобранная по строкам — для подсветки в интерфейсе."""
    return [classify_console_line(line) for line in HostingManager.console(name, lines)]


# --- Белый список и права оператора ------------------------------------------------------------
def _check_nick(nick: str) -> str:
    nick = nick.strip()
    if not _NICK_RE.match(nick):
        raise BadRequestError("Ник игрока: от 3 до 16 символов — латиница, цифры и «_»")
    return nick


def offline_uuid(nick: str) -> str:
    """UUID офлайн-игрока. Считается так же, как его считает сам сервер:
    MD5 от «OfflinePlayer:<ник>» с битами версии 3 (Java ``UUID.nameUUIDFromBytes``)."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{nick}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def mojang_uuid(nick: str) -> str:
    """UUID лицензионного игрока — из профиля на api.mojang.com (нужен интернет)."""
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True) as client:
            resp = client.get(MOJANG_PROFILE + nick)
    except httpx.HTTPError as e:
        raise ExternalServiceError(f"Mojang недоступен, UUID игрока не узнать: {e}") from e
    if resp.status_code in (204, 404):
        raise NotFoundError(f"Лицензионного игрока «{nick}» у Mojang нет — проверьте ник")
    if resp.status_code != 200:
        raise ExternalServiceError(f"Mojang вернул HTTP {resp.status_code}")
    try:
        return str(uuid.UUID(resp.json().get("id") or ""))
    except (ValueError, AttributeError) as e:
        raise ExternalServiceError(f"Mojang вернул неожиданный ответ: {e}") from e


def _online_mode(server: HostedServer) -> bool:
    return read_properties(server.path / "server.properties").get("online-mode", "false").strip().lower() == "true"


def _player_uuid(server: HostedServer, nick: str) -> str:
    """UUID игрока для whitelist.json и ops.json.

    При ``online-mode=true`` сервер сверяет игроков с Mojang, поэтому нужен настоящий UUID
    из профиля; при ``online-mode=false`` он считается из ника локально.
    """
    return mojang_uuid(nick) if _online_mode(server) else offline_uuid(nick)


def _read_entries(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and str(e.get("name", "")).strip()]


def players(name: str) -> dict[str, Any]:
    """Белый список и операторы сервера — как их видит сам Minecraft."""
    server = HostingManager.get(name)
    props = read_properties(server.path / "server.properties")
    return {
        "online_mode": props.get("online-mode", "false").strip().lower() == "true",
        "white_list": props.get("white-list", "false").strip().lower() == "true",
        "running": HostingManager.runtime(name) is not None,
        "whitelist": sorted((e["name"] for e in _read_entries(server.path / "whitelist.json")), key=str.lower),
        "ops": sorted((e["name"] for e in _read_entries(server.path / "ops.json")), key=str.lower),
    }


_PLAYER_COMMANDS = {("whitelist", True): "whitelist add", ("whitelist", False): "whitelist remove",
                    ("ops", True): "op", ("ops", False): "deop"}


def _change_player_list(name: str, kind: str, nick: str, enabled: bool) -> dict[str, Any]:
    """Правит whitelist.json или ops.json и, если сервер запущен, дублирует изменение командой.

    Файл правится всегда: так список виден в лаунчере сразу и не теряется после перезапуска.
    Запущенный сервер держит список в памяти и перезапишет файл тем же содержимым, поэтому
    порядок записи не важен — результат один и тот же.
    """
    server = HostingManager.get(name)
    nick = _check_nick(nick)
    path = server.path / ("whitelist.json" if kind == "whitelist" else "ops.json")
    with HostingManager._lock:
        entries = _read_entries(path)
        existing = next((e for e in entries if str(e.get("name", "")).lower() == nick.lower()), None)
        if enabled and existing is None:
            entry: dict[str, Any] = {"uuid": _player_uuid(server, nick), "name": nick}
            if kind == "ops":
                level = read_properties(server.path / "server.properties").get("op-permission-level", "")
                entry["level"] = int(level) if level.isdigit() else OP_LEVEL
                entry["bypassesPlayerLimit"] = False
            entries.append(entry)
        elif not enabled and existing is not None:
            entries = [e for e in entries if e is not existing]
        else:
            return players(name)  # уже в нужном состоянии — ничего не делаем
        atomic_write_json(path, entries)
    if HostingManager.runtime(name):
        try:
            HostingManager.send_command(name, f"{_PLAYER_COMMANDS[(kind, enabled)]} {nick}")
        except (BadRequestError, ConflictError) as e:
            logger.warning(f"Сервер «{name}»: команда не прошла, список применится после перезапуска: {e}")
    logger.info(f"Сервер «{name}»: {kind} {'+' if enabled else '-'}{nick}")
    return players(name)


def set_whitelist(name: str, nick: str, enabled: bool) -> dict[str, Any]:
    """Добавляет игрока в белый список или убирает из него."""
    return _change_player_list(name, "whitelist", nick, enabled)


def set_operator(name: str, nick: str, enabled: bool) -> dict[str, Any]:
    """Выдаёт права оператора или снимает их."""
    return _change_player_list(name, "ops", nick, enabled)


# --- Моды сервера и сборка для друзей ------------------------------------------------------
def list_server_mods(name: str) -> list[dict[str, Any]]:
    from backend.core.mod_metadata import scan_mods
    server = HostingManager.get(name)
    meta = ContentManager.load_meta(server)
    result = []
    if server.content_type is None:
        return []
    for mod in scan_mods(server.content_dir):
        info = meta.get(f"{server.content_type}/{mod.filename.removesuffix('.disabled')}", {})
        result.append({"filename": mod.filename, "name": info.get("title") or mod.name, "enabled": mod.enabled,
                       "version": info.get("version_number") or mod.version, "size": mod.size,
                       "tunnel": mod.filename.lower().startswith("e4mc")})
    return result


def remove_server_mod(name: str, filename: str) -> None:
    server = HostingManager.get(name)
    if HostingManager.runtime(name):
        raise ConflictError("Остановите сервер, чтобы удалить мод")
    try:
        validate_name(filename, max_length=255)
        path = safe_join(server.content_dir, filename)
    except UnsafePathError as e:
        raise BadRequestError(str(e)) from e
    if not path.exists():
        raise NotFoundError(f"Файл «{filename}» не найден")
    path.unlink()


def export_client_pack(name: str, dest: Path, task: Task | None = None) -> dict[str, Any]:
    """Сборка для друзей (.mrpack): клиентские моды сервера с Modrinth + Fabric нужной версии.

    Серверные моды (и туннель e4mc) в сборку не попадают — друзьям они не нужны.
    """
    import json
    import zipfile

    from backend.core.mod_metadata import scan_mods
    from backend.services.modrinth_client import get_modrinth

    server = HostingManager.get(name)
    if server.core != "fabric":
        raise BadRequestError("Сборка для друзей нужна только для серверов с модами (Fabric)")
    if task:
        task.set_status("Определение модов сервера на Modrinth…")
    mods = [m for m in scan_mods(server.mods_dir) if m.enabled and m.sha1]
    modrinth = get_modrinth()
    versions = modrinth.versions_by_hashes([m.sha1 for m in mods])
    projects = {p["id"]: p for p in modrinth.get_projects(list({v["project_id"] for v in versions.values()}))}
    files, skipped = [], []
    for mod in mods:
        version = versions.get(mod.sha1)
        project = projects.get(version["project_id"], {}) if version else {}
        if not version or project.get("client_side") == "unsupported" or project.get("slug") == TUNNEL_MOD:
            skipped.append(mod.name)
            continue
        download = next((f for f in version["files"] if (f.get("hashes") or {}).get("sha1") == mod.sha1), None)
        if download:
            files.append({"path": f"mods/{mod.filename}", "hashes": {"sha1": mod.sha1, "sha512": mod.sha512},
                          "env": {"client": "required", "server": "required"},
                          "downloads": [download["url"]], "fileSize": mod.size})
    index = {"formatVersion": 1, "game": "minecraft", "versionId": "1.0.0", "name": f"{name} — для друзей",
             "summary": f"Клиентская сборка для сервера «{name}» (NexoraLauncher)", "files": files,
             "dependencies": {"minecraft": server.version, "fabric-loader": server.loader_version}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index, indent=2, ensure_ascii=False))
    return {"path": str(dest), "mods": len(files), "skipped": skipped}


# --- Резервные копии мира -------------------------------------------------------------------
_BACKUP_RE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_(?P<reason>[a-z-]+)(?:_\d+)?\.zip$")


def _world_dirs(server: HostedServer) -> list[Path]:
    """Папки мира: основной, а у Paper/Purpur ещё отдельные _nether и _the_end."""
    level = read_properties(server.path / "server.properties").get("level-name") or "world"
    try:
        validate_name(level)
    except UnsafePathError:
        level = "world"
    main = server.path / level
    if not (main / "level.dat").exists():
        return []
    extra = [server.path / f"{level}_nether", server.path / f"{level}_the_end"]
    return [main, *(p for p in extra if p.is_dir())]


def _backup_folder(name: str) -> Path:
    _server_path(name)  # проверка имени
    return backups_dir() / name


def _backup_file(name: str, filename: str) -> Path:
    if not _BACKUP_RE.match(filename):
        raise BadRequestError("Некорректное имя резервной копии")
    path = _backup_folder(name) / filename
    if not path.is_file():
        raise NotFoundError(f"Резервная копия «{filename}» не найдена")
    return path


def list_backups(name: str) -> list[dict[str, Any]]:
    HostingManager.get(name)
    folder = _backup_folder(name)
    if not folder.exists():
        return []
    result = []
    for path in folder.glob("*.zip"):
        match = _BACKUP_RE.match(path.name)
        if not match:
            continue
        stat = path.stat()
        created = datetime.strptime(match.group("stamp"), "%Y-%m-%d_%H-%M-%S")
        result.append({"filename": path.name, "reason": match.group("reason"), "size": stat.st_size,
                       "created_at": created.isoformat(timespec="seconds"), "_order": (created, stat.st_mtime_ns)})
    result.sort(key=lambda b: b["_order"], reverse=True)
    for backup in result:
        del backup["_order"]
    return result


def _prune_backups(server: HostedServer, keep_file: str) -> None:
    """Автоматические копии сверх лимита удаляются (самые старые); ручные — никогда."""
    folder = _backup_folder(server.name)
    autos = sorted((p for p in folder.glob("*.zip")
                    if (m := _BACKUP_RE.match(p.name)) and m.group("reason") == "auto" and p.name != keep_file),
                   key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in autos[max(0, server.backups_keep - 1):]:
        path.unlink(missing_ok=True)


def create_backup(name: str, reason: str = "manual", task: Task | None = None) -> dict[str, Any]:
    """Архивирует мир и настройки сервера. На запущенном сервере сохранение мира
    временно выключается (save-off / save-all flush), чтобы архив был целостным."""
    import zipfile

    server = HostingManager.get(name)
    worlds = _world_dirs(server)
    if not worlds:
        raise BadRequestError("Мир ещё не создан — запустите сервер хотя бы один раз")
    runtime = HostingManager.runtime(name)
    if runtime and runtime.state == "running":
        if task:
            task.set_status("Сохранение мира…")
        runtime.saved.clear()
        HostingManager.send_command(name, "save-off")
        HostingManager.send_command(name, "save-all flush")
        if not runtime.saved.wait(_SAVE_TIMEOUT):
            logger.warning(f"Сервер «{name}» не подтвердил сохранение мира — копируем как есть")
    else:
        runtime = None
    folder = _backup_folder(name)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{reason}"
    target = folder / f"{stem}.zip"
    counter = 2
    while target.exists():  # несколько копий за одну секунду
        target = folder / f"{stem}_{counter}.zip"
        counter += 1
    partial = target.with_suffix(".part")
    try:
        if task:
            task.set_status("Архивация мира…")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as zf:
            for world in worlds:
                for file in world.rglob("*"):
                    if file.is_file() and file.name != "session.lock":
                        zf.write(file, file.relative_to(server.path).as_posix())
            for extra in BACKUP_FILES:
                if (server.path / extra).is_file():
                    zf.write(server.path / extra, extra)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
        if runtime:
            try:
                HostingManager.send_command(name, "save-on")
            except (BadRequestError, ConflictError):
                pass
    size = target.stat().st_size
    if reason == "auto":
        _prune_backups(server, target.name)
    logger.info(f"Резервная копия сервера «{name}»: {target.name}")
    return {"filename": target.name, "size": size}


def restore_backup(name: str, filename: str, task: Task | None = None) -> dict[str, Any]:
    """Возвращает мир из резервной копии (текущий мир перед этим тоже сохраняется)."""
    import zipfile

    from shared.fsutil import safe_extract_zip

    server = HostingManager.get(name)
    if HostingManager.runtime(name):
        raise ConflictError("Остановите сервер перед восстановлением")
    path = _backup_file(name, filename)
    if _world_dirs(server):
        if task:
            task.set_status("Копия текущего мира…")
        create_backup(name, reason="before-restore")
    if task:
        task.set_status("Восстановление мира…")
    with zipfile.ZipFile(path) as zf:
        roots = {n.split("/", 1)[0] for n in zf.namelist() if "/" in n}
        for root in roots:
            try:
                target = safe_join(server.path, root)
            except UnsafePathError as e:
                raise BadRequestError(f"Повреждённая резервная копия: {e}") from e
            if target.is_dir():
                shutil.rmtree(target)
        safe_extract_zip(zf, server.path)
    values = read_properties(server.path / "server.properties")
    values["server-port"] = str(server.port)  # порт мог смениться с момента копии
    write_properties(server.path / "server.properties", values)
    logger.info(f"Сервер «{name}» восстановлен из {filename}")
    return {"restored": filename}


def delete_backup(name: str, filename: str) -> None:
    _backup_file(name, filename).unlink()
