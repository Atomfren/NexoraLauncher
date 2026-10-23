"""Языки с сайта: подписанный список, установка с проверкой суммы, переключение, удаление."""

import base64
import hashlib
import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.core import languages, self_update
from shared import i18n

INDEX = "https://nexoralauncher.ru/languages/languages.json"


def pack_bytes(code: str = "uk", name: str = "Українська", version: str = "1.0",
               strings: dict | None = None) -> bytes:
    pack = {"code": code, "name": name, "version": version, "author": "Спільнота",
            "strings": strings if strings is not None else {"q.play": "Грати", "common.save": "Зберегти"}}
    return (json.dumps(pack, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@pytest.fixture
def site(monkeypatch):
    """Поддельный сайт с настоящей подписью: ``state`` позволяет испортить любой кусок."""
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(self_update, "UPDATE_PUBLIC_KEY", base64.b64encode(public).decode("ascii"))
    monkeypatch.setattr(languages, "LANGUAGE_INDEX_URLS", (INDEX,))
    monkeypatch.setattr(languages, "index_urls", lambda: [INDEX])

    # Список подписывается для исходного пакета: если потом подменить файл, сумма не сойдётся
    body = pack_bytes()
    index = {"generated": "2026-10-22",
             "languages": [{"code": "uk", "name": "Українська", "version": "1.0", "author": "Спільнота",
                            "file": "uk.json", "size": len(body),
                            "sha256": hashlib.sha256(body).hexdigest(), "translated": 2, "total": 100}]}
    state = {"pack": body, "sign_with": key, "status": {}, "index": index, "raw_index": None}

    def index_bytes() -> bytes:
        if state["raw_index"] is not None:
            return state["raw_index"]
        return (json.dumps(state["index"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, code in state["status"].items():
            if url.startswith(prefix):
                return httpx.Response(code)
        if url.endswith("languages.json"):
            return httpx.Response(200, content=index_bytes())
        if url.endswith("languages.json.sig"):
            return httpx.Response(200, text=base64.b64encode(state["sign_with"].sign(index_bytes())).decode())
        if url.endswith("uk.json"):
            return httpx.Response(200, content=state["pack"])
        return httpx.Response(404)

    monkeypatch.setattr(languages, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))
    yield state
    i18n.drop_pack("uk")


# --- Список с сайта ------------------------------------------------------------------------------
def test_catalog_lists_languages(client, site):
    data = client.get("/api/v1/languages").json()
    assert [entry["code"] for entry in data["builtin"]] == ["ru", "en"]
    assert data["available"][0]["name"] == "Українська" and data["available"][0]["installed"] is False
    assert data["error"] == ""


def test_offline_mode_does_not_touch_the_site(client, site, monkeypatch):
    monkeypatch.setattr(languages, "catalog", lambda: pytest.fail("на сайт ходить не должны"))
    data = client.get("/api/v1/languages", params={"online": "false"}).json()
    assert data["available"] == [] and data["installed"] == []


def test_site_unavailable_is_reported_not_crashed(client, site):
    site["status"] = {INDEX: 503}
    data = client.get("/api/v1/languages").json()
    assert data["available"] == [] and "Не удалось" in data["error"]
    assert [entry["code"] for entry in data["builtin"]] == ["ru", "en"]


def test_tampered_index_is_rejected(client, site):
    """Подменённый список (подпись осталась от прежнего) не принимается."""
    good = json.dumps({"generated": "2026-10-22", "languages": []}, ensure_ascii=False).encode()
    site["sign_with"] = Ed25519PrivateKey.generate()
    site["raw_index"] = good
    assert "одпись" in client.get("/api/v1/languages").json()["error"]


# --- Установка -----------------------------------------------------------------------------------
def test_install_switches_interface_language(client, wait_task, site):
    task = wait_task(client.post("/api/v1/languages/uk/install").json()["id"])
    assert task["status"] == "done", task["error"]
    assert task["result"]["translated"] == 2

    assert (languages.languages_dir() / "uk.json").is_file()
    assert "uk" in i18n.available_languages()
    assert i18n.language_name("uk") == "Українська"

    # Язык можно выбрать в настройках, хотя в сборке его не было
    assert client.patch("/api/v1/settings", json={"language": "uk"}).json()["language"] == "uk"
    i18n.set_language("uk")
    assert i18n.t("q.play") == "Грати"
    # Непереведённое не превращается в ключ, а показывается по-английски
    assert i18n.t("q.set_updates") == i18n._EN["q.set_updates"]
    i18n.set_language("ru")

    listed = client.get("/api/v1/languages").json()
    assert listed["installed"][0]["code"] == "uk"
    assert listed["available"][0]["installed"] is True


def test_substituted_pack_is_rejected(client, wait_task, site):
    """Сумма в подписанном списке не сошлась — перевод не ставится."""
    site["pack"] = pack_bytes(strings={"q.play": "Зламано"})  # список подписан для другого файла
    task = wait_task(client.post("/api/v1/languages/uk/install").json()["id"])
    assert task["status"] == "failed" and "умма" in task["error"]
    assert not (languages.languages_dir() / "uk.json").exists()
    assert "uk" not in i18n.available_languages()


def test_broken_pack_is_rejected(client, wait_task, site):
    """Файл скачался целиком (сумма сошлась), но внутри не перевод."""
    broken = json.dumps({"code": "uk", "strings": "не объект"}, ensure_ascii=False).encode("utf-8")
    site["pack"] = broken
    site["index"]["languages"][0].update(size=len(broken), sha256=hashlib.sha256(broken).hexdigest())
    task = wait_task(client.post("/api/v1/languages/uk/install").json()["id"])
    assert task["status"] == "failed" and "испорчен" in task["error"]


def test_builtin_language_cannot_be_installed(client, wait_task, site):
    task = wait_task(client.post("/api/v1/languages/en/install").json()["id"])
    assert task["status"] == "failed" and "встроен" in task["error"]


def test_unknown_language_is_404(client, wait_task, site):
    task = wait_task(client.post("/api/v1/languages/de/install").json()["id"])
    assert task["status"] == "failed" and "нет на сайте" in task["error"]


# --- Удаление ------------------------------------------------------------------------------------
def test_remove_returns_interface_to_russian(client, wait_task, site):
    wait_task(client.post("/api/v1/languages/uk/install").json()["id"])
    client.patch("/api/v1/settings", json={"language": "uk"})

    assert client.delete("/api/v1/languages/uk").json()["removed"] is True
    assert not (languages.languages_dir() / "uk.json").exists()
    assert "uk" not in i18n.available_languages()
    assert client.get("/api/v1/settings").json()["language"] == "ru"


def test_remove_unknown_is_404(client, site):
    assert client.delete("/api/v1/languages/uk").status_code == 404


# --- Пакеты с диска ------------------------------------------------------------------------------
def test_installed_packs_load_on_start(client, wait_task, site):
    wait_task(client.post("/api/v1/languages/uk/install").json()["id"])
    i18n.drop_pack("uk")
    assert "uk" not in i18n.available_languages()

    assert languages.load_installed() == ["uk"]
    assert i18n.language_name("uk") == "Українська"


def test_damaged_file_on_disk_is_skipped(client, site):
    languages.languages_dir().mkdir(parents=True, exist_ok=True)
    (languages.languages_dir() / "br.json").write_text("не json", encoding="utf-8")
    assert languages.load_installed() == []  # и не падаем
