"""Agent-facing note tools, wrapping database.notes + semantic note memory."""

from database import notes as note_store
from memory.semantic import semantic
from tools import jsonable_row


async def create_note(content: str) -> dict:
    note = await note_store.create_note(content)
    try:
        await semantic.store_note(note["id"], content)
    except Exception:
        pass  # 嵌入失败不阻断记录
    return jsonable_row(note)


async def search_notes(query: str, top_k: int = 5) -> dict:
    hits = await semantic.search_notes(query, top_k=top_k)
    return {"hits": hits, "count": len(hits)}


async def delete_note(id: int) -> dict:
    removed = await note_store.delete_note(id)
    try:
        await semantic.delete_note(id)
    except Exception:
        pass
    return {"deleted": removed, "id": id}


create_note_tool = {
    "name": "create_note",
    "description": "记录一条笔记/备忘。用户说'记一下''记住'时使用，把想记的内容原样写入。",
    "parameters": {
        "type": "object",
        "properties": {"content": {"type": "string", "description": "笔记内容"}},
        "required": ["content"],
    },
    "handler": create_note,
}

search_notes_tool = {
    "name": "search_notes",
    "description": "按语义搜索过往笔记/备忘。用户问'我的笔记里有关于X的吗'时使用。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或描述"},
            "top_k": {"type": "integer", "description": "返回条数，默认 5，可选"},
        },
        "required": ["query"],
    },
    "handler": search_notes,
}

delete_note_tool = {
    "name": "delete_note",
    "description": "删除一条笔记。",
    "parameters": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "笔记 id"}},
        "required": ["id"],
    },
    "handler": delete_note,
}
