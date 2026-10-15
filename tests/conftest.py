"""Общие фикстуры: изолированная папка данных, API-клиент, фейковый Modrinth."""

import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def nexora_home(tmp_path, monkeypatch):
    """Каждый тест работает в собственной временной папке данных."""
    monkeypatch.setenv("NEXORA_HOME", str(tmp_path / "home"))
    from shared.crypto import TokenVault
    TokenVault.reset_cache()
    from backend.config import settings
    monkeypatch.setattr(settings, "api_token", "")
    yield tmp_path / "home"
    TokenVault.reset_cache()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backend.main import create_app
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def wait_task(client):
    """Ждёт завершения задачи по ID и возвращает её состояние."""
    from backend.core.tasks import task_manager

    def wait(task_id: str, timeout: float = 15.0) -> dict:
        return task_manager.wait(task_id, timeout).to_dict()

    return wait


# --- Фейковый Modrinth ---------------------------------------------------------------
def _file(name: str, content: bytes) -> dict:
    return {
        "url": f"https://cdn.example/{name}",
        "filename": name,
        "primary": True,
        "size": len(content),
        "hashes": {"sha512": hashlib.sha512(content).hexdigest(), "sha1": hashlib.sha1(content).hexdigest()},
    }


class FakeModrinth:
    """Минимальная эмуляция API Modrinth для тестов."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.projects: dict[str, dict] = {}
        self.versions: dict[str, list[dict]] = {}
        self.corrupt: set[str] = set()

    def add_project(self, project_id: str, title: str, filename: str, deps: list[str] | None = None,
                    loaders: list[str] | None = None, game_versions: list[str] | None = None,
                    project_type: str = "mod", version_id: str | None = None,
                    content: bytes | None = None, published: str = "2024-01-01T00:00:00Z") -> dict:
        content = content if content is not None else f"{project_id}-content".encode()
        self.files[filename] = content
        self.projects[project_id] = {"id": project_id, "slug": project_id, "title": title,
                                     "description": f"{title} description", "project_type": project_type,
                                     "icon_url": "", "downloads": 10, "categories": loaders or ["fabric"]}
        version = {
            "id": version_id or f"{project_id}-v1", "project_id": project_id, "name": f"{title} 1.0",
            "version_number": "1.0", "version_type": "release", "game_versions": game_versions or ["1.20.1"],
            "loaders": loaders or ["fabric"], "date_published": published, "downloads": 5,
            "files": [_file(filename, content)],
            "dependencies": [{"project_id": d, "version_id": None, "dependency_type": "required"}
                             for d in deps or []],
        }
        self.versions.setdefault(project_id, []).insert(0, version)
        return version

    def _version_by_sha1(self, sha1: str) -> dict | None:
        for versions in self.versions.values():
            for v in versions:
                if any(f["hashes"]["sha1"] == sha1 for f in v["files"]):
                    return v
        return None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        if request.method == "POST":
            body = json.loads(request.content or b"{}")
            result = {}
            for sha1 in body.get("hashes", []):
                version = self._version_by_sha1(sha1)
                if not version:
                    continue
                if path.endswith("/version_files/update"):
                    loaders, games = set(body.get("loaders") or []), set(body.get("game_versions") or [])
                    candidates = [v for v in self.versions[version["project_id"]]
                                  if (not loaders or loaders & set(v["loaders"]))
                                  and (not games or games & set(v["game_versions"]))]
                    if candidates:
                        result[sha1] = candidates[0]
                else:
                    result[sha1] = version
            return httpx.Response(200, json=result)
        if path.endswith("/projects"):
            ids = json.loads(params.get("ids", "[]"))
            return httpx.Response(200, json=[self.projects[i] for i in ids if i in self.projects])
        if request.url.host == "cdn.example":
            name = path.rsplit("/", 1)[-1]
            data = self.files.get(name)
            if data is None:
                return httpx.Response(404)
            return httpx.Response(200, content=b"broken" if name in self.corrupt else data)
        if path.endswith("/search"):
            facets = json.loads(params.get("facets", "[]"))
            ptype = facets[0][0].split(":", 1)[1] if facets else "mod"
            hits = [{"project_id": p["id"], "slug": p["slug"], "title": p["title"],
                     "description": p["description"], "project_type": p["project_type"], "author": "tester",
                     "categories": p["categories"], "display_categories": p["categories"],
                     "downloads": p["downloads"], "follows": 1, "icon_url": None, "versions": ["1.20.1"]}
                    for p in self.projects.values() if p["project_type"] == ptype
                    and params.get("query", "").lower() in p["title"].lower()]
            return httpx.Response(200, json={"hits": hits, "total_hits": len(hits)})
        parts = path.strip("/").split("/")  # v2/project/<id>[/version] | v2/version/<id>
        if parts[1] == "project" and len(parts) == 3:
            project = self.projects.get(parts[2])
            return httpx.Response(200, json=project) if project else httpx.Response(404)
        if parts[1] == "project" and len(parts) == 4:
            versions = self.versions.get(parts[2])
            if versions is None:
                return httpx.Response(404)
            loaders = json.loads(params["loaders"]) if "loaders" in params else None
            games = json.loads(params["game_versions"]) if "game_versions" in params else None
            result = [v for v in versions
                      if (not loaders or set(loaders) & set(v["loaders"]))
                      and (not games or set(games) & set(v["game_versions"]))]
            return httpx.Response(200, json=result)
        if parts[1] == "version":
            for versions in self.versions.values():
                for v in versions:
                    if v["id"] == parts[2]:
                        return httpx.Response(200, json=v)
            return httpx.Response(404)
        return httpx.Response(404)


@pytest.fixture
def modrinth():
    from backend.services.modrinth_client import ModrinthClient, set_modrinth
    fake = FakeModrinth()
    client = ModrinthClient(base_url="https://api.modrinth.test/v2", transport=httpx.MockTransport(fake.handler))
    set_modrinth(client)
    yield fake
    set_modrinth(None)
    client.close()


# --- Заглушки установки Minecraft ------------------------------------------------------
@pytest.fixture
def fake_minecraft(monkeypatch):
    """Подменяет загрузку файлов игры: «установка» создаёт json/jar версии."""
    import minecraft_launcher_lib as mll

    from shared.paths import get_minecraft_dir

    calls: list[tuple] = []

    def write_version(version_id: str, inherits: str | None = None) -> None:
        folder = get_minecraft_dir() / "versions" / version_id
        folder.mkdir(parents=True, exist_ok=True)
        data = {"id": version_id, "type": "release"}
        if inherits:
            data["inheritsFrom"] = inherits
        else:
            (folder / f"{version_id}.jar").write_bytes(b"jar")
        (folder / f"{version_id}.json").write_text(json.dumps(data), encoding="utf-8")

    def install_minecraft_version(version_id, directory, callback=None):
        calls.append(("vanilla", version_id))
        if callback:
            callback.get("setStatus", lambda _m: None)("Download Libraries")
        write_version(version_id)

    class FakeLoader:
        def __init__(self, loader_id):
            self.loader_id = loader_id

        def get_name(self):
            return self.loader_id.capitalize()

        def is_minecraft_version_supported(self, version):
            return version.startswith("1.")

        def get_latest_loader_version(self, version):
            return "9.9.9"

        def get_loader_versions(self, version, stable_only):
            return ["9.9.9", "9.9.8"]

        def get_installed_version(self, mc_version, loader_version):
            return f"{self.loader_id}-loader-{loader_version}-{mc_version}"

        def install(self, mc_version, directory, *, loader_version=None, callback=None, java=None):
            calls.append((self.loader_id, mc_version, loader_version))
            launch_id = self.get_installed_version(mc_version, loader_version)
            write_version(launch_id, inherits=mc_version)
            return launch_id

    monkeypatch.setattr(mll.install, "install_minecraft_version", install_minecraft_version)
    monkeypatch.setattr(mll.mod_loader, "get_mod_loader", lambda loader_id: FakeLoader(loader_id))
    monkeypatch.setattr(mll.runtime, "get_executable_path", lambda component, directory: None)
    return calls
