"""Умные логи: список логов инстанса, разбор, публикация на mclo.gs."""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core import log_analyzer

router = APIRouter()


class ShareRequest(BaseModel):
    source: str = ""


@router.get("/instances/{name}/logs")
def sources(name: str):
    return log_analyzer.list_sources(name)


@router.get("/instances/{name}/logs/analyze")
def analyze(name: str, source: str = ""):
    return log_analyzer.analyze(name, source)


@router.post("/instances/{name}/logs/share")
def share(name: str, request: ShareRequest):
    return log_analyzer.share(name, request.source)
