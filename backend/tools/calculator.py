"""Safe arithmetic evaluator for the calculate tool.

Whitelist AST nodes and evaluate recursively; never use eval/exec.
"""

import ast
import operator

ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

MAX_POW_EXPONENT = 1000


def _eval_node(node):
    if isinstance(node, ast.Constant):
        # bool 是 int 子类，需显式排除（否则 True 会被当数字 1）
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ValueError("只支持数字运算")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ValueError("不支持的运算符")
        if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
            if abs(node.right.value) > MAX_POW_EXPONENT:
                raise ValueError("指数过大")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNOPS.get(type(node.op))
        if op is None:
            raise ValueError("不支持的运算符")
        return op(_eval_node(node.operand))
    raise ValueError("不支持的表达式")


async def calculate(expression: str) -> dict:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return {"error": "表达式语法错误"}
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            return {"error": "表达式包含不支持的语法"}
    try:
        value = _eval_node(tree.body)
    except (ZeroDivisionError, ValueError, OverflowError) as exc:
        return {"error": str(exc)}
    return {"result": value}


calculate_tool = {
    "name": "calculate",
    "description": "执行安全的数学表达式计算（四则运算、取余、乘方、括号）。需要算数或单位换算时使用。",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '2+3*4'"}
        },
        "required": ["expression"],
    },
    "handler": calculate,
}
