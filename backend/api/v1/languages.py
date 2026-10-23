"""Языки интерфейса: встроенные, установленные и доступные для загрузки с сайта."""

from fastapi import APIRouter, status
from pydantic import BaseModel

from backend.api.v1.tasks import TaskResponse
from backend.core import languages
from backend.core.tasks import task_manager

router = APIRouter()


class LanguageEntry(BaseModel):
    code: str
    name: str
    builtin: bool = False
    version: str = ""
    author: str = ""
    translated: int = 0
    total: int = 0
    size: int = 0
    installed: bool = False
    update_available: bool = False


class LanguagesResponse(BaseModel):
    builtin: list[LanguageEntry]
    installed: list[LanguageEntry]
    available: list[LanguageEntry]
    # Почему не удалось получить список с сайта (нет сети, канал не настроен)
    error: str = ""


@router.get("/languages", response_model=LanguagesResponse)
def list_languages(online: bool = True):
    """Список языков. С ``online=false`` отвечает сразу, не спрашивая сайт."""
    return languages.state(online)


@router.post("/languages/{code}/install", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
def install_language(code: str):
    return task_manager.submit("language", f"Загрузка языка «{code}»",
                               lambda task: languages.install(code, task)).to_dict()


@router.delete("/languages/{code}")
def remove_language(code: str):
    return languages.remove(code)
