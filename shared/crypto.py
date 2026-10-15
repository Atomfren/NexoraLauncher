"""Шифрование секретов (shared).

Секреты (токены Microsoft/Minecraft) шифруются Fernet (AES-128-CBC + HMAC).
Ключ лежит в директории конфигурации пользователя, а не в исходниках:
- на Windows ключ дополнительно защищён DPAPI (привязан к учётной записи ОС);
- на Linux/macOS файл ключа доступен только владельцу (chmod 600).
"""

import os
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from shared.paths import get_config_dir

_DPAPI_PREFIX = b"DPAPI:"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Шифрует/расшифровывает данные через Windows DPAPI."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):  # noqa: N801 — имя из WinAPI
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = func(ctypes.byref(blob_in), None, None, None, None, 0x01, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class TokenVault:
    """Хранилище для шифрования строковых секретов."""

    _lock = threading.Lock()
    _cache: dict[Path, Fernet] = {}

    @staticmethod
    def _key_file() -> Path:
        return get_config_dir() / ".vault_key"

    @classmethod
    def _load_key(cls, key_file: Path) -> bytes:
        raw = key_file.read_bytes()
        if raw.startswith(_DPAPI_PREFIX):
            return _dpapi(raw[len(_DPAPI_PREFIX):], protect=False)
        return raw.strip()

    @classmethod
    def _store_key(cls, key_file: Path, key: bytes) -> None:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        payload = key
        if sys.platform == "win32":
            try:
                payload = _DPAPI_PREFIX + _dpapi(key, protect=True)
            except OSError:
                payload = key
        key_file.write_bytes(payload)
        if os.name != "nt":
            os.chmod(key_file, 0o600)

    @classmethod
    def _get_fernet(cls) -> Fernet:
        key_file = cls._key_file()
        with cls._lock:
            if key_file in cls._cache:
                return cls._cache[key_file]
            key = None
            if key_file.exists():
                try:
                    key = cls._load_key(key_file)
                    Fernet(key)
                except (OSError, ValueError):
                    key = None
            if key is None:
                key = Fernet.generate_key()
                cls._store_key(key_file, key)
            fernet = Fernet(key)
            cls._cache[key_file] = fernet
            return fernet

    @classmethod
    def encrypt(cls, value: str) -> str:
        """Шифрует строку. Пустая строка остаётся пустой."""
        if not value:
            return ""
        return cls._get_fernet().encrypt(value.encode("utf-8")).decode("ascii")

    @classmethod
    def decrypt(cls, encrypted_value: str) -> str:
        """Расшифровывает строку. При ошибке возвращает пустую строку."""
        if not encrypted_value:
            return ""
        try:
            return cls._get_fernet().decrypt(encrypted_value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""

    @classmethod
    def reset_cache(cls) -> None:
        """Сбрасывает кэш ключей (для тестов и смены NEXORA_HOME)."""
        with cls._lock:
            cls._cache.clear()
