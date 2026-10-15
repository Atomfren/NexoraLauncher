"""Modpacks API: установка модпаков Modrinth (поиск — через /content/search?project_type=modpack)."""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core.instance import check_name
from backend.core.pack_manager import PackManager
from backend.core.tasks import task_manager

router = APIRouter()


class ModpackInstallRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    version_id: str | None = None
    new_name: str = Field("", max_length=64, description="Имя инстанса (по умолчанию — название модпака)")


@router.post("/modpacks/install", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def install_modpack(request: ModpackInstallRequest):
    if request.new_name:
        check_name(request.new_name)

    def run(task):
        instance = PackManager.install_from_modrinth(request.project_id, request.version_id,
                                                     request.new_name, task)
        return {"name": instance.name}

    return task_manager.submit("modpack", "Установка модпака", run).to_dict()
