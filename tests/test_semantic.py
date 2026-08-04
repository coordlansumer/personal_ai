from types import SimpleNamespace

import pytest

from memory.semantic import COLLECTION, NOTES_COLLECTION, SemanticMemory


class FakeEmbedder:
    def __init__(self, dim=4):
        self.dim = dim
        self.called_with = []

    def embed(self, texts):
        self.called_with.extend(texts)
        for _ in texts:
            yield [0.1] * self.dim


class FakeHit:
    def __init__(self, score, payload):
        self.score = score
        self.payload = payload


class FakeQdrant:
    def __init__(self, collection_names=None):
        self.names = set(collection_names or [])
        self.created = []
        self.upserted = []
        self.hits = []
        self.last_search = {}
        self.deleted = []

    async def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.names])

    async def create_collection(self, name, vectors_config):
        self.created.append((name, vectors_config))

    async def upsert(self, collection, points):
        self.upserted.extend(points)

    async def search(self, collection, query_vector, limit, with_payload):
        self.last_search = {"collection": collection, "limit": limit}
        return self.hits

    async def delete(self, collection, points_selector):
        self.deleted.append((collection, points_selector))


@pytest.fixture
def mem():
    fake = FakeQdrant()
    return SemanticMemory(embedder=FakeEmbedder(), client=fake)


async def test_ensure_collection_creates_when_missing(mem):
    await mem.ensure_collection()
    assert mem._client.created[0][0] == COLLECTION


async def test_ensure_collection_skips_when_exists():
    fake = FakeQdrant(collection_names=[COLLECTION])
    sm = SemanticMemory(embedder=FakeEmbedder(), client=fake)
    await sm.ensure_collection()
    assert fake.created == []


async def test_store_message_embeds_and_upserts(mem):
    await mem.store_message("s1", "user", "我喜欢咖啡")
    point = mem._client.upserted[0]
    assert point.payload["session_id"] == "s1"
    assert point.payload["role"] == "user"
    assert point.payload["content"] == "我喜欢咖啡"
    assert len(point.vector) == 4


async def test_recall_filters_below_threshold(mem):
    mem._client.hits = [
        FakeHit(score=0.9, payload={"content": "A", "role": "user", "created_at": "2026-01-01T00:00:00+00:00"}),
        FakeHit(score=0.1, payload={"content": "B", "role": "assistant", "created_at": "2026-01-01T00:00:00+00:00"}),
    ]
    results = await mem.recall("咖啡")
    assert [r["content"] for r in results] == ["A"]
    assert results[0]["score"] == 0.9
    assert mem._client.last_search["limit"] == 5


async def test_ensure_notes_collection_creates_when_missing(mem):
    await mem.ensure_notes_collection()
    assert mem._client.created[0][0] == NOTES_COLLECTION


async def test_store_note_embeds_and_upserts(mem):
    await mem.store_note(42, "买咖啡豆")
    point = mem._client.upserted[0]
    assert point.payload["note_id"] == "42"
    assert point.payload["content"] == "买咖啡豆"
    assert len(point.vector) == 4


async def test_search_notes_returns_hits(mem):
    mem._client.hits = [FakeHit(score=0.9, payload={"note_id": "42", "content": "买咖啡豆"})]
    hits = await mem.search_notes("咖啡", top_k=3)
    assert hits == [{"note_id": "42", "content": "买咖啡豆", "score": 0.9}]
    assert mem._client.last_search["collection"] == NOTES_COLLECTION


async def test_delete_note_filters_by_note_id(mem):
    await mem.delete_note(42)
    coll, selector = mem._client.deleted[0]
    assert coll == NOTES_COLLECTION
    must = selector.filter.must
    assert must[0].key == "note_id"
    assert must[0].match.value == "42"
