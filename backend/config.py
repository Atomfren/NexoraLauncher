"""Backend конфигурация (переменные окружения NEXORA_BACKEND_*)."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.version import APP_NAME, APP_VERSION


class Settings(BaseSettings):
    """Конфигурация backend сервиса."""

    model_config = SettingsConfigDict(env_prefix="NEXORA_BACKEND_", env_file=".env",
                                      case_sensitive=False, extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    app_name: str = f"{APP_NAME} Backend"
    app_version: str = APP_VERSION

    # Токен доступа к API. Frontend генерирует его при старте и передаёт backend;
    # без него сторонние сайты в браузере могли бы обращаться к localhost API.
    api_token: str = ""

    # AI
    ai_model_path: str = ""
    ai_n_ctx: int = 4096
    ai_n_threads: int = 4

    log_level: str = "INFO"


settings = Settings()
