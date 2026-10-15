"""Умные обновления и «Турбо».

- Распознавание модов по SHA-1 через Modrinth, включая добавленные вручную.
- Проверка обновлений под версию игры и загрузчик инстанса, обновление всех модов
  с автоснимком перед изменениями.
- «Турбо»: набор проверенных модов-оптимизаций под загрузчик, рекомендуемая память
  и флаги JVM.
"""

from datetime import datetime
from typing import Any

from loguru import logger

from backend.core import snapshots
from backend.core.content import ContentManager, compatible_loaders
from backend.core.errors import BadRequestError, NexoraError
from backend.core.instance import InstanceManager
from backend.core.mod_metadata import scan_mods
from backend.core.tasks import Task
from backend.services.modrinth_client import get_modrinth, pick_primary_file
from shared.system import recommended_memory_mb

_DISABLED = ".disabled"

# Проверенные оптимизации: slug → загрузчики, для которых он ставится
TURBO_MODS: list[tuple[str, tuple[str, ...]]] = [
    ("sodium", ("fabric", "quilt", "neoforge")),
    ("embeddium", ("forge",)),
    ("lithium", ("fabric", "quilt", "neoforge")),
    ("ferrite-core", ("fabric", "quilt", "forge", "neoforge")),
    ("entityculling", ("fabric", "quilt", "forge", "neoforge")),
    ("immediatelyfast", ("fabric", "quilt", "forge", "neoforge")),
    ("modernfix", ("fabric", "forge", "neoforge")),
    ("krypton", ("fabric", "quilt")),
]
# Флаги G1 GC (на основе рекомендаций Aikar), подходят для Java 17+
TURBO_JVM_ARGS = (
    "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions "
    "-XX:+DisableExplicitGC -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M "
    "-XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 "
    "-XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 "
    "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem "
    "-XX:MaxTenuringThreshold=1"
)


def _meta(instance) -> dict[str, dict[str, Any]]:
    return ContentManager.load_meta(instance)


def identify(instance_name: str) -> dict[str, Any]:
    """Сопоставляет jar-файлы модов с проектами Modrinth и обновляет метаданные."""
    instance = InstanceManager.get(instance_name)
    mods = scan_mods(instance.mods_dir)
    modrinth = get_modrinth()
    found = modrinth.versions_by_hashes([m.sha1 for m in mods if m.sha1])
    projects = {p["id"]: p for p in modrinth.get_projects(list({v["project_id"] for v in found.values()}))}
    meta = _meta(instance)
    identified = 0
    for mod in mods:
        version = found.get(mod.sha1)
        if not version:
            continue
        identified += 1
        project = projects.get(version["project_id"], {})
        key = f"mod/{mod.filename.removesuffix(_DISABLED)}"
        meta[key] = {
            **meta.get(key, {}),
            "project_id": version["project_id"],
            "version_id": version["id"],
            "version_number": version.get("version_number", ""),
            "title": project.get("title") or mod.name,
            "icon_url": project.get("icon_url") or "",
        }
    ContentManager.save_meta(instance, meta)
    return {"total": len(mods), "identified": identified}


def check_updates(instance_name: str) -> list[dict[str, Any]]:
    """Список доступных обновлений модов инстанса."""
    instance = InstanceManager.get(instance_name)
    if not instance.is_modded:
        return []
    mods = scan_mods(instance.mods_dir)
    by_hash = {m.sha1: m for m in mods if m.sha1}
    modrinth = get_modrinth()
    current = modrinth.versions_by_hashes(list(by_hash))
    latest = modrinth.latest_versions_by_hashes(list(current), compatible_loaders(instance, "mod"),
                                                [instance.version])
    projects = {p["id"]: p for p in modrinth.get_projects(list({v["project_id"] for v in latest.values()}))}
    updates = []
    for sha1, new in latest.items():
        old = current.get(sha1)
        mod = by_hash.get(sha1)
        if not old or not mod or new["id"] == old["id"]:
            continue
        if new.get("date_published", "") < old.get("date_published", ""):
            continue  # не «обновляем» на более старую сборку
        project = projects.get(new["project_id"], {})
        updates.append({
            "filename": mod.filename,
            "name": project.get("title") or mod.name,
            "icon_url": project.get("icon_url") or "",
            "project_id": new["project_id"],
            "current_version": old.get("version_number", mod.version),
            "new_version": new.get("version_number", ""),
            "version_id": new["id"],
            "enabled": mod.enabled,
        })
    return sorted(updates, key=lambda u: u["name"].lower())


def apply_updates(instance_name: str, version_ids: list[str] | None = None,
                  task: Task | None = None) -> dict[str, Any]:
    """Обновляет моды (все или выбранные) с автоснимком перед изменениями."""
    instance = InstanceManager.get(instance_name)
    updates = check_updates(instance_name)
    if version_ids is not None:
        updates = [u for u in updates if u["version_id"] in set(version_ids)]
    if not updates:
        return {"updated": [], "failed": [], "snapshot": None}
    snap = snapshots.create(instance_name, f"Перед обновлением {len(updates)} модов", auto=True)
    modrinth = get_modrinth()
    updated, failed = [], []
    for i, update in enumerate(updates, 1):
        if task:
            task.set_status(f"Обновление {update['name']} ({i}/{len(updates)})…")
        try:
            version = modrinth.get_version(update["version_id"])
            file_info = pick_primary_file(version)
            target_name = file_info["filename"] + ("" if update["enabled"] else _DISABLED)
            modrinth.download_file(file_info, instance.mods_dir / target_name, task)
            if target_name != update["filename"]:
                (instance.mods_dir / update["filename"]).unlink(missing_ok=True)
            meta = _meta(instance)
            meta.pop(f"mod/{update['filename'].removesuffix(_DISABLED)}", None)
            meta[f"mod/{file_info['filename']}"] = {
                "project_id": update["project_id"], "version_id": version["id"],
                "version_number": version.get("version_number", ""), "title": update["name"],
                "icon_url": update["icon_url"], "installed_at": datetime.now().isoformat(timespec="seconds"),
            }
            ContentManager.save_meta(instance, meta)
            updated.append(update["name"])
        except NexoraError as e:
            logger.warning(f"Не удалось обновить {update['name']}: {e}")
            failed.append({"name": update["name"], "error": str(e)})
    return {"updated": updated, "failed": failed, "snapshot": snap["id"]}


def turbo_plan(instance_name: str) -> dict[str, Any]:
    """Что сделает «Турбо» (без изменений)."""
    instance = InstanceManager.get(instance_name)
    if not instance.is_modded:
        raise BadRequestError("«Турбо» работает с загрузчиком модов. Выберите Fabric, Quilt, Forge или NeoForge "
                              "в настройках инстанса.")
    mods = scan_mods(instance.mods_dir)
    installed_projects = {i.get("project_id") for i in _meta(instance).values()}
    installed_ids = {i.lower() for m in mods for i in m.ids}
    planned = []
    for slug, loaders in TURBO_MODS:
        if instance.mod_loader not in loaders:
            continue
        # embeddium и sodium взаимоисключающие — не ставим дубль рендер-движка
        if slug in ("sodium", "embeddium") and ({"sodium", "embeddium", "rubidium"} & installed_ids):
            continue
        if slug.replace("-", "") in {i.replace("-", "").replace("_", "") for i in installed_ids}:
            continue
        planned.append(slug)
    planned = [s for s in planned if s not in installed_projects]
    memory = recommended_memory_mb(len(mods) + len(planned))
    return {"mods": planned, "max_memory": memory, "jvm_args": TURBO_JVM_ARGS,
            "current_memory": instance.max_memory, "current_jvm_args": instance.jvm_args}


def apply_turbo(instance_name: str, task: Task | None = None, tune_jvm: bool = True) -> dict[str, Any]:
    plan = turbo_plan(instance_name)
    snapshots.create(instance_name, "Перед «Турбо»", auto=True)
    installed, skipped = [], []
    modrinth = get_modrinth()
    for slug in plan["mods"]:
        if task:
            task.set_status(f"«Турбо»: {slug}…")
        try:
            project_id = modrinth.get_project(slug)["id"]
            result = ContentManager.install(instance_name, "mod", project_id, task=task)
            installed += [r["title"] for r in result]
        except NexoraError as e:
            logger.info(f"«Турбо»: {slug} пропущен — {e}")
            skipped.append(slug)
    if tune_jvm:
        InstanceManager.update(instance_name, max_memory=plan["max_memory"], jvm_args=plan["jvm_args"])
    return {"installed": installed, "skipped": skipped, "max_memory": plan["max_memory"] if tune_jvm else None}
