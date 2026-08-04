from types import SimpleNamespace

import pytest

from agent.chat_agent import APIKeyMissingError, ChatAgent


class FakeChunk:
    def __init__(self, content=None, tool_calls=None):
        self.choices = [
            SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))
        ]


class FakeCompletions:
    def __init__(self):
        self.captured = {}

    async def create(self, **kwargs):
        self.captured.update(kwargs)

        async def _gen():
            yield FakeChunk("你")
            yield FakeChunk("好")

        return _gen()


class FakeToolChunk:
    def __init__(self, tool_calls):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=tool_calls))]


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.chat = FakeChat()


def _tool_delta(index, id="", name="", arguments=""):
    return SimpleNamespace(
        index=index,
        id=id or None,
        function=SimpleNamespace(name=name or None, arguments=arguments),
    )


def test_validate_config_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    agent = ChatAgent()
    with pytest.raises(APIKeyMissingError):
        agent.validate_config()


@pytest.mark.asyncio
async def test_stream_chat_yields_content_events(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    events = [e async for e in agent.stream_chat([{"role": "user", "content": "hi"}])]
    assert events == [
        {"type": "content", "content": "你"},
        {"type": "content", "content": "好"},
    ]
    captured = agent._get_client().chat.completions.captured
    assert captured["stream"] is True
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1] == {"role": "user", "content": "hi"}
    assert "tools" not in captured


async def test_stream_chat_passes_tools(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    tools = [{"type": "function", "function": {"name": "now"}}]
    [e async for e in agent.stream_chat([{"role": "user", "content": "hi"}], tools=tools)]
    captured = agent._get_client().chat.completions.captured
    assert captured["tools"] == tools


async def test_stream_chat_yields_tool_call_deltas(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class ToolCompletions(FakeCompletions):
        async def create(self, **kwargs):
            self.captured.update(kwargs)

            async def _gen():
                yield FakeToolChunk([_tool_delta(0, id="call_1", name="create_todo", arguments="")])
                yield FakeToolChunk([_tool_delta(0, arguments='{"title": "买牛奶"}')])

            return _gen()

    class ToolChat:
        def __init__(self):
            self.completions = ToolCompletions()

    class ToolClient:
        def __init__(self, *args, **kwargs):
            self.chat = ToolChat()

    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", ToolClient)
    agent = ChatAgent()
    events = [e async for e in agent.stream_chat([{"role": "user", "content": "hi"}], tools=[{}])]
    assert events == [
        {"type": "tool_call_delta", "index": 0, "id": "call_1", "name": "create_todo", "arguments": ""},
        {"type": "tool_call_delta", "index": 0, "id": "", "name": "", "arguments": '{"title": "买牛奶"}'},
    ]


async def test_stream_chat_injects_memory_context(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    [e async for e in agent.stream_chat(
        [{"role": "user", "content": "hi"}],
        memory_context="以下是检索到的历史记忆：\n- 用户说：我喜欢咖啡",
    )]
    captured = agent._get_client().chat.completions.captured
    system = captured["messages"][0]["content"]
    assert "以下是检索到的历史记忆" in system
    assert "我喜欢咖啡" in system


async def test_default_model_is_v4_flash():
    from agent.chat_agent import DEFAULT_MODEL

    assert DEFAULT_MODEL == "deepseek-v4-flash"
