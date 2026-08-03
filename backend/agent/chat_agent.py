"""DeepSeek-backed chat agent using the OpenAI-compatible SDK.

Streams assistant tokens back to the caller. Errors are mapped to typed
exceptions so the API layer can return clean status codes.
"""

import os
from typing import AsyncIterator

from openai import AsyncOpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "你是 Personal AI OS 的助手，一个帮助用户完成任务的智能助手。"
    "回答要简洁、准确、友好。"
)


class APIKeyMissingError(Exception):
    pass


class LLMError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _settings() -> tuple[str, str, str]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip()
    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip()
    return api_key, base_url, model


class ChatAgent:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self.model = DEFAULT_MODEL

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            api_key, base_url, model = _settings()
            if not api_key:
                raise APIKeyMissingError(
                    "未配置 DEEPSEEK_API_KEY，请在 .env 中设置后重启服务"
                )
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self.model = model
        return self._client

    def validate_config(self) -> None:
        self._get_client()

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        memory_context: str | None = None,
    ) -> AsyncIterator[str]:
        client = self._get_client()
        system = SYSTEM_PROMPT
        if memory_context:
            system = f"{system}\n\n{memory_context}"
        full_messages = [{"role": "system", "content": system}, *messages]
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                stream=True,
                temperature=0.7,
            )
        except Exception as exc:  # network / auth errors from the provider
            raise LLMError(f"调用 DeepSeek 失败: {exc}") from exc

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


agent = ChatAgent()
