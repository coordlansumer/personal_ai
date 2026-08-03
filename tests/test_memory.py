from memory.store import MemoryStore


def test_create_and_get_history():
    store = MemoryStore()
    sid = store.create_session()
    assert store.get_history(sid) == []


def test_add_message_appends_in_order():
    store = MemoryStore()
    sid = store.create_session()
    store.add_message(sid, "user", "hi")
    store.add_message(sid, "assistant", "hello")
    assert store.get_history(sid) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_history_capped_at_max():
    store = MemoryStore(max_history=3)
    sid = store.create_session()
    for i in range(5):
        store.add_message(sid, "user", str(i))
    history = store.get_history(sid)
    assert len(history) == 3
    assert history[0] == {"role": "user", "content": "2"}


def test_clear_removes_session():
    store = MemoryStore()
    sid = store.create_session()
    store.add_message(sid, "user", "hi")
    store.clear(sid)
    assert store.get_history(sid) == []
