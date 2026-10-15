"""«Доктор Nexora»: диагностика вылетов и проблем сборки с исправлением в один клик.

Источники: последний лог запуска, свежий crash-report и статический анализ модов
(дубликаты, битые jar, моды не для того загрузчика, недостающие зависимости).
Каждая проблема содержит список исправлений; исправление — это действие с
параметрами, которое применяет ``apply_fix``.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.core.content import ContentManager
from backend.core.errors import BadRequestError, NotFoundError
from backend.core.instance import Instance, InstanceManager
from backend.core.mod_metadata import ModInfo, find_by_mod_id, provided_ids, scan_mods
from backend.core.tasks import Task
from backend.services.modrinth_client import get_modrinth
from shared.config import AppConfig
from shared.system import recommended_memory_mb, total_memory_mb

# ID, которые не являются модами (загрузчики, игра, Java)
_PLATFORM_IDS = {"minecraft", "java", "fabricloader", "fabric-loader", "quilt_loader", "quilt_base",
                 "forge", "neoforge", "fml", "javafml", "mcp"}
# Частые несовпадения mod id и slug на Modrinth
_SLUG_ALIASES = {
    "fabric": "fabric-api", "fabric_api": "fabric-api", "cloth_config": "cloth-config",
    "cloth-config2": "cloth-config", "architectury": "architectury-api", "yet_another_config_lib_v3": "yacl",
    "yet-another-config-lib": "yacl", "kotlinforforge": "kotlin-for-forge", "owo": "owo-lib",
    "puzzleslib": "puzzles-lib", "forgeconfigapiport": "forge-config-api-port", "bookshelf": "bookshelf-lib",
    "resourcefullib": "resourceful-lib", "cristellib": "cristel-lib", "fzzy_config": "fzzy-config",
    "geckolib3": "geckolib", "sodium-extra": "sodium-extra", "mixinextras": "mixinextras",
}
_LOG_AGE_LIMIT = 3 * 24 * 3600


@dataclass
class Fix:
    action: str  # install_mod | disable_mod | remove_mod | set_memory | reset_java | repair
    label: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Issue:
    id: str
    severity: str  # error | warning | info
    title: str
    details: str = ""
    fixes: list[Fix] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Сбор данных ------------------------------------------------------------------------
def _latest_log_text(instance: Instance) -> tuple[str, str]:
    """Текст последнего лога запуска и свежего crash-report (если есть)."""
    texts, sources = [], []
    logs_dir = instance.logs_dir
    if logs_dir.exists():
        logs = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if logs and time.time() - logs[0].stat().st_mtime < _LOG_AGE_LIMIT:
            texts.append(logs[0].read_text(encoding="utf-8", errors="replace")[-400_000:])
            sources.append(logs[0].name)
    crash_dir = instance.game_dir / "crash-reports"
    if crash_dir.exists():
        reports = sorted(crash_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        if reports and time.time() - reports[0].stat().st_mtime < _LOG_AGE_LIMIT:
            texts.append(reports[0].read_text(encoding="utf-8", errors="replace")[-200_000:])
            sources.append(reports[0].name)
    return "\n".join(texts), ", ".join(sources)


def _mod_label(mod: ModInfo | None, mod_id: str) -> str:
    return mod.name if mod else mod_id


# --- Правила по логу -------------------------------------------------------------------------
_FABRIC_MISSING = re.compile(
    r"Mod '(?P<name>[^']+)' \((?P<id>[\w.\-]+)\)[^\n]*?requires [^\n]*?"
    r"(?:of mod '[^']*' \((?P<dep1>[\w.\-]+)\)|of (?:mod )?(?P<dep2>[\w.\-]+))[^\n]*?which is missing")
_FABRIC_WRONG_VERSION = re.compile(
    r"Mod '(?P<name>[^']+)' \((?P<id>[\w.\-]+)\)[^\n]*?requires (?P<req>[^\n]*?) of "
    r"(?:mod '[^']*' \((?P<dep1>[\w.\-]+)\)|(?:mod )?(?P<dep2>[\w.\-]+))[^\n]*?but only the wrong version")
_FABRIC_INCOMPATIBLE = re.compile(
    r"Mod '(?P<name>[^']+)' \((?P<id>[\w.\-]+)\)[^\n]*?is incompatible with [^\n]*?"
    r"(?:mod '(?P<oname>[^']*)' \((?P<other1>[\w.\-]+)\)|of (?!mod ')(?:mod )?(?P<other2>[\w.\-]+))")
_FABRIC_INSTALL_HINT = re.compile(r"^\s*-\s*Install (?P<dep>[\w.\-]+), ", re.MULTILINE)
_FORGE_MISSING = re.compile(
    r"Mod ID: '(?P<dep>[\w.\-]+)', Requested by: '(?P<by>[\w.\-]+)', "
    r"Expected range: '(?P<range>[^']*)', Actual version: '(?P<actual>[^']*)'")
_JAVA_CLASS_VERSION = re.compile(r"class file version (?P<need>\d+)(?:\.\d+)?\), this version of the Java "
                                 r"Runtime only recognizes class file versions up to (?P<have>\d+)")
_MIXIN_MOD = re.compile(r"Mixin apply for mod (?P<id>[\w.\-]+) failed|\[from mod (?P<id2>[\w.\-]+)\]")
_SUSPECTED = re.compile(r"Suspected Mods?: (?P<list>[^\n]+)")
_SUSPECTED_ID = re.compile(r"\(([\w.\-]+)\)")
_GPU = re.compile(r"GLFW error 6554[23]|Pixel format not accelerated|driver does not appear to support OpenGL|"
                  r"Couldn't set pixel format|EXCEPTION_ACCESS_VIOLATION[\s\S]{0,400}(?:atio6axx|nvoglv|ig\d+icd)")
_CORRUPT_JAR = re.compile(r"(?:ZipException|zip END header not found|invalid LOC header)[\s\S]{0,300}?"
                          r"mods[/\\](?P<file>[^\s'\"]+\.jar)")


def _install_or_disable(issue: Issue, dep: str, requirer: ModInfo | None) -> None:
    issue.fixes.append(Fix("install_mod", f"Установить «{dep}» с Modrinth", {"mod_id": dep}))
    if requirer:
        issue.fixes.append(Fix("disable_mod", f"Отключить «{requirer.name}»", {"filename": requirer.filename}))


def _analyze_log(text: str, mods: list[ModInfo], instance: Instance, config: AppConfig) -> list[Issue]:
    issues: list[Issue] = []

    def mod(mod_id: str) -> ModInfo | None:
        return find_by_mod_id(mods, mod_id)

    # Недостающие зависимости (Fabric/Quilt)
    missing: dict[str, list[str]] = {}
    for m in _FABRIC_MISSING.finditer(text):
        dep = (m.group("dep1") or m.group("dep2") or "").lower()
        missing.setdefault(dep, []).append(m.group("id"))
    for m in _FABRIC_INSTALL_HINT.finditer(text):
        missing.setdefault(m.group("dep").lower(), [])
    for m in _FORGE_MISSING.finditer(text):
        dep = m.group("dep").lower()
        if m.group("actual").upper() == "[MISSING]":
            missing.setdefault(dep, []).append(m.group("by"))
        elif dep not in _PLATFORM_IDS:
            requirer = mod(m.group("by"))
            issue = Issue(f"version:{dep}", "error", f"Нужна другая версия «{dep}»",
                          f"«{_mod_label(requirer, m.group('by'))}» ожидает версию {m.group('range')}, "
                          f"установлена {m.group('actual')}.")
            issue.fixes.append(Fix("install_mod", f"Обновить «{dep}»", {"mod_id": dep}))
            if requirer:
                issue.fixes.append(Fix("disable_mod", f"Отключить «{requirer.name}»", {"filename": requirer.filename}))
            issues.append(issue)
    for dep, requirers in missing.items():
        if dep in _PLATFORM_IDS:
            for req_id in set(requirers):
                requirer = mod(req_id)
                issue = Issue(f"game_version:{req_id}", "error",
                              f"«{_mod_label(requirer, req_id)}» не подходит к этой версии игры или загрузчика",
                              f"Мод требует другую версию «{dep}». Установлено: Minecraft {instance.version}, "
                              f"{instance.mod_loader} {instance.loader_version}.")
                if requirer:
                    issue.fixes.append(Fix("disable_mod", f"Отключить «{requirer.name}»",
                                           {"filename": requirer.filename}))
                if dep in ("fabricloader", "fabric-loader", "quilt_loader", "forge", "neoforge"):
                    issue.fixes.append(Fix("update_loader", "Обновить загрузчик до последней версии", {}))
                issues.append(issue)
            continue
        names = ", ".join(sorted({_mod_label(mod(r), r) for r in requirers})) or "другим модам"
        issue = Issue(f"missing:{dep}", "error", f"Не хватает мода «{dep}»",
                      f"Он нужен для: {names}.")
        requirer = mod(requirers[0]) if requirers else None
        _install_or_disable(issue, dep, requirer)
        issues.append(issue)

    for m in _FABRIC_WRONG_VERSION.finditer(text):
        dep = (m.group("dep1") or m.group("dep2") or "").lower()
        requirer = mod(m.group("id"))
        if dep in _PLATFORM_IDS:
            issue = Issue(f"game_version:{m.group('id')}", "error",
                          f"«{m.group('name')}» не подходит к этой версии игры или загрузчика",
                          f"Требуется {m.group('req')} «{dep}».")
            if requirer:
                issue.fixes.append(Fix("disable_mod", f"Отключить «{requirer.name}»", {"filename": requirer.filename}))
            if dep in ("fabricloader", "quilt_loader", "forge", "neoforge"):
                issue.fixes.append(Fix("update_loader", "Обновить загрузчик до последней версии", {}))
        else:
            issue = Issue(f"version:{dep}", "error", f"Нужна другая версия «{dep}»",
                          f"«{m.group('name')}» требует {m.group('req')}.")
            issue.fixes.append(Fix("install_mod", f"Обновить «{dep}»", {"mod_id": dep}))
            if requirer:
                issue.fixes.append(Fix("disable_mod", f"Отключить «{requirer.name}»", {"filename": requirer.filename}))
        issues.append(issue)

    for m in _FABRIC_INCOMPATIBLE.finditer(text):
        other_id = (m.group("other1") or m.group("other2") or "").lower()
        if other_id in _PLATFORM_IDS:
            continue
        first, second = mod(m.group("id")), mod(other_id)
        issue = Issue(f"incompatible:{m.group('id')}:{other_id}", "error", "Несовместимые моды",
                      f"«{m.group('name')}» несовместим с «{_mod_label(second, other_id)}». Оставьте один из них.")
        for candidate in (first, second):
            if candidate:
                issue.fixes.append(Fix("disable_mod", f"Отключить «{candidate.name}»",
                                       {"filename": candidate.filename}))
        issues.append(issue)

    if "java.lang.OutOfMemoryError" in text:
        current = instance.max_memory or config.max_memory
        target = min(max(current + 2048, recommended_memory_mb(len(mods))), max(2048, total_memory_mb() * 3 // 4))
        target = target // 512 * 512
        issue = Issue("memory", "error", "Игре не хватило памяти",
                      f"Выделено {current} МБ. Рекомендуется {target} МБ.")
        if target > current:
            issue.fixes.append(Fix("set_memory", f"Выделить {target} МБ этому инстансу", {"max_memory": target}))
        issues.append(issue)

    if m := _JAVA_CLASS_VERSION.search(text):
        need, have = int(m.group("need")) - 44, int(m.group("have")) - 44
        issue = Issue("java_version", "error", f"Нужна Java {need}, а запущена Java {have}",
                      "Один из модов собран под более новую Java.")
        if instance.java_path or config.java_path:
            issue.fixes.append(Fix("reset_java", "Использовать Java от Mojang (автоматически)", {}))
        else:
            issue.details += " Скорее всего, мод предназначен для более новой версии Minecraft."
        issues.append(issue)

    mixin_ids = {(m.group("id") or m.group("id2")).lower() for m in _MIXIN_MOD.finditer(text)}
    for mod_id in sorted(mixin_ids - _PLATFORM_IDS):
        culprit = mod(mod_id)
        if not culprit:
            continue
        issue = Issue(f"mixin:{mod_id}", "error", f"Мод «{culprit.name}» не смог внедриться в игру (Mixin)",
                      "Обычно это несовместимость с версией игры или с другим модом.")
        issue.fixes.append(Fix("install_mod", f"Обновить «{culprit.name}»", {"mod_id": mod_id}))
        issue.fixes.append(Fix("disable_mod", f"Отключить «{culprit.name}»", {"filename": culprit.filename}))
        issues.append(issue)

    for m in _SUSPECTED.finditer(text):
        for mod_id in _SUSPECTED_ID.findall(m.group("list")):
            culprit = mod(mod_id)
            if culprit and mod_id.lower() not in _PLATFORM_IDS:
                issue = Issue(f"suspected:{mod_id.lower()}", "warning", f"Вылет связан с модом «{culprit.name}»",
                              "Так указано в отчёте о сбое Minecraft.")
                issue.fixes.append(Fix("install_mod", f"Обновить «{culprit.name}»", {"mod_id": mod_id}))
                issue.fixes.append(Fix("disable_mod", f"Отключить «{culprit.name}»", {"filename": culprit.filename}))
                issues.append(issue)

    for m in _CORRUPT_JAR.finditer(text):
        issues.append(Issue(f"broken:{m.group('file')}", "error", f"Файл «{m.group('file')}» повреждён",
                            "Скачайте мод заново.",
                            [Fix("remove_mod", "Удалить повреждённый файл", {"filename": m.group("file")})]))

    if _GPU.search(text):
        issues.append(Issue("gpu", "warning", "Проблема с видеодрайвером (OpenGL)",
                            "Обновите драйвер видеокарты с сайта NVIDIA/AMD/Intel. На ноутбуках запускайте игру "
                            "на дискретной видеокарте."))
    return issues


# Публичное имя для умных логов
analyze_log = _analyze_log


# --- Статический анализ модов --------------------------------------------------------------
def _analyze_mods(mods: list[ModInfo], instance: Instance) -> list[Issue]:
    issues: list[Issue] = []
    enabled = [m for m in mods if m.enabled]

    for mod in enabled:
        if mod.broken:
            issues.append(Issue(f"broken:{mod.filename}", "error", f"Файл «{mod.filename}» повреждён",
                                "Это не корректный jar-архив — игра не запустится.",
                                [Fix("remove_mod", "Удалить файл", {"filename": mod.filename})]))

    by_id: dict[str, list[ModInfo]] = {}
    for mod in enabled:
        for mod_id in set(mod.ids[:1]):
            by_id.setdefault(mod_id.lower(), []).append(mod)
    for mod_id, copies in by_id.items():
        if len(copies) > 1:
            copies = sorted(copies, key=lambda m: m.filename)
            issue = Issue(f"duplicate:{mod_id}", "error", f"Мод «{copies[0].name}» установлен несколько раз",
                          "Файлы: " + ", ".join(c.filename for c in copies))
            for copy in copies:
                issue.fixes.append(Fix("remove_mod", f"Удалить {copy.filename}", {"filename": copy.filename}))
            issues.append(issue)

    loader = instance.mod_loader
    accepted = {"fabric": {"fabric"}, "quilt": {"quilt", "fabric"}, "forge": {"forge"},
                "neoforge": {"neoforge", "forge"}}.get(loader, set())
    for mod in enabled:
        if mod.loader in ("fabric", "quilt", "forge", "neoforge") and accepted and mod.loader not in accepted:
            issues.append(Issue(f"wrong_loader:{mod.filename}", "error",
                                f"«{mod.name}» — мод для {mod.loader}, а инстанс на {loader}",
                                "Такой мод не загрузится.",
                                [Fix("disable_mod", f"Отключить «{mod.name}»", {"filename": mod.filename}),
                                 Fix("install_mod", f"Найти версию для {loader}", {"mod_id": mod.ids[0]
                                                                                   if mod.ids else ""})]))

    if loader in ("fabric", "quilt"):
        provided = provided_ids(mods)
        if "fabric-api" in provided:
            provided.add("fabric")
        for mod in enabled:
            for dep in mod.depends:
                dep_l = dep.lower()
                if dep_l in _PLATFORM_IDS or dep_l in provided:
                    continue
                if dep_l.startswith("fabric-") and "fabric-api" in provided:
                    continue
                issue_id = f"missing:{dep_l}"
                if any(i.id == issue_id for i in issues):
                    continue
                issue = Issue(issue_id, "warning", f"Возможно, не хватает мода «{dep}»",
                              f"Он указан как зависимость «{mod.name}».")
                _install_or_disable(issue, dep, mod)
                issues.append(issue)
    return issues


# --- Публичное API --------------------------------------------------------------------------
def diagnose(instance_name: str) -> dict[str, Any]:
    instance = InstanceManager.get(instance_name)
    config = AppConfig.load()
    mods = scan_mods(instance.mods_dir)
    text, sources = _latest_log_text(instance)
    issues = _analyze_log(text, mods, instance, config) if text else []
    known = {i.id for i in issues}
    issues += [i for i in _analyze_mods(mods, instance) if i.id not in known]
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i.severity, 3))
    return {
        "instance": instance_name,
        "sources": sources,
        "mods_scanned": len(mods),
        "issues": [i.to_dict() for i in issues],
    }


def resolve_project(mod_id: str, instance: Instance) -> str:
    """Находит проект Modrinth по mod id (slug, алиас или поиск)."""
    modrinth = get_modrinth()
    candidates = []
    for value in (_SLUG_ALIASES.get(mod_id.lower()), mod_id, mod_id.replace("_", "-"), mod_id.lower()):
        if value and value not in candidates:
            candidates.append(value)
    for slug in candidates:
        try:
            return modrinth.get_project(slug)["id"]
        except NotFoundError:
            continue
    loader = instance.mod_loader if instance.is_modded else None
    hits = modrinth.search(mod_id.replace("_", " "), "mod", instance.version, loader, limit=5).get("hits", [])
    normalized = re.sub(r"[^a-z0-9]", "", mod_id.lower())
    for hit in hits:
        if normalized in (re.sub(r"[^a-z0-9]", "", hit.get("slug", "").lower()),
                          re.sub(r"[^a-z0-9]", "", hit.get("title", "").lower())):
            return hit["project_id"]
    raise NotFoundError(f"Мод «{mod_id}» не найден на Modrinth — установите его вручную")


def apply_fix(instance_name: str, action: str, params: dict[str, Any], task: Task | None = None) -> dict[str, Any]:
    """Применяет исправление. Возвращает краткий результат для UI."""
    from backend.core import snapshots
    from backend.core.minecraft import MinecraftManager

    instance = InstanceManager.get(instance_name)
    if action in ("install_mod", "remove_mod", "disable_mod", "update_loader"):
        snapshots.create(instance_name, "Перед исправлением Доктора", auto=True)

    if action == "install_mod":
        mod_id = str(params.get("mod_id") or "")
        if not mod_id:
            raise BadRequestError("Не указан мод")
        if task:
            task.set_status(f"Поиск «{mod_id}» на Modrinth…")
        project_id = resolve_project(mod_id, instance)
        installed = ContentManager.install(instance_name, "mod", project_id, task=task)
        return {"message": "Установлено: " + ", ".join(i["title"] for i in installed)}
    if action in ("disable_mod", "remove_mod"):
        filename = str(params.get("filename") or "")
        if action == "disable_mod":
            ContentManager.set_enabled(instance_name, "mod", filename, False)
            return {"message": f"Мод {filename} отключён"}
        ContentManager.remove(instance_name, "mod", filename)
        return {"message": f"Файл {filename} удалён"}
    if action == "set_memory":
        value = int(params.get("max_memory") or 0)
        if not 1024 <= value <= 65536:
            raise BadRequestError("Некорректный объём памяти")
        InstanceManager.update(instance_name, max_memory=value)
        return {"message": f"Инстансу выделено {value} МБ"}
    if action == "reset_java":
        InstanceManager.update(instance_name, java_path="")
        AppConfig.load().update(java_path="")
        return {"message": "Будет использоваться Java от Mojang"}
    if action == "update_loader":
        InstanceManager.update(instance_name, loader_version="")
        fresh = InstanceManager.get(instance_name)
        MinecraftManager().prepare_instance(fresh, task)
        return {"message": f"Загрузчик обновлён до {InstanceManager.get(instance_name).loader_version}"}
    if action == "repair":
        MinecraftManager().prepare_instance(instance, task, force=True)
        return {"message": "Файлы игры проверены"}
    raise BadRequestError(f"Неизвестное исправление: {action}")

