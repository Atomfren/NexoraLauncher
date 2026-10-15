"""«Умные» функции: Доктор, снимки, обновления модов, «Турбо», экспорт .mrpack."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core import doctor, snapshots, updates
from backend.core.instance import InstanceManager
from backend.core.pack_manager import PackManager
from backend.core.tasks import task_manager

router = APIRouter()


class FixRequest(BaseModel):
    action: str = Field(..., pattern="^(install_mod|disable_mod|remove_mod|set_memory|reset_java|repair|"
                                     "update_loader)$")
    params: dict[str, Any] = {}


class SnapshotRequest(BaseModel):
    label: str = Field("", max_length=100)


class Snapshot(BaseModel):
    id: str
    label: str
    auto: bool
    created_at: str
    size: int
    mods: int
    version: str
    mod_loader: str


class UpdateRequest(BaseModel):
    version_ids: list[str] | None = None


class TurboRequest(BaseModel):
    tune_jvm: bool = True


class PathRequest(BaseModel):
    path: str


# --- Доктор --------------------------------------------------------------------------
@router.get("/instances/{name}/doctor")
def diagnose(name: str):
    return doctor.diagnose(name)


@router.post("/instances/{name}/doctor/fix", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def apply_fix(name: str, request: FixRequest):
    InstanceManager.get(name)
    return task_manager.submit("doctor", f"Исправление в «{name}»",
                               lambda task: doctor.apply_fix(name, request.action, request.params, task)).to_dict()


# --- Снимки ----------------------------------------------------------------------------
@router.get("/instances/{name}/snapshots", response_model=list[Snapshot])
def list_snapshots(name: str):
    return snapshots.list_snapshots(name)


@router.post("/instances/{name}/snapshots", response_model=Snapshot, status_code=status.HTTP_201_CREATED)
def create_snapshot(name: str, request: SnapshotRequest | None = None):
    return snapshots.create(name, request.label if request else "")


@router.post("/instances/{name}/snapshots/{snap_id}/restore", response_model=Snapshot)
def restore_snapshot(name: str, snap_id: str):
    return snapshots.restore(name, snap_id)


@router.delete("/instances/{name}/snapshots/{snap_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(name: str, snap_id: str):
    snapshots.delete(name, snap_id)


# --- Обновления модов ----------------------------------------------------------------
@router.post("/instances/{name}/mods/identify")
def identify_mods(name: str):
    return updates.identify(name)


@router.get("/instances/{name}/mods/updates")
def mod_updates(name: str):
    return updates.check_updates(name)


@router.post("/instances/{name}/mods/updates", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def apply_mod_updates(name: str, request: UpdateRequest | None = None):
    InstanceManager.get(name)
    ids = request.version_ids if request else None
    return task_manager.submit("mod_update", f"Обновление модов «{name}»",
                               lambda task: updates.apply_updates(name, ids, task)).to_dict()


# --- «Турбо» ------------------------------------------------------------------------------
@router.get("/instances/{name}/turbo")
def turbo_plan(name: str):
    return updates.turbo_plan(name)


@router.post("/instances/{name}/turbo", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def apply_turbo(name: str, request: TurboRequest | None = None):
    updates.turbo_plan(name)  # валидация до запуска задачи
    tune = request.tune_jvm if request else True
    return task_manager.submit("turbo", f"«Турбо» для «{name}»",
                               lambda task: updates.apply_turbo(name, task, tune)).to_dict()


# --- Поделиться ---------------------------------------------------------------------------
@router.post("/instances/{name}/export_mrpack", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def export_mrpack(name: str, request: PathRequest):
    InstanceManager.get(name)
    dest = Path(request.path)
    return task_manager.submit("export", f"Экспорт «{name}» в .mrpack",
                               lambda task: PackManager.export_mrpack(name, dest, task)).to_dict()
