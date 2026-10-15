"""API v1: агрегирование роутеров."""

from fastapi import APIRouter

from backend.api.v1 import (
    ai,
    app_update,
    auth,
    content,
    health,
    hosting,
    instances,
    logs,
    minecraft,
    modpacks,
    optifine,
    servers,
    settings,
    smart,
    tasks,
)

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(tasks.router, tags=["tasks"])
router.include_router(instances.router, tags=["instances"])
router.include_router(logs.router, tags=["logs"])
router.include_router(minecraft.router, tags=["minecraft"])
router.include_router(content.router, tags=["content"])
router.include_router(smart.router, tags=["smart"])
router.include_router(modpacks.router, tags=["modpacks"])
router.include_router(optifine.router, tags=["optifine"])
router.include_router(auth.router, tags=["auth"])
router.include_router(settings.router, tags=["settings"])
router.include_router(servers.router, tags=["servers"])
router.include_router(hosting.router, tags=["hosting"])
router.include_router(ai.router, tags=["ai"])
router.include_router(app_update.router, tags=["app"])
