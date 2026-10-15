"""Локальный AI ассистент на llama-cpp-python (опциональная функция).

Модель (*.gguf) ищется по пути из настроек backend либо в ``<data>/models``.
Если llama-cpp-python не установлен, ассистент сообщает об этом, а остальной
лаунчер работает как обычно.
"""

import threading
from collections.abc import Iterator
from pathlib import Path

from loguru import logger

from backend.config import settings
from shared.paths import get_models_dir

try:
    from llama_cpp import Llama
    _LLAMA_AVAILABLE = True
except ImportError:  # pragma: no cover — зависит от окружения
    Llama = None
    _LLAMA_AVAILABLE = False

SYSTEM_PROMPT = (
    "You are NexoraLauncher AI Assistant. Help users with Minecraft and launcher questions: "
    "installing versions, mod loaders (Fabric, Forge, Quilt, NeoForge), mods, Java and crashes. "
    "Answer in the same language as the user. Be concise and helpful."
)
_MAX_HISTORY = 8


class LocalAssistant:
    """Синглтон с ленивой загрузкой модели."""

    _instance: "LocalAssistant | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._model = None
                cls._instance._generate_lock = threading.Lock()
        return cls._instance

    @staticmethod
    def find_model() -> Path | None:
        if settings.ai_model_path and Path(settings.ai_model_path).is_file():
            return Path(settings.ai_model_path)
        models_dir = get_models_dir()
        if models_dir.is_dir():
            models = sorted(models_dir.glob("*.gguf"))
            if models:
                return models[0]
        return None

    def status(self) -> dict:
        model = self.find_model()
        return {
            "library_installed": _LLAMA_AVAILABLE,
            "model_path": str(model) if model else "",
            "models_dir": str(get_models_dir()),
            "available": _LLAMA_AVAILABLE and model is not None,
            "loaded": self._model is not None,
        }

    @property
    def is_available(self) -> bool:
        return self.status()["available"]

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not _LLAMA_AVAILABLE:
            raise RuntimeError("llama-cpp-python не установлен: pip install llama-cpp-python")
        model_path = self.find_model()
        if model_path is None:
            raise FileNotFoundError(f"Модель *.gguf не найдена. Поместите её в {get_models_dir()}")
        logger.info(f"Загрузка LLM из {model_path}")
        self._model = Llama(model_path=str(model_path), n_ctx=settings.ai_n_ctx,
                            n_threads=settings.ai_n_threads, verbose=False)
        return self._model

    @staticmethod
    def _messages(message: str, history: list[dict] | None) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in (history or [])[-_MAX_HISTORY:]:
            if item.get("role") in ("user", "assistant") and item.get("content"):
                messages.append({"role": item["role"], "content": str(item["content"])})
        messages.append({"role": "user", "content": message})
        return messages

    def ask_stream(self, message: str, history: list[dict] | None = None) -> Iterator[str]:
        """Генератор токенов ответа (синхронный — вызывать из потока)."""
        model = self._load_model()
        with self._generate_lock:
            stream = model.create_chat_completion(
                messages=self._messages(message, history), max_tokens=768, temperature=0.7, stream=True,
            )
            for chunk in stream:
                delta = chunk["choices"][0].get("delta", {})
                if token := delta.get("content"):
                    yield token

    def ask(self, message: str, history: list[dict] | None = None) -> str:
        return "".join(self.ask_stream(message, history)).strip()
