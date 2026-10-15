"""Instances API."""

from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core import snapshots
from backend.core.errors import ConflictError
from backend.core.instance import MOD_LOADERS, Instance, InstanceManager
from backend.core.launcher import launch_instance
from backend.core.minecraft import MinecraftManager
from backend.core.pack_manager import PackManager
from backend.core.process_manager import process_manager
from backend.core.tasks import task_manager

router = APIRouter()
_LOADER_PATTERN = "^(" + "|".join(MOD_LOADERS) + ")$"


class InstanceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., min_length=1, max_length=64)
    mod_loader: str = Field("vanilla", pattern=_LOADER_PATTERN)
    loader_version: str = ""
    install: bool = Field(True, description="Сразу запустить установку игры и загрузчика")


class InstanceUpdate(BaseModel):
    version: str | None = Field(None, min_length=1, max_length=64)
    mod_loader: str | None = Field(None, pattern=_LOADER_PATTERN)
    loader_version: str | None = None
    java_path: str | None = None
    max_memory: int | None = Field(None, ge=0, le=65536)
    min_memory: int | None = Field(None, ge=0, le=65536)
    jvm_args: str | None = Field(None, max_length=2000)
    width: int | None = Field(None, ge=0, le=7680)
    height: int | None = Field(None, ge=0, le=4320)
    fullscreen: bool | None = None


class InstanceResponse(BaseModel):
    name: str
    version: str
    mod_loader: str
    loader_version: str
    launch_version_id: str
    java_path: str
    max_memory: int
    min_memory: int
    jvm_args: str
    width: int
    height: int
    fullscreen: bool
    optifine: str = ""
    created_at: str
    last_played: str
    play_count: int
    total_play_seconds: int
    path: str
    game_dir: str
    installed: bool
    running_pid: int | None = None


class NameRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=64)


class LaunchRequest(BaseModel):
    server: str = ""
    port: int = Field(25565, ge=1, le=65535)


class PrepareRequest(BaseModel):
    force: bool = Field(False, description="Переустановить (проверить) файлы игры")


class ExportRequest(BaseModel):
    path: str = Field(..., description="Куда сохранить .zip")


class ImportRequest(BaseModel):
    file_path: str = Field(..., description="Путь к .zip, .mrpack или папке сборки Prism/MultiMC/CurseForge")
    new_name: str = ""


def to_response(instance: Instance, mc: MinecraftManager | None = None) -> dict[str, Any]:
    mc = mc or MinecraftManager()
    data = instance.to_dict()
    custom_launch = instance.is_modded or instance.optifine
    launch_id = (instance.launch_version_id or "") if custom_launch else instance.version
    running = process_manager.running_for(instance.name)
    data.update(
        path=str(instance.path),
        game_dir=str(instance.game_dir),
        installed=bool(launch_id) and mc.is_version_installed(launch_id),
        running_pid=running.pid if running else None,
    )
    return data


def _prepare_task(instance: Instance, force: bool = False):
    def run(task):
        launch_id = MinecraftManager().prepare_instance(instance, task, force=force)
        return {"name": instance.name, "launch_version_id": launch_id}

    return task_manager.submit("install", f"Установка «{instance.name}»", run)


@router.get("/instances/", response_model=list[InstanceResponse])
def list_instances():
    mc = MinecraftManager()
    return [to_response(i, mc) for i in InstanceManager.list_instances()]


@router.post("/instances/", response_model=InstanceResponse, status_code=status.HTTP_201_CREATED)
def create_instance(data: InstanceCreate):
    instance = InstanceManager.create(data.name, data.version, data.mod_loader, data.loader_version)
    if data.install:
        _prepare_task(instance)
    return to_response(instance)


@router.get("/instances/import/foreign")
def foreign_instances():
    """Сборки Prism Launcher / MultiMC / CurseForge, найденные на компьютере."""
    from backend.core import foreign_import
    return foreign_import.discover()


@router.post("/instances/import", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def import_instance(request: ImportRequest):
    path = Path(request.file_path)

    def run(task):
        instance = PackManager.import_archive(path, request.new_name, task)
        return {"name": instance.name}

    return task_manager.submit("import", f"Импорт {path.name}", run).to_dict()


@router.get("/instances/{name}", response_model=InstanceResponse)
def get_instance(name: str):
    return to_response(InstanceManager.get(name))


@router.patch("/instances/{name}", response_model=InstanceResponse)
def update_instance(name: str, data: InstanceUpdate):
    changes = data.model_dump(exclude_unset=True)
    current = InstanceManager.get(name)
    if any(key in changes and changes[key] != getattr(current, key)
           for key in ("version", "mod_loader", "loader_version")):
        snapshots.create(name, "Перед сменой версии/загрузчика", auto=True)
    return to_response(InstanceManager.update(name, **changes))


@router.delete("/instances/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instance(name: str):
    if process_manager.running_for(name):
        raise ConflictError("Нельзя удалить запущенный инстанс — сначала закройте игру")
    InstanceManager.delete(name)


@router.post("/instances/{name}/rename", response_model=InstanceResponse)
def rename_instance(name: str, request: NameRequest):
    if process_manager.running_for(name):
        raise ConflictError("Нельзя переименовать запущенный инстанс")
    return to_response(InstanceManager.rename(name, request.new_name))


@router.post("/instances/{name}/duplicate", response_model=InstanceResponse,
             status_code=status.HTTP_201_CREATED)
def duplicate_instance(name: str, request: NameRequest):
    return to_response(InstanceManager.duplicate(name, request.new_name))


@router.post("/instances/{name}/prepare", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def prepare_instance(name: str, request: PrepareRequest | None = None):
    instance = InstanceManager.get(name)
    return _prepare_task(instance, force=bool(request and request.force)).to_dict()


@router.post("/instances/{name}/launch", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def launch(name: str, request: LaunchRequest | None = None):
    request = request or LaunchRequest()
    return launch_instance(name, request.server, request.port).to_dict()


@router.get("/instances/{name}/log")
def latest_log(name: str, lines: int = Query(500, ge=1, le=5000)):
    """Последний лог запуска из файла (доступен и после перезапуска лаунчера)."""
    instance = InstanceManager.get(name)
    logs = []
    if instance.logs_dir.exists():
        logs = sorted(instance.logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return {"file": "", "lines": []}
    with open(logs[0], encoding="utf-8", errors="replace") as f:
        tail = deque(f, maxlen=lines)
    return {"file": str(logs[0]), "lines": [line.rstrip("\n") for line in tail]}


@router.post("/instances/{name}/export", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def export_instance(name: str, request: ExportRequest):
    InstanceManager.get(name)
    dest = Path(request.path)

    def run(task):
        return {"path": str(PackManager.export_instance(name, dest, task))}

    return task_manager.submit("export", f"Экспорт «{name}»", run).to_dict()
