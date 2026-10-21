"""Умные логи: разбор логов игры, сводка, проблемы с исправлениями и публикация на mclo.gs.

Что делает:
- собирает все логи инстанса: сеансы запуска (``logs/``), ``latest.log`` игры и отчёты о сбоях;
- разбирает строки форматов Vanilla / Fabric / Quilt / Forge / NeoForge / log4j в записи
  (время, поток, уровень, источник, сообщение), склеивает стек-трейсы с их записью
  и схлопывает одинаковые повторы;
- помечает «шум» — известные безвредные предупреждения, которые пугают, но ни на что не влияют;
- угадывает мод — виновника ошибки (по тегу логгера, Mixin и пакетам в стек-трейсе);
- собирает сводку: версия игры и загрузчика, число модов, Java, время загрузки, исход сеанса;
- находит проблемы правилами Доктора — с кнопками исправления;
- публикует лог на mclo.gs (стандарт сообщества Minecraft), предварительно убирая личные данные.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from backend.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from backend.core.instance import Instance, InstanceManager
from backend.core.process_manager import process_manager
from shared.fsutil import UnsafePathError, safe_join, validate_name
from shared.i18n import t
from shared.version import USER_AGENT

MCLOGS_API = "https://api.mclo.gs/1/log"
_MAX_READ = 3 * 1024 * 1024  # анализируем последние 3 МБ лога
_MAX_ENTRIES = 6000
_MAX_SHARE_LINES = 25000
_SESSIONS_LIMIT = 40

# [12:00:00] [Render thread/INFO]: msg
# [12:00:00] [main/INFO] (FabricLoader) msg
# [13Oct2026 12:00:00.123] [main/INFO] [cpw.mods.modlauncher.Launcher/MODLAUNCHER]: msg
_LINE_RE = re.compile(
    r"^\[(?P<time>[^\]]{5,40})\] \[(?P<thread>.+?)/(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL)\]"
    r"(?: \[(?P<logger>[^\]]*)\]| \((?P<logger2>[^)]*)\))?:? ?(?P<msg>.*)$")
# 2026-10-13T17:09:45.765Z main WARN msg (служебный вывод log4j)
_LOG4J_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z? (?P<thread>\S+) (?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL) "
                       r"(?P<msg>.*)$")
_CONTINUATION_RE = re.compile(r"^(?:\s+at |\s*\.\.\. \d+ more|Caused by:|\s+Suppressed:|\t|\s{2,}\S)")
_EXCEPTION_RE = re.compile(r"^(?:[a-z][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable)\b")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")
_FRAME_RE = re.compile(r"^\s+at (?:[\w.$]+/)?(?P<cls>[\w.$]+)\.[\w$<>]+\(")

# Известный безвредный шум
_NOISE = [re.compile(p) for p in (
    r"Missing sound for event",
    r"Ambiguity between arguments",
    r"Unable to load font|Couldn't load font",
    r"Shader .* could not find (?:sampler|uniform) named",
    r"Narrator library|Failed to load library.*narrator",
    r"Reference map '.*' for .* could not be read",
    r"Unknown custom packet identifier",
    r"Failed to verify authentication|Couldn't connect to realms|Realms: ",
    r"\(Reflector\) (?:Class|Method|Field) not present",
    r"Using missing texture, unable to load",
    r"Datafixer optimizations took",
    r"Received passengers for unknown entity",
    r"The use of package scanning to locate Log4j plugins is deprecated|Please remove the `packages` attribute|"
    r"See https://logging.apache.org",
    r"Telemetry|telemetry",
    r"Found non-pack entry",
    r"Couldn't parse data file .* from .* minecraft:.*recipes?",
    r"Unable to resolve texture due to upward reference",
    r"Configured shader .* is not valid",
    r"Error loading class: .*\(java\.lang\.ClassNotFoundException",
    r"Loaded \d+ (?:recipes|advancements)",
    r"Unable to play empty soundEvent",
)]
# Ошибки сервисов Mojang (Realms, ключи профиля, скины): при офлайн-аккаунте или без интернета
# они идут даже с уровнем ERROR, но на игру не влияют
_SERVICE_NOISE = re.compile(
    r"Failed to fetch user properties|Failed to fetch Realms feature flags|Couldn't connect to realms|"
    r"Failed to retrieve profile key pair|Services are unavailable|Couldn't look up profile properties|"
    r"Failed to verify authentication|Failed to fetch (?:the )?(?:player )?(?:profile|textures|skin)|"
    r"Failed to load Realms|Realms is not available")

# Пояснения к частым ошибкам — простым языком. Хранятся ключи словаря (loghint.*):
# текст берётся при разборе лога, на текущем языке интерфейса.
_HINTS: list[tuple[re.Pattern[str], str]] = [(re.compile(p, re.I), key) for p, key in (
    (r"OutOfMemoryError", "loghint.memory"),
    (r"Mixin apply .* failed|MixinApplyError|InvalidInjectionException|MixinTransformerError", "loghint.mixin"),
    (r"NoClassDefFoundError|ClassNotFoundException", "loghint.class_missing"),
    (r"NoSuchMethodError|NoSuchFieldError|AbstractMethodError|IncompatibleClassChangeError", "loghint.method_missing"),
    (r"UnsupportedClassVersionError|class file version", "loghint.java_version"),
    (r"GLFW error|OpenGL|Pixel format not accelerated|WGL_ARB", "loghint.gpu"),
    (r"Couldn't connect to server|Connection refused|ConnectException", "loghint.connect"),
    (r"timed out|UnknownHostException|Network is unreachable", "loghint.network"),
    (r"Invalid session|Failed to login|Not authenticated", "loghint.login"),
    (r"Can't keep up! Is the server overloaded", "loghint.overloaded"),
    (r"ZipException|zip END header|invalid LOC header|Failed to read .*\.jar", "loghint.corrupt_jar"),
    (r"Duplicate mod|DuplicateModsFoundException|Found duplicate mods", "loghint.duplicate"),
    (r"Failed to (?:load|parse) (?:texture|model|resource)|Unable to load model|Missing model", "loghint.resource"),
    (r"Exception ticking world|Ticking (?:entity|block entity)", "loghint.ticking"),
    (r"Failed to (?:load|save) (?:level|chunk|world)|Chunk file at .* is in the wrong location|RegionFile",
     "loghint.world_corrupt"),
    (r"StackOverflowError", "loghint.stack_overflow"),
    (r"Shader compilation failed|Failed to compile shader|shaderpack", "loghint.shader"),
)]

# Мод в теге логгера и в сообщениях
_MOD_HINTS = [
    re.compile(r"\[from mod (?P<id>[\w.\-]+)\]"),
    re.compile(r"Mixin apply for mod (?P<id>[\w.\-]+) failed"),
    re.compile(r"mixins?\.json:\S+ from mod (?P<id>[\w.\-]+)"),
    re.compile(r"[Mm]od '?(?:[^'(]*)'? \((?P<id>[\w.\-]+)\)"),
]
_GENERIC_PARTS = {"minecraft", "net", "com", "org", "io", "dev", "me", "java", "jdk", "sun", "lang", "util",
                  "fabric", "fabricmc", "quilt", "quiltmc", "forge", "minecraftforge", "neoforged", "neoforge",
                  "api", "impl", "core", "common", "client", "server", "mixin", "mixins", "spongepowered",
                  "lib", "libs", "internal", "loader", "launch", "main", "mod", "mods", "github",
                  "world", "render", "entity", "block", "item", "event", "events", "cpw", "modlauncher",
                  "mojang", "blaze3d", "lwjgl", "optifine", "base", "data", "registry", "network"}

# Сводка
_SUMMARY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("fabric", re.compile(r"Loading Minecraft (?P<mc>\S+) with Fabric Loader (?P<loader>\S+)")),
    ("quilt", re.compile(r"Loading Minecraft (?P<mc>\S+) with Quilt Loader (?P<loader>\S+)")),
    ("forge", re.compile(r"(?:Forge mod loading, version|ModLauncher running: .*?--fml\.forgeVersion,?) "
                         r"(?P<loader>[\d.]+).*?(?:for MC|--fml\.mcVersion,?) (?P<mc>[\d.]+)")),
    ("neoforge", re.compile(r"NeoForge mod loading, version (?P<loader>\S+), for MC (?P<mc>\S+)|"
                            r"--fml\.neoForgeVersion,? (?P<loader2>[\w.\-]+)")),
]
_MODS_COUNT = re.compile(r"Loading (?P<n>\d+) mods:|Found (?P<n2>\d+) mods? (?:files|to load)")
_JAVA = re.compile(r"Java is (?P<vm>[^,]+), version (?P<ver>[\w.\-+]+)|JVM identified as (?P<vm2>.+?) "
                   r"(?P<ver2>\d[\w.\-+]*)|Running with Java (?P<ver3>[\w.\-+]+)")
_RENDERER = re.compile(r"(?:Backend library|Backend API): (?P<v>[^\n]+)|OpenGL: (?P<gl>[^\n]+)|"
                       r"GL Renderer: (?P<gl2>[^\n]+)")
_OPTIFINE = re.compile(r"OptiFine_[\d.]+_(?P<ed>[A-Z0-9_]+)")
_READY = re.compile(r"Sound engine started|Created: \d+x\d+x\d+ minecraft:textures/atlas/blocks|"
                    r"Sound engine started|Narrator is not available")
_CRASHED = re.compile(r"---- Minecraft Crash Report ----|#@!@# Game crashed!|Game crashed! Crash report|"
                      r"Unable to launch|Exception in thread \"main\"|Preparing crash report|"
                      r"Encountered an unexpected exception|java.lang.OutOfMemoryError|"
                      r"Uncaught exception in (?:render|main|Render) thread")
_STOPPED = re.compile(r"\]: Stopping!|Stopping worker threads")
_CRASH_DESCRIPTION = re.compile(r"^Description: (?P<d>.+)$", re.MULTILINE)

# Что вычищается перед публикацией
_REDACT = [
    (re.compile(r"(--accessToken|--session|--clientId|--xuid)\s+\S+"), r"\1 <скрыто>"),
    (re.compile(r"(?i)\b(access[_-]?token|session[_-]?id|token)([\"'=: ]+)[\w.\-]{20,}"), r"\1\2<скрыто>"),
    (re.compile(r"(?i)([A-Z]:[\\/]+Users[\\/]+)[^\\/\s]+"), r"\1<user>"),
    (re.compile(r"(/home/|/Users/)[^/\s]+"), r"\1<user>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b(?!\.)"), "<ip>"),
]


@dataclass
class LogEntry:
    index: int
    line: int  # номер первой строки в файле (с 1)
    time: str
    thread: str
    level: str  # ERROR | WARN | INFO | DEBUG | ""
    source: str
    message: str
    extra: list[str] = field(default_factory=list)  # продолжение: стек-трейс и т. п.
    count: int = 1
    noise: bool = False
    mod: str = ""
    hint: str = ""  # пояснение простым языком

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Источники ----------------------------------------------------------------------------------
_STAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})[.-](\d{2})[.-](\d{2})")


def _stamp(path: Path) -> float:
    """Время сеанса из имени файла (2026-10-13_20-10-00.log, crash-2026-10-13_20.10.21-client.txt),
    иначе — время изменения файла."""
    if match := _STAMP_RE.search(path.name):
        try:
            return datetime(*(int(x) for x in match.groups())).timestamp()
        except ValueError:
            pass
    return path.stat().st_mtime


def list_sources(name: str) -> list[dict[str, Any]]:
    """Все логи инстанса: сеансы запуска, latest.log игры, отчёты о сбоях (новые сверху)."""
    instance = InstanceManager.get(name)
    running = process_manager.running_for(name)
    live_file = Path(running.log_path).name if running else ""
    sources: list[dict[str, Any]] = []

    def add(kind: str, path: Path, title: str = "") -> None:
        stamp = _stamp(path) if kind != "game" else path.stat().st_mtime
        sources.append({"id": f"{kind}:{path.name}", "kind": kind,
                        "title": title or datetime.fromtimestamp(stamp).strftime("%d.%m.%Y %H:%M:%S"),
                        "file": str(path), "size": path.stat().st_size,
                        "modified": datetime.fromtimestamp(stamp).isoformat(timespec="seconds"),
                        "live": kind == "session" and path.name == live_file, "_mtime": stamp})

    if instance.logs_dir.is_dir():
        sessions = sorted(instance.logs_dir.glob("*.log"), key=_stamp, reverse=True)
        for path in sessions[:_SESSIONS_LIMIT]:
            add("session", path)
    crash_dir = instance.game_dir / "crash-reports"
    if crash_dir.is_dir():
        for path in sorted(crash_dir.glob("*.txt"), key=_stamp, reverse=True)[:20]:
            add("crash", path)
    latest = instance.game_dir / "logs" / "latest.log"
    if latest.is_file():
        add("game", latest, "latest.log")
    sources.sort(key=lambda s: (not s["live"], -s["_mtime"]))
    for source in sources:
        del source["_mtime"]
    return sources


def _source_path(instance: Instance, source_id: str) -> Path:
    kind, _, filename = source_id.partition(":")
    folders = {"session": instance.logs_dir, "crash": instance.game_dir / "crash-reports",
               "game": instance.game_dir / "logs"}
    if kind not in folders:
        raise BadRequestError(f"Неизвестный источник лога: {kind}")
    try:
        validate_name(filename, max_length=255)
        path = safe_join(folders[kind], filename)
    except UnsafePathError as e:
        raise BadRequestError(str(e)) from e
    if not path.is_file():
        raise NotFoundError(f"Лог «{filename}» не найден")
    return path


def read_source(name: str, source_id: str = "") -> tuple[str, dict[str, Any] | None]:
    """Текст лога (последние 3 МБ). Без source_id — самый свежий лог."""
    instance = InstanceManager.get(name)
    sources = list_sources(name)
    if not source_id:
        if not sources:
            return "", None
        source = sources[0]
    else:
        source = next((s for s in sources if s["id"] == source_id), None)
        if source is None:
            _source_path(instance, source_id)  # понятная ошибка о неверном имени
            raise NotFoundError("Лог не найден")
    path = _source_path(instance, source["id"])
    with open(path, "rb") as file:
        size = path.stat().st_size
        if size > _MAX_READ:
            file.seek(size - _MAX_READ)
            file.readline()  # пропускаем обрезанную строку
        text = file.read().decode("utf-8", errors="replace")
    return text, source


# --- Разбор ---------------------------------------------------------------------------------------
def _normalize_level(level: str) -> str:
    level = level.upper()
    return {"WARNING": "WARN", "FATAL": "ERROR", "TRACE": "DEBUG"}.get(level, level)


def parse(text: str, mod_ids: set[str] | None = None) -> list[LogEntry]:
    """Разбирает лог в записи. Стек-трейсы приклеиваются к записи, повторы схлопываются."""
    entries: list[LogEntry] = []
    mod_ids = {m.lower() for m in (mod_ids or set()) if len(m) >= 4 and m.lower() not in _GENERIC_PARTS}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        if match:
            entry = LogEntry(len(entries), number, match.group("time"), match.group("thread"),
                             _normalize_level(match.group("level")),
                             (match.group("logger") or match.group("logger2") or "").strip(), match.group("msg"))
        elif m4 := _LOG4J_RE.match(line):
            entry = LogEntry(len(entries), number, "", m4.group("thread"), _normalize_level(m4.group("level")),
                             "log4j", m4.group("msg"))
        elif entries and (_CONTINUATION_RE.match(line) or (_EXCEPTION_RE.match(line) and entries[-1].time)):
            previous = entries[-1]
            previous.extra.append(line)
            if _EXCEPTION_RE.match(line) and previous.level == "":
                previous.level = "ERROR"
            continue
        else:
            level = "ERROR" if _EXCEPTION_RE.match(line) else ""
            entry = LogEntry(len(entries), number, "", "", level, "", line)
        # Повтор той же записи подряд — увеличиваем счётчик
        if entries and not entries[-1].extra and entries[-1].message == entry.message \
                and entries[-1].level == entry.level and entries[-1].source == entry.source:
            entries[-1].count += 1
            continue
        entries.append(entry)

    for entry in entries:
        entry.noise = (entry.level in ("WARN", "INFO", "") and any(p.search(entry.message) for p in _NOISE)) \
            or bool(_SERVICE_NOISE.search(entry.message)) or "Services Discovery" in entry.thread \
            or (entry.message == "Failed to connect" and any("com.mojang.authlib" in x for x in entry.extra[:3]))
        if entry.level in ("ERROR", "WARN") or entry.extra:
            entry.mod = _guess_mod(entry, mod_ids)
            if not entry.noise and entry.level in ("ERROR", "WARN"):
                blob = "\n".join([entry.message, *entry.extra[:8]])
                entry.hint = next((t(key) for pattern, key in _HINTS if pattern.search(blob)), "")
    return entries


def _guess_mod(entry: LogEntry, mod_ids: set[str]) -> str:
    blob = entry.message + "\n" + "\n".join(entry.extra[:60])
    for pattern in _MOD_HINTS:
        if match := pattern.search(blob):
            return match.group("id").lower()
    source = entry.source.lower().replace(" ", "")
    if source in mod_ids:
        return source
    for line in entry.extra[:60]:
        if frame := _FRAME_RE.match(line):
            parts = set(frame.group("cls").lower().split("."))
            found = parts & mod_ids
            if found:
                return sorted(found)[0]
    return ""


def _seconds(clock: str) -> int | None:
    match = _TIME_RE.search(clock)
    if not match:
        return None
    h, m, s = (int(x) for x in match.groups())
    return h * 3600 + m * 60 + s


def summarize(text: str, entries: list[LogEntry], instance: Instance | None = None,
              source: dict[str, Any] | None = None) -> dict[str, Any]:
    head = text[:300_000]
    summary: dict[str, Any] = {
        "minecraft": instance.version if instance else "", "loader": instance.mod_loader if instance else "",
        "loader_version": "", "mods": None, "java": "", "renderer": "", "optifine": "",
        "load_seconds": None, "outcome": "unknown", "crash_description": "",
        "errors": sum(1 for e in entries if e.level == "ERROR" and not e.noise),
        "warnings": sum(1 for e in entries if e.level == "WARN" and not e.noise),
        "noise": sum(1 for e in entries if e.noise),
        "lines": text.count("\n") + 1 if text else 0,
        "first_error": next((e.index for e in entries if e.level == "ERROR" and not e.noise), None),
        "suspects": [],
    }
    for loader, pattern in _SUMMARY_RULES:
        if match := pattern.search(head):
            groups = match.groupdict()
            summary["loader"] = loader
            summary["loader_version"] = groups.get("loader") or groups.get("loader2") or ""
            if groups.get("mc"):
                summary["minecraft"] = groups["mc"]
            break
    if match := _MODS_COUNT.search(head):
        summary["mods"] = int(match.group("n") or match.group("n2"))
    if match := _JAVA.search(head):
        summary["java"] = " ".join(x for x in (match.group("vm") or match.group("vm2") or "",
                                               match.group("ver") or match.group("ver2")
                                               or match.group("ver3") or "") if x).strip()
    if match := _RENDERER.search(text):
        summary["renderer"] = (match.group("gl") or match.group("gl2") or match.group("v") or "").strip()[:120]
    if match := _OPTIFINE.search(head):
        summary["optifine"] = match.group("ed").replace("_", " ")

    timed = [e for e in entries if e.time]
    ready = next((e for e in timed if _READY.search(e.message)), None)
    if timed and ready:
        start, end = _seconds(timed[0].time), _seconds(ready.time)
        if start is not None and end is not None:
            summary["load_seconds"] = (end - start) % 86400

    is_crash_report = bool(source and source.get("kind") == "crash")
    if is_crash_report or _CRASHED.search(text):
        summary["outcome"] = "crashed"
        if match := _CRASH_DESCRIPTION.search(text):
            summary["crash_description"] = match.group("d").strip()
    elif source and source.get("live"):
        summary["outcome"] = "running"
    elif _STOPPED.search(text):
        summary["outcome"] = "stopped"
    elif ready:
        summary["outcome"] = "loaded"

    counts: dict[str, int] = {}
    for entry in entries:
        if entry.mod and entry.level == "ERROR" and not entry.noise:
            counts[entry.mod] = counts.get(entry.mod, 0) + entry.count
    summary["suspects"] = [m for m, _ in sorted(counts.items(), key=lambda x: -x[1])[:5]]
    return summary


def analyze(name: str, source_id: str = "") -> dict[str, Any]:
    """Полный разбор лога инстанса для экрана «Логи»."""
    from backend.core import doctor
    from backend.core.mod_metadata import scan_mods
    from shared.config import AppConfig

    instance = InstanceManager.get(name)
    text, source = read_source(name, source_id)
    mods = scan_mods(instance.mods_dir) if instance.mods_dir.is_dir() else []
    mod_ids = {i for m in mods for i in m.ids}
    entries = parse(text, mod_ids)
    summary = summarize(text, entries, instance, source)
    problems = [i.to_dict() for i in doctor.analyze_log(text, mods, instance, AppConfig.load())] if text else []
    mod_names = {i.lower(): m.name for m in mods for i in m.ids}
    summary["suspects"] = [{"id": s, "name": mod_names.get(s, s)} for s in summary["suspects"]]
    truncated = len(entries) > _MAX_ENTRIES
    return {
        "source": source, "sources": list_sources(name), "summary": summary, "problems": problems,
        "entries": [e.to_dict() for e in entries[-_MAX_ENTRIES:]], "truncated": truncated,
        "mod_names": {e.mod: mod_names.get(e.mod, e.mod) for e in entries if e.mod},
        "generated_at": time.time(),
    }


# --- Публикация ----------------------------------------------------------------------------------
def redact(text: str) -> str:
    for pattern, replacement in _REDACT:
        text = pattern.sub(replacement, text)
    return text


def share(name: str, source_id: str = "") -> dict[str, Any]:
    """Публикует лог на mclo.gs (без токенов, IP и имени пользователя Windows). Возвращает ссылку."""
    text, source = read_source(name, source_id)
    if not text.strip():
        raise BadRequestError("Лог пуст")
    lines = redact(text).splitlines()[-_MAX_SHARE_LINES:]
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60) as client:
            resp = client.post(MCLOGS_API, data={"content": "\n".join(lines)})
    except httpx.HTTPError as e:
        raise ExternalServiceError(f"mclo.gs недоступен: {e}") from e
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not data.get("success"):
        raise ExternalServiceError(f"mclo.gs не принял лог: {data.get('error') or resp.status_code}")
    return {"url": data["url"], "id": data.get("id", ""), "source": source["id"] if source else ""}
