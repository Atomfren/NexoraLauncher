"""Аккаунты: офлайн и Microsoft (Device Code → Xbox Live → XSTS → Minecraft).

Аккаунты хранятся в ``accounts.json`` в директории конфигурации; все токены
шифруются ``TokenVault``. Один аккаунт помечен активным — он используется при запуске.
"""

import hashlib
import threading
import time
import uuid as uuidlib
from dataclasses import asdict, dataclass, fields
from typing import Any

import minecraft_launcher_lib as mll
import msal
from loguru import logger

from backend.core.errors import AuthRequiredError, BadRequestError, ExternalServiceError, NotFoundError
from backend.core.tasks import Task, task_manager
from shared.crypto import TokenVault
from shared.fsutil import atomic_write_json, read_json
from shared.paths import get_config_dir

_AUTHORITY = "https://login.microsoftonline.com/consumers"
_SCOPES = ["XboxLive.signin"]
_XSTS_ERRORS = {
    2148916233: "У этой учётной записи Microsoft нет профиля Xbox. Войдите на xbox.com и создайте его.",
    2148916235: "Xbox Live недоступен в вашей стране.",
    2148916236: "Требуется подтверждение возраста на xbox.com.",
    2148916237: "Требуется подтверждение возраста на xbox.com.",
    2148916238: "Детская учётная запись: добавьте её в семейную группу Microsoft.",
}
_lock = threading.RLock()


def offline_uuid(username: str) -> str:
    """UUID офлайн-игрока по алгоритму сервера Minecraft (MD5 'OfflinePlayer:<name>', v3)."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(digest)))


@dataclass
class Account:
    """Аккаунт игрока. Поля ``*_enc`` хранятся зашифрованными."""

    id: str
    username: str
    uuid: str
    auth_type: str  # offline | microsoft
    access_token_enc: str = ""
    refresh_token_enc: str = ""
    expires_at: float = 0.0
    skin_url: str = ""
    added_at: float = 0.0

    @property
    def access_token(self) -> str:
        return TokenVault.decrypt(self.access_token_enc)

    @property
    def refresh_token(self) -> str:
        return TokenVault.decrypt(self.refresh_token_enc)

    def set_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        self.access_token_enc = TokenVault.encrypt(access_token)
        if refresh_token:
            self.refresh_token_enc = TokenVault.encrypt(refresh_token)
        self.expires_at = time.time() + max(0, int(expires_in)) - 300

    def public(self, active_id: str = "") -> dict[str, Any]:
        """Данные для API — без токенов."""
        return {
            "id": self.id,
            "username": self.username,
            "uuid": self.uuid,
            "auth_type": self.auth_type,
            "skin_url": self.skin_url,
            "active": self.id == active_id,
            "expired": self.auth_type == "microsoft" and time.time() >= self.expires_at,
        }


class AccountStore:
    """Чтение/запись accounts.json."""

    @staticmethod
    def _path():
        return get_config_dir() / "accounts.json"

    @classmethod
    def _migrate_legacy_profile(cls) -> None:
        """Переносит profile.json версии 0.x (токены в открытом виде) и удаляет его."""
        legacy = get_config_dir() / "profile.json"
        if not legacy.exists() or cls._path().exists():
            return
        data = read_json(legacy, default={})
        if isinstance(data, dict) and data.get("auth_type") == "offline" and data.get("username"):
            name = str(data["username"])
            account = Account(id=uuidlib.uuid4().hex, username=name, uuid=offline_uuid(name),
                              auth_type="offline", added_at=time.time())
            cls.save([account], account.id)
            logger.info(f"Офлайн-аккаунт '{name}' перенесён из profile.json")
        legacy.unlink(missing_ok=True)

    @classmethod
    def load(cls) -> tuple[list[Account], str]:
        cls._migrate_legacy_profile()
        data = read_json(cls._path(), default={})
        if not isinstance(data, dict):
            data = {}
        known = {f.name for f in fields(Account)}
        accounts = []
        for item in data.get("accounts", []):
            try:
                accounts.append(Account(**{k: v for k, v in item.items() if k in known}))
            except TypeError:
                continue
        active = data.get("active", "")
        if accounts and active not in {a.id for a in accounts}:
            active = accounts[0].id
        return accounts, active

    @classmethod
    def save(cls, accounts: list[Account], active: str) -> None:
        atomic_write_json(cls._path(), {"active": active, "accounts": [asdict(a) for a in accounts]})


class AuthManager:
    """Операции с аккаунтами."""

    # --- Список / выбор ----------------------------------------------------
    @staticmethod
    def list_accounts() -> list[dict[str, Any]]:
        accounts, active = AccountStore.load()
        return [a.public(active) for a in accounts]

    @staticmethod
    def get_active() -> Account | None:
        accounts, active = AccountStore.load()
        return next((a for a in accounts if a.id == active), None)

    @staticmethod
    def get(account_id: str) -> Account:
        accounts, _ = AccountStore.load()
        account = next((a for a in accounts if a.id == account_id), None)
        if account is None:
            raise NotFoundError("Аккаунт не найден")
        return account

    @staticmethod
    def set_active(account_id: str) -> Account:
        with _lock:
            accounts, _ = AccountStore.load()
            account = next((a for a in accounts if a.id == account_id), None)
            if account is None:
                raise NotFoundError("Аккаунт не найден")
            AccountStore.save(accounts, account_id)
            return account

    @staticmethod
    def remove(account_id: str) -> None:
        with _lock:
            accounts, active = AccountStore.load()
            remaining = [a for a in accounts if a.id != account_id]
            if len(remaining) == len(accounts):
                raise NotFoundError("Аккаунт не найден")
            if active == account_id:
                active = remaining[0].id if remaining else ""
            AccountStore.save(remaining, active)

    @staticmethod
    def _upsert(account: Account) -> Account:
        """Добавляет аккаунт (или обновляет существующий с тем же UUID) и делает активным."""
        with _lock:
            accounts, _ = AccountStore.load()
            for i, existing in enumerate(accounts):
                if existing.uuid == account.uuid and existing.auth_type == account.auth_type:
                    account.id = existing.id
                    account.added_at = existing.added_at
                    accounts[i] = account
                    break
            else:
                accounts.append(account)
            AccountStore.save(accounts, account.id)
            return account

    # --- Офлайн --------------------------------------------------------------
    @staticmethod
    def offline_login(username: str) -> Account:
        username = username.strip()
        if not (3 <= len(username) <= 16) or not all(c.isalnum() or c == "_" for c in username) \
                or not username.isascii():
            raise BadRequestError("Ник: 3–16 символов, латиница, цифры и «_»")
        account = Account(id=uuidlib.uuid4().hex, username=username, uuid=offline_uuid(username),
                          auth_type="offline", added_at=time.time())
        return AuthManager._upsert(account)

    # --- Microsoft -----------------------------------------------------------
    @staticmethod
    def _msal_app(client_id: str) -> msal.PublicClientApplication:
        if not client_id:
            raise BadRequestError(
                "Не задан Azure Client ID. Укажите его в Настройках → Аккаунт Microsoft."
            )
        return msal.PublicClientApplication(client_id, authority=_AUTHORITY)

    @staticmethod
    def _minecraft_login(ms_access_token: str) -> dict[str, Any]:
        """Xbox Live → XSTS → Minecraft. Возвращает профиль + токен Minecraft."""
        try:
            xbl = mll.microsoft_account.authenticate_with_xbl(ms_access_token)
            xbl_token = xbl["Token"]
            userhash = xbl["DisplayClaims"]["xui"][0]["uhs"]
            xsts = mll.microsoft_account.authenticate_with_xsts(xbl_token)
            if "XErr" in xsts:
                raise ExternalServiceError(_XSTS_ERRORS.get(xsts["XErr"], f"Ошибка Xbox Live: {xsts['XErr']}"))
            mc = mll.microsoft_account.authenticate_with_minecraft(userhash, xsts["Token"])
        except ExternalServiceError:
            raise
        except (KeyError, IndexError, ValueError, OSError) as e:
            raise ExternalServiceError(f"Ошибка авторизации Xbox Live: {e}") from e
        if "access_token" not in mc:
            raise ExternalServiceError(
                "Azure-приложению не выдан доступ к Minecraft API. "
                "Подайте заявку: https://aka.ms/mce-reviewappid"
            )
        profile = mll.microsoft_account.get_profile(mc["access_token"])
        if profile.get("error") == "NOT_FOUND" or "id" not in profile:
            raise ExternalServiceError("На этом аккаунте Microsoft нет лицензии Minecraft Java Edition.")
        profile["mc_access_token"] = mc["access_token"]
        profile["mc_expires_in"] = mc.get("expires_in", 86400)
        return profile

    @staticmethod
    def _account_from_profile(profile: dict[str, Any], refresh_token: str) -> Account:
        raw = profile["id"]
        mc_uuid = str(uuidlib.UUID(raw)) if len(raw) == 32 else raw
        skins = profile.get("skins") or []
        account = Account(id=uuidlib.uuid4().hex, username=profile["name"], uuid=mc_uuid,
                          auth_type="microsoft", added_at=time.time(),
                          skin_url=skins[0].get("url", "") if skins else "")
        account.set_tokens(profile["mc_access_token"], refresh_token, profile["mc_expires_in"])
        return account

    @staticmethod
    def microsoft_login_start(client_id: str) -> dict[str, Any]:
        """Начинает вход по коду устройства. Возвращает код и ID задачи ожидания."""
        app = AuthManager._msal_app(client_id)
        flow = app.initiate_device_flow(scopes=_SCOPES)
        if "user_code" not in flow:
            raise ExternalServiceError(flow.get("error_description", "Не удалось начать вход Microsoft"))

        def wait_for_user(task: Task) -> dict[str, Any]:
            task.set_status("Ожидание подтверждения в браузере…")
            flow["expires_at"] = time.time() + int(flow.get("expires_in", 900))
            result = app.acquire_token_by_device_flow(
                flow, exit_condition=lambda f: task._cancel.is_set() or time.time() > f["expires_at"]
            )
            task.check_cancelled()
            if "access_token" not in result:
                raise ExternalServiceError(result.get("error_description", "Вход Microsoft не завершён"))
            task.set_status("Вход в Xbox Live и Minecraft…")
            profile = AuthManager._minecraft_login(result["access_token"])
            account = AuthManager._account_from_profile(profile, result.get("refresh_token", ""))
            account = AuthManager._upsert(account)
            logger.info(f"Microsoft-аккаунт добавлен: {account.username}")
            return AuthManager.list_accounts_entry(account)

        task = task_manager.submit("microsoft_login", "Вход в аккаунт Microsoft", wait_for_user)
        return {
            "task_id": task.id,
            "user_code": flow["user_code"],
            "verification_uri": flow["verification_uri"],
            "expires_in": int(flow.get("expires_in", 900)),
            "message": flow.get("message", ""),
        }

    @staticmethod
    def list_accounts_entry(account: Account) -> dict[str, Any]:
        _, active = AccountStore.load()
        return account.public(active)

    @staticmethod
    def refresh(account: Account, client_id: str) -> Account:
        """Обновляет токен Minecraft через refresh token Microsoft."""
        if account.auth_type != "microsoft":
            return account
        refresh_token = account.refresh_token
        if not refresh_token:
            raise AuthRequiredError("Сессия Microsoft истекла. Войдите в аккаунт заново.")
        app = AuthManager._msal_app(client_id)
        result = app.acquire_token_by_refresh_token(refresh_token, scopes=_SCOPES)
        if "access_token" not in result:
            raise AuthRequiredError(
                f"Сессия Microsoft истекла, войдите заново ({result.get('error_description', 'refresh failed')})"
            )
        profile = AuthManager._minecraft_login(result["access_token"])
        fresh = AuthManager._account_from_profile(profile, result.get("refresh_token") or refresh_token)
        fresh.id = account.id
        fresh.added_at = account.added_at
        with _lock:
            accounts, active = AccountStore.load()
            accounts = [fresh if a.id == account.id else a for a in accounts]
            AccountStore.save(accounts, active)
        return fresh

    @staticmethod
    def get_launch_credentials(client_id: str) -> dict[str, str]:
        """Данные для запуска игры активным аккаунтом (с обновлением токена)."""
        account = AuthManager.get_active()
        if account is None:
            raise AuthRequiredError("Добавьте аккаунт, чтобы играть (офлайн или Microsoft).")
        if account.auth_type == "microsoft" and time.time() >= account.expires_at:
            account = AuthManager.refresh(account, client_id)
        return {
            "username": account.username,
            "uuid": account.uuid,
            "token": account.access_token or "0",
            "auth_type": account.auth_type,
        }
