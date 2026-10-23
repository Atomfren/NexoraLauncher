"""Сценарий запуска инстанса: установка → авторизация → старт процесса."""

from typing import Any

from backend.core import gpu
from backend.core.auth import AuthManager
from backend.core.errors import ConflictError
from backend.core.instance import InstanceManager
from backend.core.minecraft import MinecraftManager
from backend.core.process_manager import process_manager
from backend.core.tasks import Task, task_manager
from shared.config import AppConfig


def launch_instance(name: str, server: str = "", port: int = 25565) -> Task:
    """Создаёт фоновую задачу запуска. Результат задачи — данные процесса."""
    instance = InstanceManager.get(name)
    if process_manager.running_for(instance.name):
        raise ConflictError(f"Инстанс '{instance.name}' уже запущен")
    config = AppConfig.load()
    # Проверяем аккаунт до долгой установки, чтобы сразу показать понятную ошибку
    if AuthManager.get_active() is None:
        AuthManager.get_launch_credentials(config.ms_client_id)

    def run(task: Task) -> dict[str, Any]:
        mc = MinecraftManager()
        launch_id = mc.prepare_instance(instance, task)
        task.set_max(0)
        task.set_status("Авторизация…")
        credentials = AuthManager.get_launch_credentials(config.ms_client_id)
        task.set_status("Запуск игры…")
        command = mc.build_command(instance, launch_id, credentials, config, server=server, port=port)
        # Выбор видеокарты делается для конкретного java.exe и прямо перед запуском:
        # у разных сборок Java разная, и выбор должен достаться именно той, что сейчас стартует
        gpu.apply_preference(command[0], config.gpu_preference)
        mc.sync_game_options(instance, config)
        game = process_manager.start(instance, command, credentials["username"], launch_id)
        AppConfig.load().update(last_instance=instance.name)
        return game.to_dict()

    return task_manager.submit("launch", f"Запуск «{instance.display_name}»", run)
