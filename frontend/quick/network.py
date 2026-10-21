"""Сеть: избранные серверы с пингом и свой сервер (старт/стоп, адрес, консоль, бэкапы, настройки, моды)."""

from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from frontend.quick import art, fmt
from frontend.quick.bridge import Shell
from frontend.quick.library import Library
from frontend.services.api_client import ApiClient
from frontend.utils.logger import logger
from frontend.utils.worker import run_async
from shared.i18n import t

_POLL_MS = 2000
_CONSOLE_MS = 1000


def motd_spans(text: str) -> list[dict[str, Any]]:
    """MOTD с кодами «§» → куски {text, color (0–f или ""), bold, italic}."""
    spans: list[dict[str, Any]] = []
    color, bold, italic, buf = "", False, False, ""

    def flush() -> None:
        nonlocal buf
        if buf:
            spans.append({"text": buf, "color": color, "bold": bold, "italic": italic})
            buf = ""

    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "§" and i + 1 < len(text):
            flush()
            code = text[i + 1].lower()
            if code == "r":
                color, bold, italic = "", False, False
            elif code == "l":
                bold = True
            elif code == "o":
                italic = True
            elif code in "0123456789abcdef":
                color = code
            i += 2
            continue
        buf += " " if ch == "\n" else ch
        i += 1
    flush()
    return spans


# Настройки server.properties в окне «Настройки сервера»: ключ → вид поля
PROPERTY_FIELDS: tuple[tuple[str, str], ...] = (
    ("motd", "text"), ("max-players", "number"), ("gamemode", "gamemode"), ("difficulty", "difficulty"),
    ("hardcore", "bool"), ("pvp", "bool"), ("allow-flight", "bool"), ("allow-nether", "bool"),
    ("enable-command-block", "bool"), ("online-mode", "bool"), ("white-list", "bool"),
    ("view-distance", "number"), ("simulation-distance", "number"), ("spawn-protection", "number"),
    ("level-seed", "text"),
)
PROPERTY_CHOICES = {
    "gamemode": ("survival", "creative", "adventure", "spectator"),
    "difficulty": ("peaceful", "easy", "normal", "hard"),
}
PROPERTY_LABELS = {
    "motd": "hosting.prop_motd", "max-players": "hosting.prop_max_players", "gamemode": "hosting.prop_gamemode",
    "difficulty": "hosting.prop_difficulty", "hardcore": "hosting.prop_hardcore", "pvp": "hosting.prop_pvp",
    "allow-flight": "hosting.prop_allow_flight", "allow-nether": "q.prop_allow_nether",
    "enable-command-block": "hosting.prop_enable_command_block", "online-mode": "hosting.prop_online_mode",
    "white-list": "hosting.prop_white_list", "view-distance": "hosting.prop_view_distance",
    "simulation-distance": "q.prop_simulation_distance", "spawn-protection": "q.prop_spawn_protection",
    "level-seed": "hosting.prop_seed",
}
PROPERTY_HINTS = {"online-mode": "hosting.online_mode_hint", "level-seed": "hosting.seed_placeholder",
                  "spawn-protection": "q.prop_spawn_protection_hint"}
# Значения Minecraft, если ключа нет в server.properties
MINECRAFT_DEFAULTS = {"allow-nether": "true", "enable-command-block": "false", "simulation-distance": "10",
                      "spawn-protection": "16", "view-distance": "10", "max-players": "20"}
NUMBER_LIMITS = {"max-players": (1, 1000), "view-distance": (2, 32), "simulation-distance": (2, 32),
                 "spawn-protection": (0, 1000)}


def property_rows(values: dict[str, str]) -> list[dict[str, Any]]:
    """Строки формы настроек сервера из server.properties."""
    rows = []
    for key, kind in PROPERTY_FIELDS:
        value = values.get(key, MINECRAFT_DEFAULTS.get(key, ""))
        row: dict[str, Any] = {"key": key, "kind": kind, "label": t(PROPERTY_LABELS[key]),
                               "hint": t(PROPERTY_HINTS[key]) if key in PROPERTY_HINTS else "",
                               "value": value, "checked": value.lower() == "true", "options": []}
        if kind in PROPERTY_CHOICES:
            row["options"] = [{"value": v, "label": t(f"hosting.{kind}_{v}")} for v in PROPERTY_CHOICES[kind]]
        rows.append(row)
    return rows


def normalize_property(key: str, value: Any) -> str | None:
    """Значение для server.properties или None, если оно недопустимо."""
    kind = dict(PROPERTY_FIELDS).get(key)
    if kind is None:
        return None
    if kind == "bool":
        return "true" if value in (True, "true", "True", 1) else "false"
    text = " ".join(str(value).split())
    if kind == "number":
        if not text.lstrip("-").isdigit():
            return None
        low, high = NUMBER_LIMITS.get(key, (0, 100000))
        return str(min(max(int(text), low), high))
    if kind in PROPERTY_CHOICES:
        return text if text in PROPERTY_CHOICES[kind] else None
    return text[:200]


def ping_kind(ms: int | None) -> str:
    if ms is None:
        return "off"
    return "ok" if ms < 80 else "warn" if ms < 160 else "err"


class Network(QObject):
    serversChanged = pyqtSignal()
    ownChanged = pyqtSignal()
    consoleChanged = pyqtSignal()
    backupsChanged = pyqtSignal()
    propsChanged = pyqtSignal()
    modsChanged = pyqtSignal()

    def __init__(self, api: ApiClient, shell: Shell, library: Library, parent: QObject | None = None):
        super().__init__(parent)
        self.api = api
        self.shell = shell
        self.library = library
        self._servers: list[dict] = []
        self._loaded = False
        self._own: list[dict] = []
        self._selected_own = ""
        self._console: list[str] = []
        self._console_open = False
        self._backups: list[dict] = []
        self._props: list[dict] = []
        self._mods: list[dict] = []
        self._mods_loading = False
        self._poll = QTimer(self, interval=_POLL_MS)
        self._poll.timeout.connect(self.refreshOwn)
        self._console_timer = QTimer(self, interval=_CONSOLE_MS)
        self._console_timer.timeout.connect(self._fetch_console)

    # --- Свойства -------------------------------------------------------------------------------
    @pyqtProperty("QVariantList", notify=serversChanged)
    def servers(self) -> list[dict]:
        return self._servers

    @pyqtProperty(bool, notify=serversChanged)
    def loaded(self) -> bool:
        return self._loaded

    @pyqtProperty("QVariantList", notify=ownChanged)
    def ownServers(self) -> list[dict]:
        return self._own

    @pyqtProperty("QVariantMap", notify=ownChanged)
    def own(self) -> dict:
        return next((s for s in self._own if s["name"] == self._selected_own), self._own[0] if self._own else {})

    @pyqtProperty("QVariantList", notify=consoleChanged)
    def console(self) -> list[str]:
        return self._console

    @pyqtProperty("QVariantList", notify=backupsChanged)
    def backups(self) -> list[dict]:
        return self._backups

    @pyqtProperty("QVariantList", notify=propsChanged)
    def props(self) -> list[dict]:
        return self._props

    @pyqtProperty("QVariantList", notify=modsChanged)
    def mods(self) -> list[dict]:
        return self._mods

    @pyqtProperty(bool, notify=modsChanged)
    def modsLoading(self) -> bool:
        return self._mods_loading

    # --- Запуск раздела -------------------------------------------------------------------------
    @pyqtSlot()
    def activate(self) -> None:
        """Раздел открыт: обновить списки и следить за своим сервером."""
        self.refreshServers()
        self.refreshOwn()
        self._poll.start()

    @pyqtSlot()
    def deactivate(self) -> None:
        self._poll.stop()
        self._console_timer.stop()

    # --- Избранные серверы ----------------------------------------------------------------------
    @pyqtSlot()
    def refreshServers(self) -> None:
        def done(items: list[dict]) -> None:
            old = {s["id"]: s for s in self._servers}
            self._servers = [self._server_row(i, old.get(i["id"])) for i in items]
            self._loaded = True
            self.serversChanged.emit()
            for row in self._servers:
                self._ping(row["id"])

        run_async(self.api.servers, done, lambda msg: logger.warning(f"Серверы не загружены: {msg}"), owner=self)

    @staticmethod
    def _server_row(item: dict, old: dict | None) -> dict:
        address = item["host"] + ("" if item.get("port", 25565) == 25565 else f":{item['port']}")
        row = {"id": item["id"], "name": item["name"], "address": address, "instance": item.get("instance_name", ""),
               "seed": art.seed_of(item["name"]), "palette": art.palette_for(item["name"]),
               "motd": [], "ping": "", "pingKind": "", "players": "", "online": False, "pinging": True}
        if old:
            row.update({k: old[k] for k in ("motd", "ping", "pingKind", "players", "online")})
        return row

    def _ping(self, server_id: str) -> None:
        def done(info: dict) -> None:
            online = bool(info.get("online"))
            ms = info.get("latency_ms") if online else None
            players = f"{info.get('player_count') or 0}/{info.get('max_players') or 0}" if online else "—"
            motd = motd_spans(info.get("motd") or "") if online else [{"text": t("q.server_unavailable"),
                                                                        "color": "7", "bold": False, "italic": False}]
            self._update_server(server_id, motd=motd, ping=t("q.ms", n=ms) if ms is not None else "—",
                                pingKind=ping_kind(ms), players=players, online=online, pinging=False)

        def failed(_message: str) -> None:
            self._update_server(server_id, ping="—", pingKind="off", players="—", online=False, pinging=False)

        run_async(lambda: self.api.ping_server(server_id), done, failed, owner=self, background=True)

    def _update_server(self, server_id: str, **changes) -> None:
        self._servers = [dict(s, **changes) if s["id"] == server_id else s for s in self._servers]
        self.serversChanged.emit()

    @pyqtSlot(str, str)
    def addServer(self, name: str, address: str) -> None:
        host, _, port = address.strip().rpartition(":") if ":" in address else (address.strip(), "", "")
        port_num = int(port) if port.isdigit() else 25565

        def done(_r) -> None:
            self.shell.toast(t("q.server_added", name=name))
            self.refreshServers()

        run_async(lambda: self.api.create_server(name.strip() or host, host, port_num), done,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str)
    def removeServer(self, server_id: str) -> None:
        run_async(lambda: self.api.delete_server(server_id), lambda _r: self.refreshServers(),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, str)
    def connectTo(self, server_id: str, instance: str) -> None:
        """Запуск выбранной сборки с автоподключением — через Library, чтобы кнопка «Играть» показала прогресс."""
        row = next((s for s in self._servers if s["id"] == server_id), None)
        if not row:
            return
        name = instance or row["instance"] or self.library.selected
        if not name:
            self.shell.toast(t("q.need_build"), "err")
            return
        self.library.select(name)
        self.library.play(name, row["address"])
        self.shell.navigate("library")

    # --- Свой сервер ----------------------------------------------------------------------------
    @pyqtSlot()
    def refreshOwn(self) -> None:
        def done(items: list[dict]) -> None:
            self._own = [self._own_row(i) for i in items]
            self.ownChanged.emit()

        run_async(self.api.hosted_servers, done, lambda msg: logger.warning(f"Свой сервер не загружен: {msg}"),
                  owner=self)

    @staticmethod
    def _own_row(item: dict) -> dict:
        return {"name": item["name"], "version": item.get("version", ""), "core": item.get("core", "fabric"),
                "state": item.get("state", "stopped"), "installed": bool(item.get("installed")),
                "address": item.get("public_address", ""), "lan": item.get("lan_address", ""),
                "local": item.get("local_address", ""), "players": item.get("players") or [],
                "uptime": int(item.get("uptime_seconds") or 0), "memory": int(item.get("max_memory") or 0),
                "seed": art.seed_of(item["name"]), "tunnel": bool(item.get("tunnel", True))}

    @pyqtSlot(str)
    def selectOwn(self, name: str) -> None:
        self._selected_own = name
        self.ownChanged.emit()
        if self._console_open:
            self._fetch_console()

    def _own_name(self) -> str:
        return self.own.get("name", "")

    @pyqtSlot()
    def start(self) -> None:
        name = self._own_name()
        self._own_action(lambda: self.api.start_hosted_server(name))

    @pyqtSlot()
    def stop(self) -> None:
        name = self._own_name()
        self._own_action(lambda: self.api.stop_hosted_server(name))

    def _own_action(self, call) -> None:
        def done(result) -> None:
            if isinstance(result, dict) and "id" in result and "status" in result:
                self.shell.tracker.track(result, lambda _t: self.refreshOwn(),
                                         lambda msg: self.shell.toast(msg, "err"))
            self.refreshOwn()

        run_async(call, done, lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, str, int, str, bool)
    def createOwn(self, name: str, version: str, memory_mb: int, core: str, accept_eula: bool) -> None:
        def done(result) -> None:
            self._selected_own = name
            if isinstance(result, dict) and "id" in result and "status" in result:
                self.shell.tracker.track(result, lambda _t: (self.refreshOwn(), self.shell.toast(t("q.server_ready"))),
                                         lambda msg: self.shell.toast(msg, "err"))
            self.refreshOwn()

        run_async(lambda: self.api.create_hosted_server(name.strip(), version, memory_mb, accept_eula, core), done,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- Консоль --------------------------------------------------------------------------------
    @pyqtSlot(bool)
    def setConsoleOpen(self, value: bool) -> None:
        self._console_open = value
        if value:
            self._fetch_console()
            self._console_timer.start()
        else:
            self._console_timer.stop()

    def _fetch_console(self) -> None:
        name = self._own_name()
        if not name:
            return

        def done(lines: list[str]) -> None:
            if lines != self._console:
                self._console = lines
                self.consoleChanged.emit()

        run_async(lambda: self.api.server_console(name, 400), done, lambda _m: None, owner=self, background=True)

    @pyqtSlot(str)
    def sendCommand(self, command: str) -> None:
        name = self._own_name()
        command = command.strip().lstrip("/")
        if not command:
            return
        run_async(lambda: self.api.server_command(name, command), lambda _r: self._fetch_console(),
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- Бэкапы ----------------------------------------------------------------------------------
    @pyqtSlot()
    def loadBackups(self) -> None:
        name = self._own_name()

        def done(items: list[dict]) -> None:
            self._backups = [{"filename": b["filename"], "date": fmt.when(b.get("created_at")),
                              "size": fmt.size(b.get("size", 0)),
                              "reason": t(f"hosting.backup_reason_{b.get('reason', 'manual')}")} for b in items]
            self.backupsChanged.emit()

        run_async(lambda: self.api.server_backups(name), done, lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot()
    def createBackup(self) -> None:
        name = self._own_name()

        def started(result) -> None:
            if isinstance(result, dict) and "id" in result and "status" in result:
                self.shell.tracker.track(result, lambda _t: (self.loadBackups(), self.shell.toast(t("q.backup_done"))),
                                         lambda msg: self.shell.toast(msg, "err"))
            else:
                self.loadBackups()

        run_async(lambda: self.api.create_server_backup(name), started,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str)
    def restoreBackup(self, filename: str) -> None:
        name = self._own_name()

        def started(result) -> None:
            if isinstance(result, dict) and "id" in result and "status" in result:
                self.shell.tracker.track(result, lambda _t: self.shell.toast(t("q.backup_restored")),
                                         lambda msg: self.shell.toast(msg, "err"))

        run_async(lambda: self.api.restore_server_backup(name, filename), started,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- Настройки сервера (server.properties) -----------------------------------------------------
    @pyqtSlot()
    def loadProps(self) -> None:
        name = self._own_name()
        if not name:
            return

        def done(values: dict) -> None:
            self._props = property_rows(values)
            self.propsChanged.emit()

        run_async(lambda: self.api.server_properties(name), done, lambda msg: self.shell.toast(msg, "err"), owner=self)

    @pyqtSlot(str, "QVariant")
    def setProp(self, key: str, value: Any) -> None:
        name = self._own_name()
        normalized = normalize_property(key, value)
        current = next((r for r in self._props if r["key"] == key), None)
        if not name or normalized is None or (current and current["value"] == normalized):
            if normalized is None:
                self.loadProps()  # вернуть прежнее значение в поле
            return

        def done(values: dict) -> None:
            self._props = property_rows(values)
            self.propsChanged.emit()
            restart = self.own.get("state") in ("running", "starting")
            self.shell.toast(t("q.server_saved_restart") if restart else t("q.saved"))

        run_async(lambda: self.api.update_server_properties(name, {key: normalized}), done,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)

    # --- Моды и плагины своего сервера ------------------------------------------------------------
    @pyqtSlot()
    def loadMods(self) -> None:
        name = self._own_name()
        if not name:
            return
        self._mods_loading = True
        self.modsChanged.emit()

        def done(items: list[dict]) -> None:
            self._mods = [{"filename": m["filename"], "name": m.get("name") or m["filename"],
                           "version": m.get("version") or "", "size": fmt.size(m.get("size", 0)),
                           "enabled": bool(m.get("enabled", True)), "tunnel": bool(m.get("tunnel"))}
                          for m in items]
            self._mods_loading = False
            self.modsChanged.emit()

        def failed(message: str) -> None:
            self._mods_loading = False
            self.modsChanged.emit()
            self.shell.toast(message, "err")

        run_async(lambda: self.api.server_mods(name), done, failed, owner=self)

    @pyqtSlot(str)
    def removeMod(self, filename: str) -> None:
        name = self._own_name()
        title = next((m["name"] for m in self._mods if m["filename"] == filename), filename)

        def done(_r) -> None:
            self.shell.toast(t("q.mod_removed", name=title))
            self.loadMods()

        run_async(lambda: self.api.remove_server_mod(name, filename), done,
                  lambda msg: self.shell.toast(msg, "err"), owner=self)
