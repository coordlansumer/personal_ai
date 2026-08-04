import pytest

from tools import calculator


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("2+3*4", 14.0),
        ("(1+2)*3", 9.0),
        ("2**10", 1024.0),
        ("10/4", 2.5),
        ("7 % 3", 1.0),
        ("-5", -5.0),
        ("1.5 + 2.5", 4.0),
        ("2.0**10", 1024.0),
    ],
)
async def test_calculate_valid(expr, expected):
    assert await calculator.calculate(expression=expr) == {"result": expected}


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "os.system('echo hi')",
        "open('/etc/passwd')",
        "lambda: 1",
        "1; 2",
        "'abc'",
        "True",
        "a + b",
        "2**999999999999",
    ],
)
async def test_calculate_rejects_unsafe(expr):
    result = await calculator.calculate(expression=expr)
    assert "error" in result
