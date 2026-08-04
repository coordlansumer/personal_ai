import pytest

from tools import basic
from tools import registry


async def test_now_returns_datetime_fields():
    result = await basic.now()
    assert "datetime" in result and "date" in result and "time" in result
    assert result["weekday"] in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def test_to_openai_tools_has_all_nine():
    tools = registry.to_openai_tools()
    names = [t["function"]["name"] for t in tools]
    assert len(tools) == 9
    for expected in [
        "now", "calculate",
        "create_todo", "list_todos", "complete_todo", "delete_todo",
        "create_note", "search_notes", "delete_note",
    ]:
        assert expected in names
    first = tools[0]
    assert first["type"] == "function"
    assert "parameters" in first["function"]
    assert "description" in first["function"]


async def test_dispatch_calls_handler(monkeypatch):
    calls = []

    async def handler(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setitem(
        registry.TOOLS_BY_NAME,
        "test_tool",
        {"name": "test_tool", "description": "", "parameters": {}, "handler": handler},
    )
    assert await registry.dispatch("test_tool", {"a": 1}) == {"ok": True}
    assert calls == [{"a": 1}]


async def test_dispatch_unknown_tool_returns_error():
    result = await registry.dispatch("nope", {})
    assert "error" in result
    assert "nope" in result["error"]


async def test_dispatch_wraps_handler_exception(monkeypatch):
    async def handler(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        registry.TOOLS_BY_NAME,
        "bad",
        {"name": "bad", "description": "", "parameters": {}, "handler": handler},
    )
    result = await registry.dispatch("bad", {})
    assert "error" in result
    assert "boom" in result["error"]
