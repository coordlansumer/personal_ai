import json

import pytest

from agent.orchestrator import MAX_TOOL_ROUNDS, ToolAgent


class FakeLLM:
    """Scripted per-round event streams; one list per stream_chat call."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    async def stream_chat(self, messages, memory_context=None, tools=None):
        self.calls.append(
            {"messages": list(messages), "memory_context": memory_context, "tools": tools}
        )
        for ev in self.rounds.pop(0):
            yield ev


def _tool_delta(idx, id_, name, args):
    return {"type": "tool_call_delta", "index": idx, "id": id_, "name": name, "arguments": args}


async def _collect(agent, messages, memory_context=None):
    return [e async for e in agent.stream(messages, memory_context=memory_context)]


async def test_roundtrip_tool_then_answer():
    fake = FakeLLM(
        [
            [_tool_delta(0, "call_1", "create_todo", ""), _tool_delta(0, "", "", '{"title": "买牛奶"}')],
            [{"type": "content", "content": "已添加待办"}],
        ]
    )

    async def fake_dispatch(name, arguments):
        assert name == "create_todo"
        assert arguments == {"title": "买牛奶"}
        return {"id": 1, "title": "买牛奶", "status": "pending"}

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "记录待办"}])

    tools = [e for e in events if e["type"] == "tool"]
    assert len(tools) == 1
    assert tools[0]["name"] == "create_todo"
    assert tools[0]["arguments"] == {"title": "买牛奶"}
    assert tools[0]["result"]["id"] == 1
    assert [e["content"] for e in events if e["type"] == "token"] == ["已添加待办"]

    # second round carries assistant tool_calls + tool result
    second = fake.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["id"] == "call_1"
    assert second[-1]["role"] == "tool"
    assert json.loads(second[-1]["content"])["id"] == 1
    assert fake.calls[0]["tools"], "tools payload should be passed each round"
    assert fake.calls[0]["messages"][-1] == {"role": "user", "content": "记录待办"}


async def test_passes_memory_context():
    fake = FakeLLM([[{"type": "content", "content": "hi"}]])
    agent = ToolAgent(llm=fake)
    await _collect(agent, [{"role": "user", "content": "hi"}], memory_context="记忆块")
    assert fake.calls[0]["memory_context"] == "记忆块"


async def test_multiple_parallel_tools_accumulate_by_index():
    fake = FakeLLM(
        [
            [
                _tool_delta(0, "c0", "now", "{}"),
                _tool_delta(1, "c1", "calculate", '{"expression": "2+2"}'),
            ],
            [{"type": "content", "content": "done"}],
        ]
    )

    async def fake_dispatch(name, arguments):
        return {"ok": name}

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "x"}])
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["name"] for t in tools] == ["now", "calculate"]
    # 一条 assistant(tool_calls 列表) + 两条 tool 结果，按 index 顺序
    second = fake.calls[1]["messages"]
    assert [m["role"] for m in second[-4:]] == ["user", "assistant", "tool", "tool"]
    assert second[-4 + 1]["tool_calls"][0]["id"] == "c0"
    assert second[-4 + 1]["tool_calls"][1]["id"] == "c1"


async def test_round_cap_forces_final_answer():
    rounds = []
    for _ in range(MAX_TOOL_ROUNDS):
        rounds.append([_tool_delta(0, "c", "now", "{}")])
    rounds.append([{"type": "content", "content": "已达上限的答复"}])

    fake = FakeLLM(rounds)

    async def fake_dispatch(name, arguments):
        return {"ok": True}

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "x"}])

    tools = [e for e in events if e["type"] == "tool"]
    assert len(tools) == MAX_TOOL_ROUNDS
    assert [e["content"] for e in events if e["type"] == "token"] == ["已达上限的答复"]
    # cap message was appended before the final call
    assert fake.calls[-1]["messages"][-1]["content"] == "工具调用已达上限，请基于已有信息回答。"


async def test_json_parse_failure_becomes_error_result():
    fake = FakeLLM(
        [
            [_tool_delta(0, "c1", "create_todo", '{bad json')],
            [{"type": "content", "content": "处理不了"}],
        ]
    )

    async def fake_dispatch(name, arguments):
        raise AssertionError("dispatch 不应被调用")

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "x"}])
    tools = [e for e in events if e["type"] == "tool"]
    assert "error" in tools[0]["result"]
