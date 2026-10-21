"""Settings API."""


from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.java_detector import find_java_installations
from shared.config import AppConfig
from shared.paths import get_data_dir, get_instances_dir, get_logs_dir, get_minecraft_dir
from shared.system import total_memory_mb

router = APIRouter()


class SettingsResponse(BaseModel):
    language: str
    appearance_mode: str
    java_path: str
    max_memory: int
    min_memory: int
    jvm_args: str
    game_width: int
    game_height: int
    fullscreen: bool
    ms_client_id: str
    last_instance: str
    hide_on_launch: bool
    check_updates: bool
    curseforge_key_set: bool = False


class SettingsUpdate(BaseModel):
    language: str | None = Field(None, pattern="^(ru|en)$")
    appearance_mode: str | None = Field(None, pattern="^(dark|light)$")
    java_path: str | None = None
    max_memory: int | None = Field(None, ge=512, le=65536)
    min_memory: int | None = Field(None, ge=256, le=65536)
    jvm_args: str | None = Field(None, max_length=2000)
    game_width: int | None = Field(None, ge=320, le=7680)
    game_height: int | None = Field(None, ge=240, le=4320)
    fullscreen: bool | None = None
    ms_client_id: str | None = Field(None, max_length=64)
    last_instance: str | None = None
    hide_on_launch: bool | None = None
    check_updates: bool | None = None
    # Ключ передаётся только на запись; хранится зашифрованным, наружу не отдаётся
    curseforge_api_key: str | None = Field(None, max_length=200)


class JavaInfo(BaseModel):
    path: str
    version: str
    major: int
    vendor: str
    is_64bit: bool


class SystemInfo(BaseModel):
    total_memory_mb: int
    data_dir: str
    instances_dir: str
    minecraft_dir: str
    logs_dir: str


def _public(config: AppConfig) -> dict:
    data = config.to_dict()
    data["curseforge_key_set"] = bool(data.pop("curseforge_key_enc", ""))
    return data


@router.get("/settings/", response_model=SettingsResponse)
def get_settings():
    return _public(AppConfig.load())


@router.patch("/settings/", response_model=SettingsResponse)
def update_settings(changes: SettingsUpdate):
    values = changes.model_dump(exclude_unset=True)
    if "curseforge_api_key" in values:
        from shared.crypto import TokenVault
        key = (values.pop("curseforge_api_key") or "").strip()
        values["curseforge_key_enc"] = TokenVault.encrypt(key) if key else ""
    config = AppConfig.load()
    if values.get("curseforge_key_enc") == "":
        config.curseforge_key_enc = ""  # update() пропускает пустые значения только для None
    return _public(config.update(**values))


@router.get("/settings/system", response_model=SystemInfo)
def get_system_info():
    return SystemInfo(
        total_memory_mb=total_memory_mb(), data_dir=str(get_data_dir()),
        instances_dir=str(get_instances_dir()), minecraft_dir=str(get_minecraft_dir()),
        logs_dir=str(get_logs_dir()),
    )


@router.get("/settings/java/", response_model=list[JavaInfo])
def detect_java():
    """Найденные установки Java."""
    return [j.__dict__ for j in find_java_installations()]
