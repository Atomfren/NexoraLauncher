"""Исключения бизнес-логики.

Обработчик в ``backend.main`` переводит их в HTTP-ответы с единым форматом
``{"detail": "..."}``, поэтому endpoints не оборачивают каждый вызов в try/except.
"""


class NexoraError(Exception):
    """Базовая ошибка лаунчера."""

    status_code = 500


class BadRequestError(NexoraError):
    status_code = 400


class AuthRequiredError(NexoraError):
    status_code = 401


class NotFoundError(NexoraError):
    status_code = 404


class ConflictError(NexoraError):
    status_code = 409


class ExternalServiceError(NexoraError):
    """Внешний сервис (Mojang, Modrinth, Microsoft) недоступен или вернул ошибку."""

    status_code = 502
