"""Reactive tool-calling loop that streams tokens and tool events."""

import json
from typing import Any, AsyncIterator, Callable

from agent.chat_agent import agent
from tools import registry

MAX_TOOL_ROUNDS = 5

Dispatch = Callable[[str, dict], Any]


class ToolAgent:
    def __init__(self, llm=None, dispatch: Dispatch = registry.dispatch) -> None:
        self.llm = llm or agent
        self.dispatch = dispatch

    async def stream(
        self, messages: list[dict], memory_context: str | None = None
    ) -> AsyncIterator[dict]:
        msgs = list(messages)
        for _ in range(MAX_TOOL_ROUNDS):
            tool_calls: dict[int, dict] = {}
            async for event in self.llm.stream_chat(
                msgs, memory_context=memory_context, tools=registry.to_openai_tools()
            ):
                if event["type"] == "content":
                    yield {"type": "token", "content": event["content"]}
                elif event["type"] == "tool_call_delta":
                    idx = event["index"]
                    tc = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    tc["id"] += event.get("id") or ""
                    tc["name"] += event.get("name") or ""
                    tc["arguments"] += event.get("arguments") or ""

            if not tool_calls:
                return  # 本轮回无工具调用，内容已流式产出

            assistant_tool_calls = []
            results: dict[int, Any] = {}
            for idx in sorted(tool_calls):
                tc = tool_calls[idx]
                name, args_str = tc["name"], tc["arguments"]
                try:
                    arguments = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
                    result = {"error": "工具参数不是合法 JSON"}
                else:
                    result = await self.dispatch(name, arguments)
                results[idx] = result
                yield {
                    "type": "tool",
                    "name": name,
                    "arguments": arguments,
                    "result": result,
                }
                assistant_tool_calls.append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": name, "arguments": args_str},
                    }
                )

            msgs.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})
            for idx in sorted(tool_calls):
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_calls[idx]["id"],
                        "content": json.dumps(results[idx], ensure_ascii=False),
                    }
                )

        # 轮数耗尽：强制产出最终答复
        msgs.append({"role": "user", "content": "工具调用已达上限，请基于已有信息回答。"})
        async for event in self.llm.stream_chat(
            msgs, memory_context=memory_context, tools=registry.to_openai_tools()
        ):
            if event["type"] == "content":
                yield {"type": "token", "content": event["content"]}
