"""Minecraft API: версии, загрузчики, запущенные процессы."""

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from backend.api.v1.tasks import TaskResponse
from backend.core.minecraft import MinecraftManager
from backend.core.process_manager import process_manager
from backend.core.tasks import task_manager

router = APIRouter()


class VersionInfo(BaseModel):
    id: str
    type: str
    release_time: str
    inherits_from: str = ""


class ProcessInfo(BaseModel):
    pid: int
    instance: str
    username: str
    version: str
    status: str
    exit_code: int | None
    started_at: float
    duration_seconds: int
    log_path: str
    public_address: str = ""


@router.get("/minecraft/versions/available", response_model=list[VersionInfo])
def get_available_versions(refresh: bool = False):
    return MinecraftManager().get_available_versions(force=refresh)


@router.get("/minecraft/versions/installed", response_model=list[VersionInfo])
def get_installed_versions():
    return MinecraftManager().get_installed_versions()


@router.post("/minecraft/versions/{version_id}/install", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def install_version(version_id: str):
    def run(task):
        return {"version": MinecraftManager().install_version(version_id, task)}

    return task_manager.submit("install", f"Установка Minecraft {version_id}", run).to_dict()


@router.get("/minecraft/loaders/{loader}/versions", response_model=list[str])
def get_loader_versions(loader: str, mc_version: str = Query(..., min_length=1),
                        stable_only: bool = True):
    return MinecraftManager().get_loader_versions(loader, mc_version, stable_only)


@router.get("/minecraft/processes", response_model=list[ProcessInfo])
def list_processes():
    return [g.to_dict() for g in process_manager.all()]


@router.get("/minecraft/processes/{pid}", response_model=ProcessInfo)
def get_process(pid: int):
    return process_manager.get(pid).to_dict()


@router.get("/minecraft/processes/{pid}/log", response_model=list[str])
def get_process_log(pid: int, lines: int = Query(200, ge=1, le=2000)):
    return process_manager.log_tail(pid, lines)


@router.delete("/minecraft/processes/{pid}", response_model=ProcessInfo)
def stop_process(pid: int):
    return process_manager.stop(pid).to_dict()
