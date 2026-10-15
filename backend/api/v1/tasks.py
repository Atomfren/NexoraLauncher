"""Фоновые задачи."""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.core.tasks import task_manager

router = APIRouter()


class TaskResponse(BaseModel):
    id: str
    kind: str
    title: str
    status: str
    message: str
    progress: float | None
    result: Any = None
    error: str
    created_at: float
    finished_at: float | None


@router.get("/tasks/", response_model=list[TaskResponse])
def list_tasks(active: bool = Query(False, description="Только незавершённые")):
    return [t.to_dict() for t in task_manager.all(active_only=active)]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str):
    return task_manager.get(task_id).to_dict()


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(task_id: str):
    return task_manager.cancel(task_id).to_dict()
