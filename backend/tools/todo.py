"""Agent-facing todo tools, wrapping database.todos."""

from database import todos as todo_store


async def create_todo(title: str, due_at: str | None = None, category: str | None = None) -> dict:
    return await todo_store.create_todo(title, due_at=due_at, category=category)


async def list_todos(status: str | None = None) -> dict:
    rows = await todo_store.list_todos(status=status)
    return {"todos": rows, "count": len(rows)}


async def complete_todo(id: int) -> dict:
    return {"completed": await todo_store.complete_todo(id), "id": id}


async def delete_todo(id: int) -> dict:
    return {"deleted": await todo_store.delete_todo(id), "id": id}


create_todo_tool = {
    "name": "create_todo",
    "description": "新建一条待办事项。用户要求设置提醒、记录待办、安排任务时使用。due_at 传 ISO 8601 格式（如 2026-08-05T15:00:00）；推算日期（如'明天'）先调用 now 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "待办内容"},
            "due_at": {"type": "string", "description": "截止时间，ISO 8601，可选"},
            "category": {"type": "string", "description": "分类，可选"},
        },
        "required": ["title"],
    },
    "handler": create_todo,
}

list_todos_tool = {
    "name": "list_todos",
    "description": "列出待办事项。用户问'我有哪些待办''明天要做什么'时使用，可按状态过滤。",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "done"], "description": "按状态过滤，可选"}
        },
    },
    "handler": list_todos,
}

complete_todo_tool = {
    "name": "complete_todo",
    "description": "把待办标记为已完成。用户说'做完了''搞定'时使用。",
    "parameters": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 id"}},
        "required": ["id"],
    },
    "handler": complete_todo,
}

delete_todo_tool = {
    "name": "delete_todo",
    "description": "删除一条待办事项。",
    "parameters": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 id"}},
        "required": ["id"],
    },
    "handler": delete_todo,
}
