"""Ping серверов Minecraft (Server List Ping)."""

from dataclasses import asdict, dataclass

from loguru import logger
from mcstatus import JavaServer


@dataclass
class PingResult:
    """Результат ping сервера."""

    online: bool
    player_count: int | None = None
    max_players: int | None = None
    version: str | None = None
    motd: str | None = None
    latency_ms: int | None = None
    icon: str | None = None  # data:image/png;base64,...
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def ping_server(host: str, port: int = 25565, timeout: float = 5.0) -> PingResult:
    """Пингует Java-сервер (учитывает SRV-записи, если порт стандартный)."""
    try:
        address = host if port == 25565 else f"{host}:{port}"
        server = JavaServer.lookup(address, timeout=timeout)
        status = server.status()
        motd = status.motd.to_plain() if hasattr(status, "motd") else str(status.description)
        return PingResult(
            online=True,
            player_count=status.players.online,
            max_players=status.players.max,
            version=status.version.name,
            motd=motd.strip(),
            latency_ms=int(status.latency),
            icon=status.icon,
        )
    except Exception as e:  # noqa: BLE001 — любые сетевые ошибки = офлайн
        logger.debug(f"Ping {host}:{port} не удался: {e}")
        return PingResult(online=False, error=str(e) or type(e).__name__)
