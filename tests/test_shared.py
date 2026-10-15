"""Тесты shared: файлы, шифрование, конфигурация."""

import json
import zipfile

import pytest

from shared.config import AppConfig
from shared.crypto import TokenVault
from shared.fsutil import (
    UnsafePathError,
    atomic_write_json,
    read_json,
    safe_extract_zip,
    safe_join,
    sanitize_name,
    validate_name,
)
from shared.paths import get_config_dir, get_instances_dir


@pytest.mark.parametrize("name", ["Survival", "Fabric 1.20.1", "Мой мир", "pack_(2)", "a.b"])
def test_validate_name_accepts(name):
    assert validate_name(name) == name


@pytest.mark.parametrize("name", ["", "..", "../evil", "a/b", "a\\b", "CON", "nul.txt", " lead", "dot.",
                                  "x" * 65, "bad:name", "q?"])
def test_validate_name_rejects(name):
    with pytest.raises(UnsafePathError):
        validate_name(name)


def test_sanitize_name():
    assert sanitize_name("Better MC [FORGE]: 1.20") == "Better MC [FORGE]_ 1.20"
    assert sanitize_name("...") == "Instance"


def test_safe_join_blocks_escape(tmp_path):
    assert safe_join(tmp_path, "a", "b") == (tmp_path / "a" / "b").resolve()
    with pytest.raises(UnsafePathError):
        safe_join(tmp_path, "..", "outside")


def test_safe_extract_zip_blocks_zip_slip(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ok/file.txt", "fine")
        zf.writestr("../../escape.txt", "bad")
    with zipfile.ZipFile(archive) as zf, pytest.raises(UnsafePathError):
        safe_extract_zip(zf, tmp_path / "out")
    assert not (tmp_path.parent / "escape.txt").exists()


def test_safe_extract_zip_strip_prefix(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("root/inner/x.txt", "x")
        zf.writestr("other.txt", "skip")
    with zipfile.ZipFile(archive) as zf:
        safe_extract_zip(zf, tmp_path / "out", strip_prefix="root/")
    assert (tmp_path / "out" / "inner" / "x.txt").read_text() == "x"
    assert not (tmp_path / "out" / "other.txt").exists()


def test_atomic_write_and_read_json(tmp_path):
    path = tmp_path / "x" / "data.json"
    atomic_write_json(path, {"a": 1})
    assert read_json(path) == {"a": 1}
    path.write_text("{broken", encoding="utf-8")
    assert read_json(path, default="fallback") == "fallback"


def test_paths_follow_nexora_home(nexora_home):
    assert get_config_dir() == nexora_home / "config"
    assert get_instances_dir() == nexora_home / "data" / "instances"


def test_token_vault_roundtrip(nexora_home):
    secret = "eyJhbGciOi.secret-token"
    encrypted = TokenVault.encrypt(secret)
    assert encrypted and secret not in encrypted
    assert TokenVault.decrypt(encrypted) == secret
    assert TokenVault.decrypt("garbage") == ""
    assert TokenVault.encrypt("") == ""
    assert (get_config_dir() / ".vault_key").exists()


def test_config_defaults_and_clamping():
    config = AppConfig(max_memory=100, min_memory=99999, language="de", appearance_mode="pink")
    assert config.max_memory == 512
    assert config.min_memory == 512
    assert config.language == "ru"
    assert config.appearance_mode == "dark"


def test_config_save_load_update():
    AppConfig().update(max_memory=6144, java_path="  /usr/bin/java ", unknown_field=1)
    loaded = AppConfig.load()
    assert loaded.max_memory == 6144
    assert loaded.java_path == "/usr/bin/java"


def test_config_migrates_v1_and_survives_corruption():
    path = get_config_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"window_width": 1600, "color_theme": "green", "_ms_client_id": "gAAAA",
                                "max_memory": 2048, "_schema_version": 1}), encoding="utf-8")
    config = AppConfig.load()
    assert config.game_width == 1600 and config.max_memory == 2048 and config.schema_version == 2
    path.write_text("not json", encoding="utf-8")
    assert AppConfig.load() == AppConfig()
