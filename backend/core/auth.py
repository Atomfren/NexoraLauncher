"""Аккаунты: офлайн и Microsoft (Device Code → Xbox Live → XSTS → Minecraft).

Аккаунты хранятся в ``accounts.json`` в директории конфигурации; все токены
шифруются ``TokenVault``. Один аккаунт помечен активным — он используется при запуске.
"""

import hashlib
import os
import threading
import time
import uuid as uuidlib
from dataclasses import asdict, dataclass, fields
from typing import Any

import minecraft_launcher_lib as mll
import msal
from loguru import logger

from backend.core import nexora_account
from backend.core.errors import AuthRequiredError, BadRequestError, ExternalServiceError, NotFoundError
from backend.core.tasks import Task, task_manager
from shared.crypto import TokenVault
from shared.fsutil import atomic_write_json, read_json
from shared.paths import get_config_dir
from shared.version import MS_CLIENT_ID

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
    auth_type: str  # offline | microsoft | nexora
    access_token_enc: str = ""
    refresh_token_enc: str = ""
    expires_at: float = 0.0
    skin_url: str = ""
    # Плащ и модель скина приходят с сервера аккаунтов Nexora; у остальных типов пусто
    cape_url: str = ""
    skin_slim: bool = False
    email: str = ""
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
            "cape_url": self.cape_url,
            "email": self.email,
            "active": self.id == active_id,
            "expired": self.auth_type in ("microsoft", "nexora") and time.time() >= self.expires_at,
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
            removed = next((a for a in accounts if a.id == account_id), None)
            if removed is None:
                raise NotFoundError("Аккаунт не найден")
            remaining = [a for a in accounts if a.id != account_id]
            if active == account_id:
                active = remaining[0].id if remaining else ""
            AccountStore.save(remaining, active)
        # Выход на сервере — уже без блокировки: это сеть, и удаление от него не зависит
        if removed.auth_type == "nexora" and removed.access_token:
            nexora_account.logout(removed.access_token)

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

    # --- Nexora (свой сервер аккаунтов) --------------------------------------
    @staticmethod
    def _apply_profile(account: Account, profile: dict[str, Any]) -> Account:
        """Переносит в аккаунт то, что знает о нём сервер: ник, UUID, скин, плащ, почту."""
        account.username = str(profile.get("username") or account.username)
        account.uuid = str(profile.get("uuid") or account.uuid)
        account.skin_url = str(profile.get("skin_url") or "")
        account.cape_url = str(profile.get("cape_url") or "")
        account.skin_slim = profile.get("skin_model") == "slim"
        account.email = str(profile.get("email") or account.email)
        return account

    @staticmethod
    def _store(account: Account) -> Account:
        """Сохраняет изменения существующего аккаунта, не трогая выбор активного."""
        with _lock:
            accounts, active = AccountStore.load()
            AccountStore.save([account if a.id == account.id else a for a in accounts], active)
        return account

    @staticmethod
    def _nexora_account(session: dict[str, Any]) -> Account:
        profile = session.get("account") or {}
        username = str(profile.get("username") or "")
        if not username or not session.get("token"):
            raise ExternalServiceError("Сервер аккаунтов ответил без данных аккаунта")
        account = Account(id=uuidlib.uuid4().hex, username=username, uuid=offline_uuid(username),
                          auth_type="nexora", added_at=time.time())
        AuthManager._apply_profile(account, profile)
        account.set_tokens(session["token"], "", int(session.get("expires_in", 0)))
        return account

    @staticmethod
    def nexora_login(login: str, password: str) -> Account:
        """Вход по нику или почте на сервере аккаунтов Nexora."""
        account = AuthManager._nexora_account(nexora_account.login(login, password))
        logger.info(f"Аккаунт Nexora добавлен: {account.username}")
        return AuthManager._upsert(account)

    @staticmethod
    def nexora_register(username: str, email: str, password: str) -> Account:
        """Регистрация на сервере и сразу вход — пароль спрашиваем один раз."""
        account = AuthManager._nexora_account(nexora_account.register(username, email, password))
        logger.info(f"Аккаунт Nexora зарегистрирован: {account.username}")
        return AuthManager._upsert(account)

    @staticmethod
    def nexora_update(account: Account, profile: dict[str, Any]) -> Account:
        """Запомнить присланные сервером данные аккаунта (ник, скин, плащ) и сохранить их."""
        return AuthManager._store(AuthManager._apply_profile(account, profile))

    @staticmethod
    def nexora_token(account: Account) -> str:
        """Действующий токен сессии. Сессию, которой осталось меньше недели, продлеваем молча."""
        if account.auth_type != "nexora":
            raise BadRequestError("Это не аккаунт Nexora")
        token = account.access_token
        now = time.time()
        if not token or now >= account.expires_at:
            raise AuthRequiredError("Сессия Nexora истекла. Войдите в аккаунт заново.")
        if not nexora_account.needs_refresh(account.expires_at, now):
            return token
        try:
            session = nexora_account.refresh(token)
        except (ExternalServiceError, AuthRequiredError) as e:
            # Продление — не главное действие: пока токен жив, работаем с ним
            logger.debug(f"Сессия Nexora не продлена: {e}")
            return token
        account.set_tokens(session["token"], "", int(session.get("expires_in", 0)))
        AuthManager._apply_profile(account, session.get("account") or {})
        AuthManager._store(account)
        return session["token"]

    # --- Microsoft -----------------------------------------------------------
    @staticmethod
    def resolve_client_id(configured: str = "") -> str:
        """Client ID приложения Azure. По порядку: настройка игрока, окружение, сборка.

        Обычному игроку ничего указывать не нужно — работает встроенный в сборку.
        Своё значение нужно тем, кто собирает лаунчер сам или проверяет новое приложение
        до выпуска: Microsoft считает входы по приложению, и чужой Client ID брать нельзя.
        """
        return (configured or os.environ.get("NEXORA_MS_CLIENT_ID") or MS_CLIENT_ID).strip()

    @staticmethod
    def microsoft_available(configured: str = "") -> bool:
        """Есть ли чем входить. Окно аккаунтов спрашивает это, чтобы не предлагать пустую кнопку."""
        return bool(AuthManager.resolve_client_id(configured))

    @staticmethod
    def _msal_app(client_id: str) -> msal.PublicClientApplication:
        client_id = AuthManager.resolve_client_id(client_id)
        if not client_id:
            raise BadRequestError(
                "Вход через Microsoft в этой сборке недоступен: у лаунчера нет своего "
                "приложения Azure. Войдите через аккаунт Nexora или укажите свой Client ID "
                "в «Настройках → Аккаунт Microsoft»."
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
        """Обновляет токен Minecraft через refresh token Microsoft (или сессию Nexora)."""
        if account.auth_type == "nexora":
            token = AuthManager.nexora_token(account)
            AuthManager._apply_profile(account, nexora_account.profile(token))
            return AuthManager._store(account)
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
        # Аккаунт Nexora для самой игры — обычный офлайн-вход: лицензию он не заменяет,
        # а токен нашего сервера серверам Mojang ничего не говорит
        token = account.access_token if account.auth_type == "microsoft" else ""
        return {
            "username": account.username,
            "uuid": account.uuid,
            "token": token or "0",
            "auth_type": account.auth_type,
        }
