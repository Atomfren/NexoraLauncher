"""Запущенные процессы игры: отслеживание, логи, статистика."""

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.errors import ConflictError, NotFoundError
from backend.core.instance import Instance

_LOG_LINES = 2000
_KEEP_EXITED = 20


@dataclass
class GameProcess:
    """Процесс Minecraft, запущенный лаунчером."""

    instance: str
    process: subprocess.Popen
    log_path: Path
    username: str
    version: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    exit_code: int | None = None
    lines: deque = field(default_factory=lambda: deque(maxlen=_LOG_LINES))
    stop_requested: bool = False
    # Публичный адрес мира, открытого через e4mc («Играть с друзьями»)
    public_address: str = ""

    @property
    def pid(self) -> int:
        return self.process.pid

    @property
    def status(self) -> str:
        if self.exit_code is None:
            return "running"
        if self.exit_code == 0 or self.stop_requested:
            return "exited"
        return "crashed"

    def to_dict(self) -> dict[str, Any]:
        end = self.ended_at or time.time()
        return {
            "pid": self.pid,
            "instance": self.instance,
            "username": self.username,
            "version": self.version,
            "status": self.status,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "duration_seconds": int(end - self.started_at),
            "log_path": str(self.log_path),
            "public_address": self.public_address if self.exit_code is None else "",
        }


class ProcessManager:
    """Реестр процессов игры."""

    def __init__(self) -> None:
        self._games: dict[int, GameProcess] = {}
        self._lock = threading.Lock()

    def running_for(self, instance_name: str) -> GameProcess | None:
        with self._lock:
            return next((g for g in self._games.values()
                         if g.instance == instance_name and g.exit_code is None), None)

    def start(self, instance: Instance, command: list[str], username: str, version: str) -> GameProcess:
        if self.running_for(instance.name):
            raise ConflictError(f"Инстанс '{instance.name}' уже запущен")
        instance.ensure_dirs()
        instance.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = instance.logs_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            command, cwd=str(instance.game_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs,
        )
        game = GameProcess(instance=instance.name, process=process, log_path=log_path,
                           username=username, version=version)
        with self._lock:
            self._games[process.pid] = game
            self._trim()
        threading.Thread(target=self._pump, args=(game,), daemon=True,
                         name=f"mc-log-{process.pid}").start()

        fresh = Instance.load(instance.name) or instance
        fresh.last_played = datetime.now().isoformat(timespec="seconds")
        fresh.play_count += 1
        fresh.save()
        logger.info(f"Minecraft запущен: '{instance.name}' pid={process.pid}")
        return game

    def _pump(self, game: GameProcess) -> None:
        """Читает вывод игры в файл и кольцевой буфер; фиксирует завершение."""
        try:
            with open(game.log_path, "w", encoding="utf-8") as log_file:
                assert game.process.stdout is not None
                for line in game.process.stdout:
                    game.lines.append(line.rstrip("\n"))
                    if "Domain assigned:" in line:
                        game.public_address = line.rsplit("Domain assigned:", 1)[1].strip()
                    elif "Local game no longer publicly hosted" in line:
                        game.public_address = ""
                    log_file.write(line)
                    log_file.flush()
        except (OSError, ValueError) as e:
            logger.warning(f"Ошибка чтения вывода pid={game.pid}: {e}")
        game.exit_code = game.process.wait()
        game.ended_at = time.time()
        logger.info(f"Minecraft '{game.instance}' завершён, код {game.exit_code}")
        try:
            instance = Instance.load(game.instance)
            if instance:
                instance.record_session(int(game.ended_at - game.started_at))
        except Exception as e:  # noqa: BLE001 — инстанс могли удалить/переименовать
            logger.warning(f"Не удалось обновить статистику '{game.instance}': {e}")

    def _trim(self) -> None:
        exited = sorted((g for g in self._games.values() if g.exit_code is not None),
                        key=lambda g: g.started_at)
        for g in exited[: max(0, len(exited) - _KEEP_EXITED)]:
            self._games.pop(g.pid, None)

    def get(self, pid: int) -> GameProcess:
        game = self._games.get(pid)
        if game is None:
            raise NotFoundError(f"Процесс {pid} не найден")
        return game

    def all(self) -> list[GameProcess]:
        with self._lock:
            return sorted(self._games.values(), key=lambda g: g.started_at, reverse=True)

    def stop(self, pid: int) -> GameProcess:
        game = self.get(pid)
        if game.exit_code is None:
            game.stop_requested = True
            game.process.terminate()
            try:
                game.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                game.process.kill()
        return game

    def log_tail(self, pid: int, lines: int = 200) -> list[str]:
        game = self.get(pid)
        return list(game.lines)[-lines:]

    def stop_all(self) -> None:
        for game in self.all():
            if game.exit_code is None:
                try:
                    self.stop(game.pid)
                except Exception:  # noqa: BLE001
                    pass


process_manager = ProcessManager()
