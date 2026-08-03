"""HTTP routes for the Personal AI OS backend."""

import json
import logging
import os
from typing import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.chat_agent import APIKeyMissingError, LLMError, agent
from database import db
from memory.semantic import semantic
from memory.short_term import short_term

logger = logging.getLogger("personal_ai.api")

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


def _build_memory_block(hits: list[dict]) -> str:
    lines = "\n".join(
        f"- [{hit['created_at'][:10]}] {hit['role']}：{hit['content']}" for hit in hits
    )
    return (
        "以下是检索到的历史记忆：\n"
        + lines
        + "\n请结合这些记忆回答，但不要编造记忆里没有的内容。"
    )


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
    return {"sessions": await db.list_sessions()}


async def _recent_context(session_id: str) -> list[dict]:
    try:
        cached = await short_term.get_context(session_id)
        if cached is not None:
            return cached
    except Exception as exc:
        logger.warning("Redis read failed, falling back to DB: %s", exc)
    try:
        recent = await db.load_recent_messages(session_id)
        await short_term.set_context(session_id, recent)
        return recent
    except Exception as exc:
        logger.warning("DB context load failed: %s", exc)
        return []


async def _recall_memory(message: str) -> str | None:
    try:
        hits = await semantic.recall(message)
    except Exception as exc:
        logger.warning("Semantic recall failed, proceeding without memory: %s", exc)
        return None
    return _build_memory_block(hits) if hits else None


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    if req.session_id:
        session_id = req.session_id
        try:
            if not await db.session_exists(session_id):
                raise HTTPException(status_code=404, detail="会话不存在")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("session_exists failed, continuing: %s", exc)
    else:
        session_id = uuid4().hex

    await db.upsert_session(session_id)
    recent = await _recent_context(session_id)
    history = [*recent, {"role": "user", "content": message}]
    memory_block = await _recall_memory(message)

    # Fail fast with a clean HTTP status if the API key is missing.
    try:
        agent.validate_config()
    except APIKeyMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("session", {"session_id": session_id})
        parts: list[str] = []
        try:
            async for token in agent.stream_chat(history, memory_context=memory_block):
                parts.append(token)
                yield _sse("token", {"content": token})
        except LLMError as exc:
            logger.error("LLM streaming failed for session %s: %s", session_id, exc)
            yield _sse("error", {"message": str(exc)})
            return
        except Exception as exc:
            logger.exception("Unhandled streaming error for session %s", session_id)
            yield _sse("error", {"message": f"服务内部错误: {exc}"})
            return

        # Persistence is best-effort and must not fail the stream.
        try:
            reply = "".join(parts)
            new_messages = [
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ]
            await db.append_messages(session_id, new_messages)
            await db.upsert_session(session_id)
            await short_term.set_context(session_id, [*recent, *new_messages])
            await semantic.store_message(session_id, "user", message)
            await semantic.store_message(session_id, "assistant", reply)
        except Exception as exc:
            logger.warning("Persistence failed for session %s: %s", session_id, exc)
        yield _sse("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
