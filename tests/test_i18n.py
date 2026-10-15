"""Полнота переводов: каждый ключ из кода есть в ru и en с одинаковыми параметрами."""

import re
import string
from pathlib import Path

from frontend.quick.catalog import CATEGORIES
from shared import i18n

ROOT = Path(__file__).resolve().parent.parent
_KEY_CALL = re.compile(r'(?<![\w.])t\("([a-z_]+\.[a-z_]+)"')
_KEY_LITERAL = re.compile(r'"((?:nav|browse|versions)\.[a-z_]+)"')
# Новый интерфейс: I18n.t("…") / I18n.tf("…") в QML и склоняемые ключи count(n, "q.…") → _one/_few/_many
_QML_KEY = re.compile(r'I18n\.tf?\("([a-z_]+\.[a-z_]+)"')
_PLURAL_BASE = re.compile(r'count\((?:[^,()]|\([^()]*\))+, *"([a-z_]+\.[a-z_]+)"')
# Ключи, собираемые динамически (f-строки)
_DYNAMIC_KEYS = (
    {f"process.{s}" for s in ("running", "exited", "crashed")}
    | {f"hosting.state_{s}" for s in ("running", "starting", "stopping", "stopped", "crashed", "not_installed")}
    | {f"hosting.gamemode_{s}" for s in ("survival", "creative", "adventure", "spectator")}
    | {f"hosting.difficulty_{s}" for s in ("peaceful", "easy", "normal", "hard")}
    | {f"hosting.prop_{s}" for s in ("gamemode", "difficulty", "pvp", "allow_flight", "hardcore", "white_list",
                                      "enable_command_block")}
    | {f"logs.level_{s}" for s in ("all", "errors", "warnings", "info")}
    | {f"logs.outcome_{s}" for s in ("crashed", "running", "loaded", "stopped", "unknown")}
    | {f"hosting.core_{s}" for s in ("fabric", "vanilla", "paper", "purpur")}
    | {f"hosting.backup_reason_{s}" for s in ("manual", "auto", "before_restore")}
    | {f"q.unit_{s}" for s in ("b", "kb", "mb", "gb")}
    | {"q.compact_k", "q.compact_m"}
    | {f"q.cat_{c.replace('-', '_')}" for cats in CATEGORIES.values() for c in cats}
)


def _used_keys() -> set[str]:
    keys = set(_DYNAMIC_KEYS)
    for path in (ROOT / "frontend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        keys |= set(_KEY_CALL.findall(text)) | set(_KEY_LITERAL.findall(text))
    for path in (ROOT / "frontend").rglob("*.qml"):
        keys |= set(_QML_KEY.findall(path.read_text(encoding="utf-8")))
    for path in [*(ROOT / "frontend").rglob("*.py"), *(ROOT / "frontend").rglob("*.qml")]:
        for base in _PLURAL_BASE.findall(path.read_text(encoding="utf-8")):
            keys |= {f"{base}_{form}" for form in ("one", "few", "many")}
    return keys


def _params(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_all_used_keys_translated():
    used = _used_keys()
    assert len(used) > 200
    for lang in ("ru", "en"):
        missing = sorted(k for k in used if k not in i18n._BUILTIN[lang])
        assert not missing, f"{lang}: нет переводов {missing}"


def test_languages_have_same_keys_and_params():
    ru, en = i18n._BUILTIN["ru"], i18n._BUILTIN["en"]
    assert set(ru) == set(en)
    for key in ru:
        assert _params(ru[key]) == _params(en[key]), key


def test_t_fallbacks():
    i18n.set_language("en")
    try:
        assert i18n.t("common.save") == "Save"
        assert i18n.t("home.greeting", name="Alex") == "Hi, Alex!"
        assert i18n.t("no.such.key") == "no.such.key"
        assert i18n.t("home.greeting") == "Hi, {name}!"
    finally:
        i18n.set_language("ru")
