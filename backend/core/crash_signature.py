"""Отпечаток вылета: короткая подпись ошибки, которую игрок может отправить Доктору.

Зачем это нужно. «Доктор» силён не кодом, а числом разобранных случаев: чем больше
отпечатков ошибок и ответов «помогло / не помогло», тем точнее правила. Поэтому
лаунчер умеет отправить на сервер не лог целиком, а устойчивую подпись ошибки.

Правила, от которых нельзя отступать:

- **по умолчанию не отправляется ничего.** Никакой настройки «отправлять всегда» нет
  специально: согласие спрашивается каждый раз, и каждый раз человеку показывается
  ровно тот текст, который уйдёт (``preview`` → ``text``);
- **в отпечатке нет ничего, по чему можно узнать человека.** Чистка та же, что перед
  публикацией лога на mclo.gs (``log_analyzer.redact``), и сверх неё — ники аккаунтов
  лаунчера, почта, имя пользователя Windows, любые пути, UUID, ссылки и длинные
  шестнадцатеричные «хвосты» (это токены и хэши);
- **IP не отправляется и не нужен:** сервер его тоже не хранит (см. ``nexora-site/api``).

Что уходит на сервер, перечислено в ``_FIELDS`` — это же перечисление показывается
человеку перед отправкой и описано на странице сайта ``/bezopasnost/``.
"""

import getpass
import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from backend.core.errors import BadRequestError, ExternalServiceError
from shared.i18n import t
from shared.version import APP_VERSION, USER_AGENT

# Ручка приёма на сервере аккаунтов (PHP, nexora-site/api). Адрес подменяется
# переменной окружения NEXORA_API_URL — так же, как для аккаунтов.
_ENDPOINT = "/crash-signatures"
_TIMEOUT = httpx.Timeout(15.0, connect=6.0)
_MAX_LINE = 200
_MAX_SUSPECTS = 5

# Поля отпечатка в том порядке, в котором они показываются человеку и уходят на сервер
_FIELDS = ("signature", "launcher", "os", "minecraft", "loader", "loader_version", "java",
           "error_class", "error_line", "rule", "suspects", "mods", "outcome", "fix", "helped")

_EXCEPTION_RE = re.compile(r"\b(?:[a-z][\w$]*\.){1,}[A-Z][\w$]*(?:Exception|Error|Throwable)\b")
_JAVA_MAJOR_RE = re.compile(r"\b(?:1\.)?(\d{1,2})(?:[._]\d+)*\b")

# Чистка сверх redact(): всё, что бывает личным, но в логе выглядит как обычный текст
_SCRUB = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"[a-z]+://\S+"), "<url>"),
    # Пути: и Windows (C:\...), и UNC (\\host\...), и Unix (/home/..., ./mods/x.jar)
    (re.compile(r"\\\\[^\s\"']+"), "<path>"),
    (re.compile(r"\b[A-Za-z]:[\\/][^\s\"'<>|]*"), "<path>"),
    (re.compile(r"(?<![\w.])\.{0,2}/[\w.+-]+(?:/[\w.+-]*)+"), "<path>"),
    # Длинный шестнадцатеричный хвост — это токен, хэш или идентификатор сессии
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<id>"),
    (re.compile(r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{8,}\b"), "<id>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b"), "<ip>"),
    (re.compile(r"\s+"), " "),
]
# «Setting user: Ник» — ник в логе игры стоит открытым текстом даже без аккаунта в лаунчере
_USER_LINE = re.compile(r"(?i)\b(Setting user|username|player|user|nick(?:name)?|gamer ?tag)"
                        r"([\"'=: ]+)([^\s,;\"']{2,32})")


def _own_names() -> set[str]:
    """Имена, которые точно нельзя отправлять: ники и почта аккаунтов лаунчера,
    имя пользователя Windows и имя домашней папки."""
    names: set[str] = set()
    try:
        from backend.core.auth import AccountStore
        accounts, _active = AccountStore.load()
        for account in accounts:
            names.add(account.username)
            if account.email:
                names.add(account.email)
                names.add(account.email.split("@")[0])
    except Exception as error:  # noqa: BLE001 — чистка не должна падать из-за битого accounts.json
        logger.debug(f"Отпечаток вылета: список аккаунтов не прочитан: {error}")
    for value in (os.environ.get("USERNAME", ""), os.environ.get("USER", ""), Path.home().name):
        names.add(value)
    try:
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001 — в контейнере без пользователя getuser() падает
        pass
    return {n for n in names if len(n) >= 3}


def scrub(text: str, names: set[str] | None = None) -> str:
    """Убирает из строки всё личное: сначала как перед публикацией лога, затем ники,
    почту, пути, UUID, ссылки и длинные идентификаторы."""
    from backend.core.log_analyzer import redact

    cleaned = redact(text)
    for name in sorted(names if names is not None else _own_names(), key=len, reverse=True):
        cleaned = re.sub(rf"(?i){re.escape(name)}", "<player>", cleaned)
    cleaned = _USER_LINE.sub(r"\1\2<player>", cleaned)
    for pattern, replacement in _SCRUB:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned.strip()


def _java_major(java: str) -> str:
    """Из «OpenJDK 64-Bit Server VM, version 17.0.9+9» — только «17»: по версии сборки
    Java узнать человека нельзя, а для правил Доктора важен лишь старший номер."""
    # В сводке java — это «<название ВМ> <версия>», поэтому номер берём из последнего слова:
    # иначе «64-Bit» в названии притворится версией Java
    match = _JAVA_MAJOR_RE.search(java.split()[-1] if java.split() else "")
    return match.group(1) if match else ""


def _error_of(entries: list[Any]) -> tuple[str, str, str]:
    """Класс исключения, ключевая строка и вид правила Доктора у первой настоящей ошибки."""
    from backend.core.log_analyzer import hint_key

    for entry in entries:
        if entry.level != "ERROR" or entry.noise:
            continue
        blob = "\n".join([entry.message, *entry.extra[:12]])
        match = _EXCEPTION_RE.search(blob)
        line = entry.message
        if match and match.group(0) not in line:
            # Сообщение вида «Uncaught exception», а класс — в приклеенном стек-трейсе
            line = next((x for x in entry.extra[:12] if match.group(0) in x), line)
        # «loghint.memory» → «memory»: имён файлов и модов в виде правила нет
        return (match.group(0) if match else ""), line, hint_key(blob).split(".")[-1]
    return "", "", ""


def _fingerprint(parts: list[str]) -> str:
    """Короткий устойчивый идентификатор подписи: одинаковые вылеты у разных людей
    дают одинаковую строку, поэтому сервер может их просто считать."""
    blob = "|".join(re.sub(r"\d+", "#", p.lower()) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def build(instance_name: str, source_id: str = "", helped: bool | None = None,
          fix_action: str = "") -> dict[str, Any]:
    """Собирает отпечаток последнего вылета. Ничего не отправляет."""
    from backend.core import log_analyzer
    from backend.core.instance import InstanceManager

    instance = InstanceManager.get(instance_name)
    text, source = log_analyzer.read_source(instance_name, source_id)
    if not text.strip():
        raise BadRequestError(t("diag.sig_no_log"))
    entries = log_analyzer.parse(text)
    summary = log_analyzer.summarize(text, entries, instance, source)
    names = _own_names()
    error_class, error_line, rule = _error_of(entries)
    if not error_class and not error_line:
        raise BadRequestError(t("diag.sig_no_error"))

    suspects = [s for s in summary["suspects"][:_MAX_SUSPECTS]
                if not any(n.lower() in s.lower() for n in names)]
    signature = {
        "launcher": APP_VERSION,
        "os": platform.system().lower(),
        "minecraft": summary["minecraft"],
        "loader": summary["loader"] or "vanilla",
        "loader_version": summary["loader_version"],
        "java": _java_major(summary["java"]),
        "error_class": scrub(error_class, names)[:120],
        "error_line": scrub(error_line, names)[:_MAX_LINE],
        # Правило Доктора — только его вид (memory, mixin, gpu…), без имён файлов
        "rule": rule,
        "suspects": suspects,
        "mods": int(summary["mods"] or 0),
        "outcome": summary["outcome"],
        "fix": fix_action,
        "helped": helped,
    }
    signature["signature"] = _fingerprint([signature["error_class"], signature["error_line"],
                                           signature["loader"], signature["minecraft"], signature["java"],
                                           ",".join(suspects)])
    return {key: signature[key] for key in _FIELDS}


def preview(instance_name: str, source_id: str = "", helped: bool | None = None,
            fix_action: str = "") -> dict[str, Any]:
    """Что уйдёт на сервер, если человек согласится: сам отпечаток и его текст —
    ровно тот, который отправится."""
    signature = build(instance_name, source_id, helped, fix_action)
    return {"signature": signature, "fields": list(_FIELDS),
            "text": json.dumps(signature, ensure_ascii=False, indent=2)}


def send(instance_name: str, consent: bool, source_id: str = "", helped: bool | None = None,
         fix_action: str = "") -> dict[str, Any]:
    """Отправляет отпечаток. Без явного согласия — отказ: тихой отправки не бывает."""
    if not consent:
        raise BadRequestError(t("diag.sig_no_consent"))
    signature = build(instance_name, source_id, helped, fix_action)
    from backend.core.nexora_account import base_url

    try:
        with httpx.Client(base_url=base_url(), headers={"User-Agent": USER_AGENT},
                          timeout=_TIMEOUT, follow_redirects=True) as client:
            response = client.post(_ENDPOINT, json=signature)
    except httpx.HTTPError as error:
        logger.debug(f"Отпечаток вылета не отправлен: {error}")
        raise ExternalServiceError(t("diag.sig_offline")) from error
    if response.status_code >= 400:
        raise ExternalServiceError(t("diag.sig_rejected", code=response.status_code))
    return {"sent": True, "signature": signature["signature"], "helped": helped}
