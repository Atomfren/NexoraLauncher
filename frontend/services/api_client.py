"""Синхронный HTTP-клиент backend API.

Методы блокирующие — вызывайте их из фонового потока (``frontend.utils.worker.run_async``).
"""

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import httpx

TOKEN_HEADER = "X-Nexora-Token"


class ApiError(Exception):
    """Ошибка API с человекочитаемым сообщением из поля ``detail``."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def _q(value: str) -> str:
    return quote(value, safe="")


class ApiClient:
    """Клиент NexoraLauncher Backend."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        headers = {TOKEN_HEADER: token} if token else {}
        # trust_env=False: backend локальный, системный прокси (HTTP_PROXY) к нему применять нельзя —
        # иначе прокси без исключения для 127.0.0.1 отвечает 502
        self._http = httpx.Client(base_url=self.base_url, headers=headers, trust_env=False,
                                  timeout=httpx.Timeout(timeout, connect=5.0))
        # Отдельный клиент для внешних ресурсов (иконки): без токена, с пулом соединений
        self._external = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True,
                                      limits=httpx.Limits(max_connections=6))

    def close(self) -> None:
        self._http.close()
        self._external.close()

    # --- Базовые запросы --------------------------------------------------------
    def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            raise ApiError("Превышено время ожидания ответа backend") from e
        except httpx.HTTPError as e:
            raise ApiError(f"Нет связи с backend: {e}") from e
        if resp.status_code == 204 or not resp.content:
            if resp.status_code >= 400:
                raise ApiError(f"HTTP {resp.status_code}", resp.status_code)
            return None
        try:
            data = resp.json()
        except ValueError:
            data = {"detail": resp.text}
        if resp.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise ApiError(str(detail or f"HTTP {resp.status_code}"), resp.status_code)
        return data

    def get(self, path: str, **params) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, json_body: Any = None) -> Any:
        return self.request("POST", path, json=json_body)

    def patch(self, path: str, json_body: Any) -> Any:
        return self.request("PATCH", path, json=json_body)

    def put(self, path: str, json_body: Any) -> Any:
        return self.request("PUT", path, json=json_body)

    def delete(self, path: str, **params) -> Any:
        return self.request("DELETE", path, params=params or None)

    # --- Health / задачи -----------------------------------------------------------
    def health(self) -> dict:
        return self.get("/health")

    def tasks(self, active: bool = False) -> list[dict]:
        return self.get("/tasks/", active=str(active).lower())

    def task(self, task_id: str) -> dict:
        return self.get(f"/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> dict:
        return self.post(f"/tasks/{task_id}/cancel")

    # --- Инстансы ---------------------------------------------------------------------
    def instances(self) -> list[dict]:
        return self.get("/instances/")

    def instance(self, name: str) -> dict:
        return self.get(f"/instances/{_q(name)}")

    def create_instance(self, name: str, version: str, mod_loader: str = "vanilla",
                        loader_version: str = "", install: bool = True, title: str = "") -> dict:
        return self.post("/instances/", {"name": name, "version": version, "mod_loader": mod_loader,
                                         "loader_version": loader_version, "install": install, "title": title})

    def update_instance(self, name: str, **changes) -> dict:
        return self.patch(f"/instances/{_q(name)}", changes)

    def delete_instance(self, name: str) -> None:
        self.delete(f"/instances/{_q(name)}")

    def rename_instance(self, name: str, new_name: str) -> dict:
        return self.post(f"/instances/{_q(name)}/rename", {"new_name": new_name})

    def set_background(self, name: str, path: str) -> dict:
        return self.put(f"/instances/{_q(name)}/background", {"path": path})

    def clear_background(self, name: str) -> dict:
        return self.delete(f"/instances/{_q(name)}/background")

    def duplicate_instance(self, name: str, new_name: str) -> dict:
        return self.post(f"/instances/{_q(name)}/duplicate", {"new_name": new_name})

    def prepare_instance(self, name: str, force: bool = False) -> dict:
        return self.post(f"/instances/{_q(name)}/prepare", {"force": force})

    def launch_instance(self, name: str, server: str = "", port: int = 25565) -> dict:
        return self.post(f"/instances/{_q(name)}/launch", {"server": server, "port": port})

    def analyze_logs(self, name: str, source: str = "") -> dict:
        return self.request("GET", f"/instances/{_q(name)}/logs/analyze", timeout=60, params={"source": source})

    def share_log(self, name: str, source: str = "") -> dict:
        return self.request("POST", f"/instances/{_q(name)}/logs/share", timeout=90, json={"source": source})

    def instance_log(self, name: str, lines: int = 2000) -> dict:
        return self.get(f"/instances/{_q(name)}/log", lines=lines)

    def export_instance(self, name: str, path: str) -> dict:
        return self.post(f"/instances/{_q(name)}/export", {"path": path})

    # --- OptiFine ---------------------------------------------------------------------------
    def optifine_status(self, instance: str) -> dict:
        return self.get(f"/instances/{_q(instance)}/optifine")

    def optifine_versions(self, mc_version: str) -> list[dict]:
        return self.get("/optifine/versions", mc_version=mc_version)

    def optifine_downloaded(self, mc_version: str) -> list[dict]:
        return self.get("/optifine/downloaded", mc_version=mc_version)

    def install_optifine(self, instance: str, path: str) -> dict:
        return self.post(f"/instances/{_q(instance)}/optifine", {"path": path})

    def remove_optifine(self, instance: str) -> None:
        self.delete(f"/instances/{_q(instance)}/optifine")

    def foreign_instances(self) -> list[dict]:
        return self.get("/instances/import/foreign")

    def import_instance(self, file_path: str, new_name: str = "") -> dict:
        return self.post("/instances/import", {"file_path": file_path, "new_name": new_name})

    # --- Контент ------------------------------------------------------------------------
    def search(self, project_type: str, query: str = "", game_version: str | None = None,
               loader: str | None = None, index: str = "relevance", limit: int = 20,
               offset: int = 0, category: str | None = None) -> dict:
        return self.get("/content/search", project_type=project_type, query=query,
                        game_version=game_version, loader=loader, index=index, limit=limit, offset=offset,
                        category=category)

    def project(self, project_id: str) -> dict:
        return self.get(f"/content/projects/{_q(project_id)}")

    # --- Сборки FTB и CurseForge (через API FTB) -----------------------------------------------------
    def packs_search(self, provider: str, query: str = "", limit: int = 20) -> dict:
        return self.get(f"/packs/{_q(provider)}/search", q=query, limit=limit)

    def pack(self, provider: str, pack_id: str) -> dict:
        return self.get(f"/packs/{_q(provider)}/{_q(pack_id)}")

    def install_pack(self, provider: str, pack_id: str, version_id: int | None = None, new_name: str = "") -> dict:
        return self.post(f"/packs/{_q(provider)}/{_q(pack_id)}/install",
                         {"version_id": version_id, "new_name": new_name})

    def project_versions(self, project_id: str, game_version: str | None = None,
                         loader: str | None = None) -> list[dict]:
        return self.get(f"/content/projects/{_q(project_id)}/versions",
                        game_version=game_version, loader=loader)

    def installed_content(self, instance: str, content_type: str) -> list[dict]:
        return self.get(f"/instances/{_q(instance)}/content/{content_type}")

    def install_content(self, instance: str, content_type: str, project_id: str,
                        version_id: str | None = None) -> dict:
        return self.post(f"/instances/{_q(instance)}/content/{content_type}",
                         {"project_id": project_id, "version_id": version_id})

    def add_local_content(self, instance: str, content_type: str, path: str) -> dict:
        return self.post(f"/instances/{_q(instance)}/content/{content_type}/local", {"path": path})

    def toggle_content(self, instance: str, content_type: str, filename: str, enabled: bool) -> dict:
        return self.patch(f"/instances/{_q(instance)}/content/{content_type}/{_q(filename)}",
                          {"enabled": enabled})

    def remove_content(self, instance: str, content_type: str, filename: str) -> None:
        self.delete(f"/instances/{_q(instance)}/content/{content_type}/{_q(filename)}")

    def worlds(self, instance: str) -> list[dict]:
        return self.get(f"/instances/{_q(instance)}/worlds")

    def import_world(self, instance: str, path: str) -> dict:
        return self.post(f"/instances/{_q(instance)}/worlds/import", {"path": path})

    def export_world(self, instance: str, world: str, path: str) -> dict:
        return self.post(f"/instances/{_q(instance)}/worlds/{_q(world)}/export", {"path": path})

    def delete_world(self, instance: str, world: str) -> None:
        self.delete(f"/instances/{_q(instance)}/worlds/{_q(world)}")

    def install_modpack(self, project_id: str, version_id: str | None = None, new_name: str = "") -> dict:
        return self.post("/modpacks/install", {"project_id": project_id, "version_id": version_id,
                                               "new_name": new_name})

    # --- Доктор, снимки, обновления, «Турбо» -----------------------------------------------
    def diagnose(self, instance: str) -> dict:
        return self.request("GET", f"/instances/{_q(instance)}/doctor", timeout=60)

    def apply_fix(self, instance: str, action: str, params: dict) -> dict:
        return self.post(f"/instances/{_q(instance)}/doctor/fix", {"action": action, "params": params})

    def snapshots(self, instance: str) -> list[dict]:
        return self.get(f"/instances/{_q(instance)}/snapshots")

    def create_snapshot(self, instance: str, label: str = "") -> dict:
        return self.request("POST", f"/instances/{_q(instance)}/snapshots", json={"label": label}, timeout=300)

    def restore_snapshot(self, instance: str, snap_id: str) -> dict:
        return self.request("POST", f"/instances/{_q(instance)}/snapshots/{_q(snap_id)}/restore", timeout=300)

    def delete_snapshot(self, instance: str, snap_id: str) -> None:
        self.delete(f"/instances/{_q(instance)}/snapshots/{_q(snap_id)}")

    def identify_mods(self, instance: str) -> dict:
        return self.request("POST", f"/instances/{_q(instance)}/mods/identify", timeout=120)

    def mod_updates(self, instance: str) -> list[dict]:
        return self.request("GET", f"/instances/{_q(instance)}/mods/updates", timeout=120)

    def apply_mod_updates(self, instance: str, version_ids: list[str] | None = None) -> dict:
        return self.post(f"/instances/{_q(instance)}/mods/updates", {"version_ids": version_ids})

    def turbo_plan(self, instance: str) -> dict:
        return self.request("GET", f"/instances/{_q(instance)}/turbo", timeout=60)

    def apply_turbo(self, instance: str, tune_jvm: bool = True) -> dict:
        return self.post(f"/instances/{_q(instance)}/turbo", {"tune_jvm": tune_jvm})

    def export_mrpack(self, instance: str, path: str) -> dict:
        return self.post(f"/instances/{_q(instance)}/export_mrpack", {"path": path})

    # --- Свой сервер (хостинг) -----------------------------------------------------------
    def hosted_servers(self) -> list[dict]:
        return self.get("/hosting/servers")

    def hosted_server(self, name: str) -> dict:
        return self.get(f"/hosting/servers/{_q(name)}")

    def create_hosted_server(self, name: str, version: str, max_memory: int, accept_eula: bool,
                             core: str = "fabric") -> dict:
        return self.post("/hosting/servers", {"name": name, "version": version, "max_memory": max_memory,
                                              "accept_eula": accept_eula, "core": core})

    def update_hosted_server(self, name: str, **changes) -> dict:
        return self.patch(f"/hosting/servers/{_q(name)}", changes)

    def delete_hosted_server(self, name: str) -> None:
        self.delete(f"/hosting/servers/{_q(name)}")

    def reinstall_hosted_server(self, name: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/install")

    def start_hosted_server(self, name: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/start")

    def stop_hosted_server(self, name: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/stop")

    def server_command(self, name: str, command: str) -> None:
        self.post(f"/hosting/servers/{_q(name)}/command", {"command": command})

    def server_console(self, name: str, lines: int = 500) -> list[str]:
        return self.get(f"/hosting/servers/{_q(name)}/console", lines=lines)

    def server_properties(self, name: str) -> dict:
        return self.get(f"/hosting/servers/{_q(name)}/properties")

    def update_server_properties(self, name: str, changes: dict) -> dict:
        return self.patch(f"/hosting/servers/{_q(name)}/properties", changes)

    def server_mods(self, name: str) -> list[dict]:
        return self.get(f"/hosting/servers/{_q(name)}/mods")

    def install_server_mod(self, name: str, project_id: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/mods", {"project_id": project_id})

    def remove_server_mod(self, name: str, filename: str) -> None:
        self.delete(f"/hosting/servers/{_q(name)}/mods/{_q(filename)}")

    def server_client_pack(self, name: str, path: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/client_pack", {"path": path})

    def prepare_friends(self, instance: str) -> dict:
        return self.post(f"/instances/{_q(instance)}/friends/prepare")

    def search_server_mods(self, query: str, game_version: str, limit: int = 20, core: str = "fabric") -> dict:
        """Моды для Fabric-сервера или плагины для Paper/Purpur."""
        project_type = "plugin" if core in ("paper", "purpur") else "mod"
        return self.get("/content/search", project_type=project_type, query=query, game_version=game_version,
                        loader=core, side="server", index="relevance" if query else "downloads",
                        limit=limit)

    # --- Обновление лаунчера -------------------------------------------------------------
    def check_update(self) -> dict:
        return self.get("/app/update")

    def download_update(self) -> dict:
        return self.post("/app/update/download")

    def apply_update(self, path: str) -> dict:
        return self.post("/app/update/apply", {"path": path})

    def server_backups(self, name: str) -> list[dict]:
        return self.get(f"/hosting/servers/{_q(name)}/backups")

    def create_server_backup(self, name: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/backups")

    def restore_server_backup(self, name: str, filename: str) -> dict:
        return self.post(f"/hosting/servers/{_q(name)}/backups/{_q(filename)}/restore")

    def delete_server_backup(self, name: str, filename: str) -> None:
        self.delete(f"/hosting/servers/{_q(name)}/backups/{_q(filename)}")

    # --- Minecraft ------------------------------------------------------------------------
    def available_versions(self, refresh: bool = False) -> list[dict]:
        return self.get("/minecraft/versions/available", refresh=str(refresh).lower())

    def installed_versions(self) -> list[dict]:
        return self.get("/minecraft/versions/installed")

    def install_version(self, version_id: str) -> dict:
        return self.post(f"/minecraft/versions/{_q(version_id)}/install")

    def loader_versions(self, loader: str, mc_version: str, stable_only: bool = True) -> list[str]:
        return self.get(f"/minecraft/loaders/{loader}/versions", mc_version=mc_version,
                        stable_only=str(stable_only).lower())

    def processes(self) -> list[dict]:
        return self.get("/minecraft/processes")

    def process_log(self, pid: int, lines: int = 500) -> list[str]:
        return self.get(f"/minecraft/processes/{pid}/log", lines=lines)

    def stop_process(self, pid: int) -> dict:
        return self.delete(f"/minecraft/processes/{pid}")

    # --- Аккаунты ---------------------------------------------------------------------------
    def accounts(self) -> list[dict]:
        return self.get("/auth/accounts")

    def offline_login(self, username: str) -> dict:
        return self.post("/auth/offline/login", {"username": username})

    def microsoft_login_start(self) -> dict:
        return self.post("/auth/microsoft/login/start")

    def activate_account(self, account_id: str) -> dict:
        return self.post(f"/auth/accounts/{_q(account_id)}/activate")

    def account_skin(self, account_id: str) -> dict:
        return self.get(f"/auth/accounts/{_q(account_id)}/skin")

    def set_account_skin(self, account_id: str, path: str, slim: bool) -> dict:
        return self.put(f"/auth/accounts/{_q(account_id)}/skin", {"path": path, "slim": slim})

    def set_account_cape(self, account_id: str, path: str) -> dict:
        return self.put(f"/auth/accounts/{_q(account_id)}/cape", {"path": path})

    def reset_account_skin(self, account_id: str) -> dict:
        return self.delete(f"/auth/accounts/{_q(account_id)}/skin")

    def remove_account(self, account_id: str) -> None:
        self.delete(f"/auth/accounts/{_q(account_id)}")

    # --- Настройки -----------------------------------------------------------------------------
    def settings(self) -> dict:
        return self.get("/settings/")

    def update_settings(self, **changes) -> dict:
        return self.patch("/settings/", changes)

    def system_info(self) -> dict:
        return self.get("/settings/system")

    def detect_java(self) -> list[dict]:
        return self.request("GET", "/settings/java/", timeout=120)

    # --- Серверы --------------------------------------------------------------------------------
    def servers(self) -> list[dict]:
        return self.get("/servers/")

    def create_server(self, name: str, host: str, port: int = 25565, instance_name: str = "") -> dict:
        return self.post("/servers/", {"name": name, "host": host, "port": port,
                                       "instance_name": instance_name})

    def update_server(self, server_id: str, **changes) -> dict:
        return self.patch(f"/servers/{_q(server_id)}", changes)

    def delete_server(self, server_id: str) -> None:
        self.delete(f"/servers/{_q(server_id)}")

    def ping_server(self, server_id: str) -> dict:
        return self.get(f"/servers/{_q(server_id)}/ping")

    def connect_server(self, server_id: str, instance_name: str = "") -> dict:
        return self.post(f"/servers/{_q(server_id)}/connect", {"instance_name": instance_name})

    # --- AI ---------------------------------------------------------------------------------------
    def ai_status(self) -> dict:
        return self.get("/ai/status")

    def ai_chat_stream(self, text: str, history: list[dict]) -> Iterator[dict]:
        """Потоковый ответ AI: последовательность dict из NDJSON."""
        try:
            with self._http.stream("POST", "/ai/chat", json={"text": text, "history": history},
                                   timeout=httpx.Timeout(600.0, connect=5.0)) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise ApiError(resp.json().get("detail", f"HTTP {resp.status_code}"), resp.status_code)
                for line in resp.iter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.HTTPError as e:
            raise ApiError(f"Нет связи с backend: {e}") from e

    # --- Прочее ---------------------------------------------------------------------------------
    def download_bytes(self, url: str) -> bytes:
        """Скачивает внешний ресурс (иконки). Без токена backend."""
        resp = self._external.get(url)
        resp.raise_for_status()
        return resp.content
