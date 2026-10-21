"""Экспорт/импорт инстансов (.zip) и модпаков Modrinth (.mrpack)."""

import json
import shutil
import zipfile
from pathlib import Path

import minecraft_launcher_lib as mll
from loguru import logger

from backend.core.errors import BadRequestError
from backend.core.instance import Instance, InstanceManager, check_name, instance_path
from backend.core.minecraft import MinecraftManager, with_network_retries
from backend.core.tasks import Task
from backend.services.modrinth_client import get_modrinth, pick_primary_file
from shared.fsutil import safe_extract_zip, sanitize_name
from shared.paths import get_cache_dir, get_minecraft_dir

_MRPACK_LOADERS = {"fabric-loader": "fabric", "quilt-loader": "quilt", "forge": "forge", "neoforge": "neoforge"}
_EXPORT_SKIP = {"logs", "crash-reports", ".cache"}


def _open_zip(path: Path) -> zipfile.ZipFile:
    if not path.is_file():
        raise BadRequestError(f"Файл не найден: {path}")
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise BadRequestError("Файл повреждён или не является архивом") from e


class PackManager:
    """Менеджер архивов инстансов."""

    @staticmethod
    def export_instance(name: str, dest: Path, task: Task | None = None) -> Path:
        """Экспортирует инстанс в ZIP (без логов и отчётов о падениях)."""
        instance = InstanceManager.get(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        files = [p for p in instance.path.rglob("*")
                 if p.is_file() and not (_EXPORT_SKIP & set(p.relative_to(instance.path).parts))]
        if task:
            task.set_status(f"Экспорт «{name}»…")
            task.set_max(len(files))
        tmp = dest.with_name(dest.name + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, file in enumerate(files):
                zf.write(file, file.relative_to(instance.path))
                if task:
                    task.set_progress(i + 1)
        tmp.replace(dest)
        logger.info(f"Инстанс '{name}' экспортирован в {dest}")
        return dest

    @staticmethod
    def export_mrpack(name: str, dest: Path, task: Task | None = None) -> dict:
        """Экспорт в .mrpack: файлы с Modrinth — ссылками, остальное — в overrides.

        Такой модпак открывается в NexoraLauncher, Modrinth App, Prism Launcher и др.
        """
        from backend.core.mod_metadata import file_hashes

        instance = InstanceManager.get(name)
        game = instance.game_dir
        candidates = []
        for folder in ("mods", "resourcepacks", "shaderpacks"):
            base = game / folder
            if base.is_dir():
                candidates += [p for p in base.iterdir()
                               if p.is_file() and p.suffix.lower() in (".jar", ".zip")]
        if task:
            task.set_status("Определение файлов на Modrinth…")
        hashes = {p: file_hashes(p) for p in candidates}
        known = get_modrinth().versions_by_hashes([h[0] for h in hashes.values()]) if hashes else {}

        files, overrides = [], []
        for path, (sha1, sha512) in hashes.items():
            version = known.get(sha1)
            download = next((f for f in (version or {}).get("files", [])
                             if (f.get("hashes") or {}).get("sha1") == sha1), None)
            rel = path.relative_to(game).as_posix()
            if download:
                files.append({"path": rel, "hashes": {"sha1": sha1, "sha512": sha512},
                              "env": {"client": "required", "server": "optional"},
                              "downloads": [download["url"]], "fileSize": path.stat().st_size})
            else:
                overrides.append(path)
        for rel in ("config", "defaultconfigs", "kubejs", "options.txt", "servers.dat"):
            path = game / rel
            if path.is_file():
                overrides.append(path)
            elif path.is_dir():
                overrides += [p for p in path.rglob("*") if p.is_file()]

        dependencies = {"minecraft": instance.version}
        loader_key = {v: k for k, v in _MRPACK_LOADERS.items()}.get(instance.mod_loader)
        if loader_key and instance.loader_version:
            dependencies[loader_key] = instance.loader_version
        index = {"formatVersion": 1, "game": "minecraft", "versionId": "1.0.0", "name": instance.name,
                 "summary": f"Экспорт из NexoraLauncher: {instance.mod_loader} {instance.version}",
                 "files": files, "dependencies": dependencies}
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("modrinth.index.json", json.dumps(index, indent=2, ensure_ascii=False))
            for path in overrides:
                zf.write(path, "overrides/" + path.relative_to(game).as_posix())
        tmp.replace(dest)
        logger.info(f"Инстанс '{name}' экспортирован в .mrpack: {len(files)} ссылок, {len(overrides)} файлов")
        return {"path": str(dest), "linked": len(files), "embedded": len(overrides)}

    @staticmethod
    def import_archive(path: Path, new_name: str = "", task: Task | None = None) -> Instance:
        """Импорт .zip (экспорт NexoraLauncher, Prism, MultiMC), .mrpack или папки другого лаунчера."""
        from backend.core import foreign_import

        if path.is_dir():
            return foreign_import.import_folder(path, new_name, task)
        if path.suffix.lower() == ".mrpack":
            return PackManager.import_mrpack(path, new_name, task)
        with _open_zip(path) as zf:
            is_mmc = foreign_import.is_mmc_zip(zf)
        if is_mmc:
            return foreign_import.import_mmc_zip(path, new_name, task)
        return PackManager.import_zip(path, new_name, task)

    @staticmethod
    def import_zip(path: Path, new_name: str = "", task: Task | None = None) -> Instance:
        with _open_zip(path) as zf:
            entries = [n.replace("\\", "/") for n in zf.namelist()]
            configs = [n for n in entries if n.endswith("instance.json") and n.count("/") <= 1]
            if not configs:
                raise BadRequestError("В архиве нет instance.json — это не экспорт NexoraLauncher")
            prefix = min(configs, key=len)[: -len("instance.json")]
            data = json.loads(zf.read(prefix + "instance.json"))
            name = new_name or InstanceManager.unique_name(sanitize_name(data.get("name", path.stem)))
            check_name(name)
            target = instance_path(name)
            if target.exists():
                raise BadRequestError(f"Инстанс '{name}' уже существует")
            if task:
                task.set_status("Распаковка архива…")
            try:
                safe_extract_zip(zf, target, strip_prefix=prefix)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
        instance = Instance.load(name)
        if instance is None:
            shutil.rmtree(target, ignore_errors=True)
            raise BadRequestError("Повреждённый instance.json в архиве")
        instance.save()  # нормализует имя внутри instance.json
        logger.info(f"Инстанс импортирован как '{name}'")
        return instance

    @staticmethod
    def import_mrpack(path: Path, new_name: str = "", task: Task | None = None, title: str = "") -> Instance:
        with _open_zip(path) as zf:
            try:
                index = json.loads(zf.read("modrinth.index.json"))
            except KeyError as e:
                raise BadRequestError("В архиве нет modrinth.index.json") from e
        deps: dict[str, str] = index.get("dependencies", {})
        mc_version = deps.get("minecraft")
        if not mc_version:
            raise BadRequestError("В модпаке не указана версия Minecraft")
        mod_loader, loader_version = "vanilla", ""
        for key, loader in _MRPACK_LOADERS.items():
            if key in deps:
                mod_loader, loader_version = loader, deps[key]
                break

        pack_title = index.get("name", path.stem)
        name = new_name or InstanceManager.unique_name(sanitize_name(pack_title))
        instance = InstanceManager.create(name, mc_version, mod_loader, loader_version,
                                          title=title or ("" if new_name else pack_title))
        try:
            if task:
                task.set_status(f"Загрузка файлов модпака «{index.get('name', name)}»…")
            with_network_retries(lambda: mll.mrpack.install_mrpack(
                path, get_minecraft_dir(), modpack_directory=instance.game_dir,
                callback=task.callback_dict() if task else None,
                mrpack_install_options={"optionalFiles": [], "skipDependenciesInstall": True},
            ), task, "файлов модпака")
            MinecraftManager().prepare_instance(instance, task)
        except Exception:
            shutil.rmtree(instance.path, ignore_errors=True)
            raise
        logger.info(f"Модпак импортирован как '{name}'")
        return Instance.load(name) or instance

    @staticmethod
    def install_from_modrinth(project_id: str, version_id: str | None, new_name: str,
                              task: Task | None = None) -> Instance:
        """Скачивает .mrpack с Modrinth и импортирует его."""
        modrinth = get_modrinth()
        if version_id:
            version = modrinth.get_version(version_id)
        else:
            versions = modrinth.get_project_versions(project_id)
            if not versions:
                raise BadRequestError("У модпака нет версий")
            releases = [v for v in versions if v.get("version_type") == "release"]
            version = (releases or versions)[0]
        project = modrinth.get_project(version["project_id"])
        file_info = pick_primary_file(version)
        if not file_info["filename"].endswith(".mrpack"):
            raise BadRequestError("Файл модпака имеет неизвестный формат")
        dest = get_cache_dir() / "modpacks" / f"{version['id']}.mrpack"
        if task:
            task.set_status(f"Загрузка {project.get('title', 'модпака')}…")
        modrinth.download_file(file_info, dest, task)
        try:
            pack_title = project.get("title", "Modpack")
            name = new_name or InstanceManager.unique_name(sanitize_name(pack_title))
            return PackManager.import_mrpack(dest, name, task, title="" if new_name else pack_title)
        finally:
            dest.unlink(missing_ok=True)
