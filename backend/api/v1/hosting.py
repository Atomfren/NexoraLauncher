"""Свой сервер без белого IP (Fabric/Vanilla/Paper/Purpur, туннель e4mc, бэкапы) и «Играть с друзьями»."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core import hosting
from backend.core.content import ContentManager
from backend.core.errors import BadRequestError, ConflictError
from backend.core.hosting import HostingManager
from backend.core.instance import InstanceManager
from backend.core.mod_metadata import scan_mods
from backend.core.tasks import task_manager

router = APIRouter()


class ServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., min_length=1, max_length=32)
    core: str = Field("fabric", pattern="^(fabric|vanilla|paper|purpur)$")
    max_memory: int = Field(3072, ge=1024, le=65536)
    accept_eula: bool = Field(False, description="Пользователь принял EULA Minecraft")


class ServerUpdate(BaseModel):
    max_memory: int | None = Field(None, ge=1024, le=65536)
    tunnel: bool | None = None
    jvm_args: str | None = Field(None, max_length=2000)
    auto_backup: bool | None = None
    backups_keep: int | None = Field(None, ge=1, le=100)
    backup_interval_hours: int | None = Field(None, ge=0, le=168, description="0 — без расписания")


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=500)


class PlayerRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=16, description="Ник игрока Minecraft")


class ModRequest(BaseModel):
    project_id: str = Field(..., min_length=1)


class PathRequest(BaseModel):
    path: str


def _install_task(name: str):
    return task_manager.submit("server_install", f"Установка сервера «{name}»",
                               lambda task: HostingManager.install(name, task).to_dict())


@router.get("/hosting/servers")
def list_servers():
    return [HostingManager.status(s.name) for s in HostingManager.all_servers()]


@router.post("/hosting/servers", status_code=status.HTTP_201_CREATED)
def create_server(request: ServerCreate):
    if not request.accept_eula:
        raise BadRequestError("Чтобы создать сервер, нужно принять EULA Minecraft (aka.ms/MinecraftEULA)")
    server = HostingManager.create(request.name, request.version, request.max_memory, request.core)
    HostingManager.update(server.name, eula_accepted=True)
    task = _install_task(server.name)
    return {"server": HostingManager.status(server.name), "task": task.to_dict()}


@router.get("/hosting/servers/{name}")
def get_server(name: str):
    return HostingManager.status(name)


@router.patch("/hosting/servers/{name}")
def update_server(name: str, request: ServerUpdate):
    HostingManager.update(name, **request.model_dump(exclude_unset=True))
    return HostingManager.status(name)


@router.delete("/hosting/servers/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(name: str):
    HostingManager.delete(name)


@router.post("/hosting/servers/{name}/install", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def reinstall(name: str):
    if HostingManager.runtime(name):
        raise ConflictError("Остановите сервер перед переустановкой")
    HostingManager.get(name)
    return _install_task(name).to_dict()


@router.post("/hosting/servers/{name}/start")
def start(name: str):
    return HostingManager.start(name)


@router.post("/hosting/servers/{name}/stop")
def stop(name: str):
    return HostingManager.stop(name)


@router.post("/hosting/servers/{name}/command", status_code=status.HTTP_204_NO_CONTENT)
def command(name: str, request: CommandRequest):
    HostingManager.send_command(name, request.command)


@router.get("/hosting/servers/{name}/console", response_model=list[str])
def console(name: str, lines: int = Query(300, ge=1, le=3000)):
    return HostingManager.console(name, lines)


@router.get("/hosting/servers/{name}/console_lines")
def console_lines(name: str, lines: int = Query(300, ge=1, le=3000)):
    """Та же консоль, но разобранная по строкам — для подсветки в интерфейсе."""
    return hosting.console_lines(name, lines)


# --- Белый список и права оператора ---------------------------------------------------------
@router.get("/hosting/servers/{name}/players")
def server_players(name: str):
    return hosting.players(name)


@router.post("/hosting/servers/{name}/whitelist")
def add_to_whitelist(name: str, request: PlayerRequest):
    return hosting.set_whitelist(name, request.name, True)


@router.delete("/hosting/servers/{name}/whitelist/{player}")
def remove_from_whitelist(name: str, player: str):
    return hosting.set_whitelist(name, player, False)


@router.post("/hosting/servers/{name}/ops")
def add_operator(name: str, request: PlayerRequest):
    return hosting.set_operator(name, request.name, True)


@router.delete("/hosting/servers/{name}/ops/{player}")
def remove_operator(name: str, player: str):
    return hosting.set_operator(name, player, False)


@router.get("/hosting/servers/{name}/properties")
def get_properties(name: str):
    return HostingManager.properties(name)


@router.patch("/hosting/servers/{name}/properties")
def update_properties(name: str, changes: dict[str, Any]):
    return HostingManager.update_properties(name, changes)


@router.get("/hosting/servers/{name}/mods")
def list_mods(name: str):
    return hosting.list_server_mods(name)


@router.post("/hosting/servers/{name}/mods", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def install_mod(name: str, request: ModRequest):
    server = HostingManager.get(name)
    content_type = server.content_type
    if content_type is None:
        raise BadRequestError("На ванильный сервер нельзя ставить моды и плагины — выберите Fabric или Paper")
    title = "Плагин" if content_type == "plugin" else "Мод"
    return task_manager.submit("server_mod", f"{title} для сервера «{name}»",
                               lambda task: ContentManager.install_into(server, content_type, request.project_id,
                                                                        task=task)).to_dict()


@router.delete("/hosting/servers/{name}/mods/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def remove_mod(name: str, filename: str):
    hosting.remove_server_mod(name, filename)


@router.post("/hosting/servers/{name}/client_pack", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def client_pack(name: str, request: PathRequest):
    HostingManager.get(name)
    dest = Path(request.path)
    return task_manager.submit("export", f"Сборка для друзей «{name}»",
                               lambda task: hosting.export_client_pack(name, dest, task)).to_dict()


# --- «Играть с друзьями» из обычного инстанса --------------------------------------------
@router.post("/instances/{name}/friends/prepare", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def prepare_friends(name: str):
    """Ставит туннель e4mc в инстанс (если его ещё нет)."""
    instance = InstanceManager.get(name)
    if not instance.is_modded:
        raise BadRequestError("Для игры с друзьями нужен инстанс с загрузчиком (Fabric, Quilt, Forge, NeoForge). "
                              "Смените загрузчик в настройках инстанса или создайте свой сервер.")

    def run(task):
        mods = scan_mods(instance.mods_dir)
        if any("e4mc_minecraft" in m.ids or m.filename.lower().startswith("e4mc") for m in mods if m.enabled):
            return {"installed": False}
        ContentManager.install(name, "mod", hosting.TUNNEL_MOD, task=task)
        return {"installed": True}

    return task_manager.submit("friends", f"Подготовка «{name}» к игре с друзьями", run).to_dict()


# --- Резервные копии ---------------------------------------------------------------------------
@router.get("/hosting/servers/{name}/backups")
def list_backups(name: str):
    return hosting.list_backups(name)


@router.post("/hosting/servers/{name}/backups", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def create_backup(name: str):
    HostingManager.get(name)
    return task_manager.submit("server_backup", f"Резервная копия «{name}»",
                               lambda task: hosting.create_backup(name, "manual", task)).to_dict()


@router.post("/hosting/servers/{name}/backups/{filename}/restore", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def restore_backup(name: str, filename: str):
    if HostingManager.runtime(name):
        raise ConflictError("Остановите сервер перед восстановлением")
    return task_manager.submit("server_restore", f"Восстановление «{name}»",
                               lambda task: hosting.restore_backup(name, filename, task)).to_dict()


@router.delete("/hosting/servers/{name}/backups/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(name: str, filename: str):
    hosting.delete_backup(name, filename)
