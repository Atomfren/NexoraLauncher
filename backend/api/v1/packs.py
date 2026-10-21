"""Сборки FTB и CurseForge (All The Mods и др.): поиск, карточка, установка."""

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core import ftb_packs
from backend.core.errors import BadRequestError
from backend.core.instance import check_name
from backend.core.tasks import task_manager

router = APIRouter()
_PROVIDER = "^(ftb|curseforge)$"


class PackInstallRequest(BaseModel):
    version_id: int | None = None
    new_name: str = Field("", max_length=64)


@router.get("/packs/{provider}/search")
def search_packs(provider: str, q: str = "", limit: int = Query(20, ge=1, le=40)):
    if provider not in ftb_packs.PROVIDERS:
        raise BadRequestError(f"Неизвестный источник: {provider}")
    return {"results": ftb_packs.search(provider, q, limit)}


@router.get("/packs/{provider}/{pack_id}")
def get_pack(provider: str, pack_id: int):
    return ftb_packs.pack_row(provider, ftb_packs.pack(provider, pack_id))


@router.post("/packs/{provider}/{pack_id}/install", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def install_pack(provider: str, pack_id: int, request: PackInstallRequest | None = None):
    request = request or PackInstallRequest()
    if provider not in ftb_packs.PROVIDERS:
        raise BadRequestError(f"Неизвестный источник: {provider}")
    if request.new_name:
        check_name(request.new_name)

    def run(task):
        instance, blocked = ftb_packs.install(provider, pack_id, request.version_id, request.new_name, task)
        return {"name": instance.name, "blocked": blocked}

    title = "FTB" if provider == "ftb" else "CurseForge"
    return task_manager.submit("modpack", f"Установка сборки {title}", run).to_dict()
