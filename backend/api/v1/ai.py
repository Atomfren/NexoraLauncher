"""AI-ассистент: потоковый ответ в формате NDJSON."""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.services.ai_assistant import LocalAssistant

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = []


class AIStatus(BaseModel):
    library_installed: bool
    model_path: str
    models_dir: str
    available: bool
    loaded: bool


@router.get("/ai/status", response_model=AIStatus)
def ai_status():
    return LocalAssistant().status()


@router.post("/ai/chat")
def ai_chat(request: ChatRequest):
    """Каждая строка ответа — JSON: ``{"token": ...}``, в конце ``{"done": true}`` или ``{"error": ...}``."""
    assistant = LocalAssistant()
    history = [m.model_dump() for m in request.history]

    def generate():
        try:
            for token in assistant.ask_stream(request.text, history):
                yield json.dumps({"token": token}, ensure_ascii=False) + "\n"
            yield json.dumps({"done": True}) + "\n"
        except Exception as e:  # noqa: BLE001 — ошибку передаём клиенту в потоке
            logger.error(f"AI chat error: {e}")
            yield json.dumps({"error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
