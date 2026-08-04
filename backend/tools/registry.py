"""Tool registry: schema generation and dispatch."""

from tools import basic, calculator
from tools import notes as note_tools
from tools import todo as todo_tools

ALL_TOOLS = [
    basic.now_tool,
    calculator.calculate_tool,
    todo_tools.create_todo_tool,
    todo_tools.list_todos_tool,
    todo_tools.complete_todo_tool,
    todo_tools.delete_todo_tool,
    note_tools.create_note_tool,
    note_tools.search_notes_tool,
    note_tools.delete_note_tool,
]

TOOLS_BY_NAME = {t["name"]: t for t in ALL_TOOLS}


def to_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in ALL_TOOLS
    ]


async def dispatch(name: str, arguments: dict) -> dict:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"error": f"未知工具: {name}"}
    try:
        result = await tool["handler"](**arguments)
    except TypeError as exc:
        return {"error": f"工具参数错误: {exc}"}
    except Exception as exc:
        return {"error": f"工具执行失败: {exc}"}
    if result is None:
        return {"error": "工具未返回结果"}
    return result
