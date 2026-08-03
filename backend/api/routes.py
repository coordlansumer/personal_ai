"""HTTP routes for the Personal AI OS backend."""

import json
import logging
import os
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.chat_agent import APIKeyMissingError, LLMError, agent
from database import db
from memory.store import store

logger = logging.getLogger("personal_ai.api")

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


@router.get("/health")
async def health() -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    return {
        "status": "ok",
        "llm_configured": bool(api_key),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }


@router.get("/sessions")
async def sessions() -> dict:
    return {"sessions": db.list_sessions()}


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    if req.session_id:
        session_id = req.session_id
        if not store.has_session(session_id):
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        session_id = store.create_session()

    history = [*store.get_history(session_id), {"role": "user", "content": message}]

    # Fail fast with a clean HTTP status if the API key is missing.
    try:
        agent.validate_config()
    except APIKeyMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("session", {"session_id": session_id})
        parts: list[str] = []
        try:
            async for token in agent.stream_chat(history):
                parts.append(token)
                yield _sse("token", {"content": token})
            store.add_message(session_id, "user", message)
            store.add_message(session_id, "assistant", "".join(parts))
            db.upsert_session(session_id)
            yield _sse("done", {})
        except LLMError as exc:
            logger.error("LLM streaming failed for session %s: %s", session_id, exc)
            yield _sse("error", {"message": str(exc)})
        except Exception as exc:  # unexpected backend failure
            logger.exception("Unhandled streaming error for session %s", session_id)
            yield _sse("error", {"message": f"服务内部错误: {exc}"})

    return StreamingResponse(
        event_stream(), media_type="text/event-stream"
    )
