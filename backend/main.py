"""FastAPI приложение NexoraLauncher Backend.

Запуск отдельно: ``python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000``
"""

import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from loguru import logger  # noqa: E402

from backend.api.v1 import router as api_v1_router  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.core.errors import NexoraError  # noqa: E402
from backend.core.tasks import task_manager  # noqa: E402
from shared.paths import ensure_directories, get_logs_dir  # noqa: E402

TOKEN_HEADER = "X-Nexora-Token"
_PUBLIC_PATHS = {"/", "/api/v1/health", "/api/v1/ping"}


_log_handler_id: int | None = None


def _setup_logging() -> None:
    global _log_handler_id
    if _log_handler_id is not None:
        return
    _log_handler_id = logger.add(
        str(get_logs_dir() / "backend.log"), level="DEBUG" if settings.debug else settings.log_level,
        rotation="5 MB", retention=5, encoding="utf-8", enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    _setup_logging()
    logger.info(f"{settings.app_name} v{settings.app_version} запущен")
    from backend.core.instance import InstanceManager
    InstanceManager.purge_leftovers()  # остатки прерванных удалений сборок
    yield
    from backend.core.hosting import HostingManager
    HostingManager.stop_all()  # серверы корректно сохраняют миры при выходе
    task_manager.shutdown()
    logger.info("Backend остановлен")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="REST API лаунчера NexoraLauncher",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug or not settings.api_token else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        """Проверка токена доступа (если он задан)."""
        if settings.api_token and request.url.path not in _PUBLIC_PATHS \
                and request.method != "OPTIONS":
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not secrets.compare_digest(supplied, settings.api_token):
                return JSONResponse(status_code=401, content={"detail": "Неверный токен доступа"})
        return await call_next(request)

    @app.exception_handler(NexoraError)
    async def nexora_error_handler(request: Request, exc: NexoraError):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        messages = []
        for err in exc.errors():
            location = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
            messages.append(f"{location}: {err.get('msg')}" if location else err.get("msg", ""))
        return JSONResponse(status_code=422, content={"detail": "; ".join(messages), "errors": exc.errors()})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception(f"Необработанная ошибка {request.method} {request.url.path}: {exc}")
        return JSONResponse(status_code=500, content={"detail": f"Внутренняя ошибка: {exc}"})

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": settings.app_name, "version": settings.app_version}

    app.include_router(api_v1_router, prefix="/api/v1")
    return app


app = create_app()
