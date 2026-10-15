"""Servers API."""

from dataclasses import asdict

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core.errors import BadRequestError
from backend.core.instance import InstanceManager
from backend.core.launcher import launch_instance
from backend.core.server_manager import ServerManager
from backend.core.server_ping import ping_server
from shared.config import AppConfig

router = APIRouter()


class ServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(25565, ge=1, le=65535)
    instance_name: str = ""


class ServerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    host: str | None = Field(None, min_length=1, max_length=253)
    port: int | None = Field(None, ge=1, le=65535)
    instance_name: str | None = None


class ServerResponse(BaseModel):
    id: str
    name: str
    host: str
    port: int
    instance_name: str
    description: str
    icon_url: str


class PingResponse(BaseModel):
    online: bool
    player_count: int | None = None
    max_players: int | None = None
    version: str | None = None
    motd: str | None = None
    latency_ms: int | None = None
    icon: str | None = None
    error: str | None = None


class ConnectRequest(BaseModel):
    instance_name: str = ""


@router.get("/servers/", response_model=list[ServerResponse])
def list_servers():
    return [asdict(s) for s in ServerManager.list_servers()]


@router.post("/servers/", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
def create_server(server: ServerCreate):
    return asdict(ServerManager.add_server(server.name, server.host, server.port, server.instance_name))


@router.get("/servers/{server_id}", response_model=ServerResponse)
def get_server(server_id: str):
    return asdict(ServerManager.get_server(server_id))


@router.patch("/servers/{server_id}", response_model=ServerResponse)
def update_server(server_id: str, server: ServerUpdate):
    return asdict(ServerManager.update_server(server_id, **server.model_dump(exclude_unset=True)))


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: str):
    ServerManager.delete_server(server_id)


@router.get("/servers/{server_id}/ping", response_model=PingResponse)
def ping(server_id: str):
    server = ServerManager.get_server(server_id)
    return ping_server(server.host, server.port).to_dict()


@router.post("/servers/{server_id}/connect", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def connect(server_id: str, request: ConnectRequest | None = None):
    """Запускает инстанс с автоподключением к серверу."""
    server = ServerManager.get_server(server_id)
    name = (request.instance_name if request else "") or server.instance_name or AppConfig.load().last_instance
    if not name:
        instances = InstanceManager.list_instances()
        if not instances:
            raise BadRequestError("Создайте инстанс, чтобы подключиться к серверу")
        name = max(instances, key=lambda i: i.last_played or "").name
    return launch_instance(name, server.host, server.port).to_dict()
