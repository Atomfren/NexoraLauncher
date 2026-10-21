"""Аккаунты: офлайн и Microsoft."""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from backend.core.auth import AuthManager
from backend.core.errors import NotFoundError
from shared.config import AppConfig

router = APIRouter()


class AccountResponse(BaseModel):
    id: str
    username: str
    uuid: str
    auth_type: str
    skin_url: str
    active: bool
    expired: bool


class OfflineLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=16)


class MicrosoftLoginStartResponse(BaseModel):
    task_id: str
    user_code: str
    verification_uri: str
    expires_in: int
    message: str


@router.get("/auth/accounts", response_model=list[AccountResponse])
def list_accounts():
    return AuthManager.list_accounts()


@router.get("/auth/profile", response_model=AccountResponse)
def get_active_account():
    """Активный аккаунт (404, если аккаунтов нет)."""
    account = AuthManager.get_active()
    if account is None:
        raise NotFoundError("Аккаунт не добавлен")
    return AuthManager.list_accounts_entry(account)


@router.post("/auth/offline/login", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def offline_login(request: OfflineLoginRequest):
    return AuthManager.list_accounts_entry(AuthManager.offline_login(request.username))


@router.post("/auth/microsoft/login/start", response_model=MicrosoftLoginStartResponse)
def microsoft_login_start():
    """Начинает вход по коду устройства. Завершение — по задаче ``task_id``."""
    return AuthManager.microsoft_login_start(AppConfig.load().ms_client_id)


@router.post("/auth/accounts/{account_id}/activate", response_model=AccountResponse)
def activate_account(account_id: str):
    return AuthManager.list_accounts_entry(AuthManager.set_active(account_id))


@router.post("/auth/accounts/{account_id}/refresh", response_model=AccountResponse)
def refresh_account(account_id: str):
    account = AuthManager.get(account_id)
    return AuthManager.list_accounts_entry(AuthManager.refresh(account, AppConfig.load().ms_client_id))


@router.delete("/auth/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_account(account_id: str):
    AuthManager.remove(account_id)



# --- Скин и плащ (3D-модель персонажа в лаунчере) ----------------------------------------
class SkinResponse(BaseModel):
    skin: str
    cape: str
    slim: bool
    source: str  # custom | mojang | default


class SkinFileRequest(BaseModel):
    path: str
    slim: bool = False


@router.get("/auth/accounts/{account_id}/skin", response_model=SkinResponse)
def get_skin(account_id: str):
    from backend.core import skins
    return skins.skin_info(account_id)


@router.put("/auth/accounts/{account_id}/skin", response_model=SkinResponse)
def put_skin(account_id: str, request: SkinFileRequest):
    from pathlib import Path

    from backend.core import skins
    return skins.set_custom_skin(account_id, Path(request.path), request.slim)


@router.put("/auth/accounts/{account_id}/cape", response_model=SkinResponse)
def put_cape(account_id: str, request: SkinFileRequest):
    from pathlib import Path

    from backend.core import skins
    return skins.set_custom_cape(account_id, Path(request.path))


@router.delete("/auth/accounts/{account_id}/skin", response_model=SkinResponse)
def reset_skin(account_id: str):
    from backend.core import skins
    return skins.reset_custom(account_id)
