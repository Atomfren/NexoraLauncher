"""OptiFine: версии с optifine.net, поиск скачанного файла, установка в инстанс."""

from pathlib import Path

from fastapi import APIRouter, Query, status
from pydantic import BaseModel

from backend.api.v1.tasks import TaskResponse
from backend.core import optifine
from backend.core.instance import InstanceManager
from backend.core.tasks import task_manager

router = APIRouter()


class InstallRequest(BaseModel):
    path: str


@router.get("/optifine/versions")
def versions(mc_version: str | None = None, refresh: bool = False):
    return optifine.list_versions(mc_version, force=refresh)


@router.get("/optifine/downloaded")
def downloaded(mc_version: str | None = Query(None)):
    """Файлы OptiFine в папке «Загрузки»."""
    return optifine.find_downloaded(mc_version)


@router.get("/instances/{name}/optifine")
def get_status(name: str):
    return optifine.status(name)


@router.post("/instances/{name}/optifine", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def install(name: str, request: InstallRequest):
    InstanceManager.get(name)
    optifine.inspect_jar(Path(request.path))  # быстрая проверка до фоновой задачи
    return task_manager.submit("optifine", f"OptiFine для «{name}»",
                               lambda task: optifine.install(name, Path(request.path), task)).to_dict()


@router.delete("/instances/{name}/optifine", status_code=status.HTTP_204_NO_CONTENT)
def remove(name: str):
    optifine.remove(name)
