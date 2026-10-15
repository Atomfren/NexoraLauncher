"""Обновление самого лаунчера (GitHub Releases)."""

from fastapi import APIRouter, status
from pydantic import BaseModel

from backend.api.v1.tasks import TaskResponse
from backend.core import self_update
from backend.core.tasks import task_manager

router = APIRouter()


class ApplyRequest(BaseModel):
    path: str


@router.get("/app/update")
def check_update():
    return self_update.check()


@router.post("/app/update/download", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def download_update():
    return task_manager.submit("app_update", "Загрузка обновления лаунчера", self_update.download).to_dict()


@router.post("/app/update/apply")
def apply_update(request: ApplyRequest):
    return self_update.apply(request.path)
