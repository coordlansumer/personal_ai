from types import SimpleNamespace

import pytest

from agent.chat_agent import APIKeyMissingError, ChatAgent


class FakeChunk:
    def __init__(self, content):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]


class FakeCompletions:
    def __init__(self):
        self.captured = {}

    async def create(self, **kwargs):
        self.captured.update(kwargs)

        async def _gen():
            yield FakeChunk("你")
            yield FakeChunk("好")

        return _gen()


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.chat = FakeChat()


def test_validate_config_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    agent = ChatAgent()
    with pytest.raises(APIKeyMissingError):
        agent.validate_config()


@pytest.mark.asyncio
async def test_stream_chat_yields_tokens_and_builds_messages(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    tokens = []
    async for t in agent.stream_chat([{"role": "user", "content": "hi"}]):
        tokens.append(t)
    assert tokens == ["你", "好"]

    captured = agent._get_client().chat.completions.captured
    assert captured["stream"] is True
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1] == {"role": "user", "content": "hi"}
