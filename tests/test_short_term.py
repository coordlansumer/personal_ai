import pytest

from memory.short_term import ShortTermMemory


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value

    async def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def mem():
    return ShortTermMemory(redis_client=FakeRedis(), context_limit=3)


async def test_get_context_unknown_returns_none(mem):
    assert await mem.get_context("nope") is None


async def test_set_then_get_roundtrip(mem):
    msgs = [{"role": "user", "content": "hi"}]
    await mem.set_context("s1", msgs)
    assert await mem.get_context("s1") == msgs


async def test_set_context_truncates_to_limit(mem):
    msgs = [{"role": "user", "content": str(i)} for i in range(5)]
    await mem.set_context("s1", msgs)
    assert len(await mem.get_context("s1")) == 3


async def test_delete_removes(mem):
    await mem.set_context("s1", [{"role": "user", "content": "hi"}])
    await mem.delete_context("s1")
    assert await mem.get_context("s1") is None
