"""Логирование frontend (в директорию логов пользователя)."""

import sys

from loguru import logger

from shared.paths import get_logs_dir

_configured = False


def setup_logging(debug: bool = False) -> None:
    """Настраивает вывод в консоль и файл ``frontend.log``. Вызывается один раз."""
    global _configured
    if _configured:
        return
    _configured = True
    logger.remove()
    if sys.stdout is not None:  # в сборке без консоли stdout отсутствует
        logger.add(sys.stdout, level="DEBUG" if debug else "INFO", colorize=True,
                   format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
                          "<cyan>{name}</cyan> — <level>{message}</level>")
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(str(logs_dir / "frontend.log"), level="DEBUG", rotation="5 MB", retention=5,
               encoding="utf-8", enqueue=True,
               format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}")


__all__ = ["logger", "setup_logging"]
