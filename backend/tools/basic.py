"""Simple built-in tools with no external dependencies."""

from datetime import datetime

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


async def now() -> dict:
    dt = datetime.now().astimezone()
    return {
        "datetime": dt.isoformat(timespec="seconds"),
        "date": dt.date().isoformat(),
        "time": dt.strftime("%H:%M:%S"),
        "weekday": _WEEKDAYS[dt.weekday()],
    }


now_tool = {
    "name": "now",
    "description": "获取当前本地日期、时间、星期。需要推算日期（如'明天''下周三'）或回答当前时间时使用。",
    "parameters": {"type": "object", "properties": {}},
    "handler": now,
}
