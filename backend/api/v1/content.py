"""Контент: поиск на Modrinth, моды/ресурспаки/шейдеры инстанса, миры."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from backend.api.v1.tasks import TaskResponse
from backend.core.content import ContentManager
from backend.core.instance import InstanceManager
from backend.core.tasks import task_manager
from backend.services.modrinth_client import PROJECT_TYPES, SORT_INDEXES, get_modrinth

router = APIRouter()
_TYPE_PATTERN = "^(" + "|".join(PROJECT_TYPES) + ")$"
_SORT_PATTERN = "^(" + "|".join(SORT_INDEXES) + ")$"


class Project(BaseModel):
    project_id: str
    slug: str
    title: str
    description: str
    project_type: str = ""
    author: str = ""
    categories: list[str] = []
    downloads: int = 0
    follows: int = 0
    icon_url: str | None = None
    game_versions: list[str] = []
    loaders: list[str] = []
    gallery: list[str] = []


class SearchResponse(BaseModel):
    results: list[Project]
    total: int
    offset: int
    limit: int


class ProjectVersion(BaseModel):
    id: str
    project_id: str
    name: str
    version_number: str
    version_type: str
    game_versions: list[str]
    loaders: list[str]
    date_published: str
    downloads: int
    files: list[dict[str, Any]]


class InstalledContent(BaseModel):
    filename: str
    name: str
    enabled: bool
    size: int
    project_id: str
    version_id: str
    version_number: str
    icon_url: str


class InstallRequest(BaseModel):
    project_id: str = Field(..., min_length=1)
    version_id: str | None = None
    dependencies: bool = True


class LocalFileRequest(BaseModel):
    path: str


class ToggleRequest(BaseModel):
    enabled: bool


class World(BaseModel):
    name: str
    size: int
    last_played: str
    has_icon: bool
    path: str


def _project_from_hit(h: dict[str, Any]) -> Project:
    return Project(
        project_id=h["project_id"], slug=h.get("slug", ""), title=h.get("title", ""),
        description=h.get("description", ""), project_type=h.get("project_type", ""),
        author=h.get("author", ""), categories=h.get("display_categories") or h.get("categories", []),
        downloads=h.get("downloads", 0), follows=h.get("follows", 0), icon_url=h.get("icon_url"),
        game_versions=h.get("versions", []),
        loaders=[c for c in h.get("categories", []) if c in ("fabric", "forge", "quilt", "neoforge")],
    )


# --- Каталог Modrinth --------------------------------------------------------------
@router.get("/content/search", response_model=SearchResponse)
def search(
    project_type: str = Query("mod", pattern=_TYPE_PATTERN),
    query: str = "",
    game_version: str | None = None,
    loader: str | None = None,
    index: str = Query("relevance", pattern=_SORT_PATTERN),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    side: str = Query("client", pattern="^(client|server)$", description="Моды для клиента или для сервера"),
    category: str | None = Query(None, pattern="^[a-z0-9-]{1,40}$", description="Категория Modrinth"),
):
    data = get_modrinth().search(query, project_type, game_version, loader, limit, offset, index, side, category)
    return SearchResponse(
        results=[_project_from_hit(h) for h in data.get("hits", [])],
        total=data.get("total_hits", 0), offset=offset, limit=limit,
    )


@router.get("/content/projects/{project_id}", response_model=Project)
def get_project(project_id: str):
    p = get_modrinth().get_project(project_id)
    return Project(
        project_id=p["id"], slug=p.get("slug", ""), title=p.get("title", ""),
        description=p.get("description", ""), project_type=p.get("project_type", ""),
        categories=p.get("categories", []), downloads=p.get("downloads", 0),
        follows=p.get("followers", 0), icon_url=p.get("icon_url"),
        game_versions=p.get("game_versions", []), loaders=p.get("loaders", []),
        gallery=[g["url"] for g in p.get("gallery") or [] if g.get("url")][:6],
    )


@router.get("/content/projects/{project_id}/versions", response_model=list[ProjectVersion])
def get_project_versions(project_id: str, game_version: str | None = None, loader: str | None = None):
    versions = get_modrinth().get_project_versions(project_id, game_version, [loader] if loader else None)
    return [
        ProjectVersion(
            id=v["id"], project_id=v["project_id"], name=v.get("name", ""),
            version_number=v.get("version_number", ""), version_type=v.get("version_type", "release"),
            game_versions=v.get("game_versions", []), loaders=v.get("loaders", []),
            date_published=v.get("date_published", ""), downloads=v.get("downloads", 0),
            files=[{"filename": f["filename"], "size": f.get("size", 0), "primary": f.get("primary", False)}
                   for f in v.get("files", [])],
        )
        for v in versions
    ]


# --- Контент инстанса (content_type: mod | resourcepack | shader) -------------------


@router.get("/instances/{name}/content/{content_type}", response_model=list[InstalledContent])
def list_content(name: str, content_type: str):
    return ContentManager.list_installed(name, content_type)


@router.post("/instances/{name}/content/{content_type}", response_model=TaskResponse,
             status_code=status.HTTP_202_ACCEPTED)
def install_content(name: str, content_type: str, request: InstallRequest):
    InstanceManager.get(name)
    ContentManager.list_installed(name, content_type)  # валидация типа до запуска задачи

    def run(task):
        return ContentManager.install(name, content_type, request.project_id, request.version_id,
                                      task, request.dependencies)

    return task_manager.submit("content", f"Установка в «{name}»", run).to_dict()


@router.post("/instances/{name}/content/{content_type}/local")
def add_local_content(name: str, content_type: str, request: LocalFileRequest):
    return ContentManager.add_local_file(name, content_type, Path(request.path))


@router.patch("/instances/{name}/content/{content_type}/{filename}")
def toggle_content(name: str, content_type: str, filename: str, request: ToggleRequest):
    return ContentManager.set_enabled(name, content_type, filename, request.enabled)


@router.delete("/instances/{name}/content/{content_type}/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def remove_content(name: str, content_type: str, filename: str):
    ContentManager.remove(name, content_type, filename)


# --- Миры ------------------------------------------------------------------------------
@router.get("/instances/{name}/worlds", response_model=list[World])
def list_worlds(name: str):
    return ContentManager.list_worlds(name)


@router.post("/instances/{name}/worlds/import")
def import_world(name: str, request: LocalFileRequest):
    return ContentManager.import_world(name, Path(request.path))


@router.post("/instances/{name}/worlds/{world}/export")
def export_world(name: str, world: str, request: LocalFileRequest):
    return {"path": str(ContentManager.export_world(name, world, Path(request.path)))}


@router.delete("/instances/{name}/worlds/{world}", status_code=status.HTTP_204_NO_CONTENT)
def delete_world(name: str, world: str):
    ContentManager.delete_world(name, world)
