"""Список избранных серверов."""

import threading
import uuid
from dataclasses import asdict, dataclass, fields
from typing import Any

from backend.core.errors import NotFoundError
from shared.fsutil import atomic_write_json, read_json
from shared.paths import get_config_dir

_lock = threading.Lock()


@dataclass
class Server:
    """Сервер Minecraft."""

    id: str
    name: str
    host: str
    port: int = 25565
    # Инстанс, которым подключаться (пусто — последний запущенный)
    instance_name: str = ""
    description: str = ""
    icon_url: str = ""


class ServerManager:
    """Хранение серверов в servers.json."""

    @staticmethod
    def _path():
        return get_config_dir() / "servers.json"

    @classmethod
    def _load(cls) -> list[Server]:
        data = read_json(cls._path(), default=[])
        known = {f.name for f in fields(Server)}
        servers = []
        for item in data if isinstance(data, list) else []:
            try:
                servers.append(Server(**{k: v for k, v in item.items() if k in known}))
            except TypeError:
                continue
        return servers

    @classmethod
    def _save(cls, servers: list[Server]) -> None:
        atomic_write_json(cls._path(), [asdict(s) for s in servers])

    @classmethod
    def list_servers(cls) -> list[Server]:
        return cls._load()

    @classmethod
    def get_server(cls, server_id: str) -> Server:
        for server in cls._load():
            if server.id == server_id:
                return server
        raise NotFoundError(f"Сервер '{server_id}' не найден")

    @classmethod
    def add_server(cls, name: str, host: str, port: int = 25565, instance_name: str = "") -> Server:
        with _lock:
            servers = cls._load()
            server = Server(id=uuid.uuid4().hex, name=name, host=host.strip(), port=port,
                            instance_name=instance_name)
            servers.append(server)
            cls._save(servers)
            return server

    @classmethod
    def update_server(cls, server_id: str, **changes: Any) -> Server:
        with _lock:
            servers = cls._load()
            for server in servers:
                if server.id == server_id:
                    for key, value in changes.items():
                        if key != "id" and hasattr(server, key) and value is not None:
                            setattr(server, key, value)
                    cls._save(servers)
                    return server
        raise NotFoundError(f"Сервер '{server_id}' не найден")

    @classmethod
    def delete_server(cls, server_id: str) -> None:
        with _lock:
            servers = cls._load()
            remaining = [s for s in servers if s.id != server_id]
            if len(remaining) == len(servers):
                raise NotFoundError(f"Сервер '{server_id}' не найден")
            cls._save(remaining)
