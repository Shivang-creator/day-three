import os
from pathlib import Path

import pytest

from core.events import Event
from store import make_store
from store.memory import MemoryStore
from store.readonly import ReadOnlyStoreView


def _event(seq: int, case_id: str = "3:mother-01", type_: str = "ENROLLED", key: str = "k1") -> Event:
    return Event(
        seq=seq,
        case_id=case_id,
        at="2026-08-24T00:00:00+00:00",
        type=type_,
        payload={"seq_marker": seq},
        tag="Simulated",
        idempotency_key=key,
    )


def test_append_and_events_roundtrip():
    store = MemoryStore()
    ok = store.append("3:mother-01", _event(0), "key-0")
    assert ok is True
    events = store.events("3:mother-01")
    assert len(events) == 1
    assert events[0].type == "ENROLLED"


def test_append_returns_false_on_duplicate_idempotency_key():
    store = MemoryStore()
    assert store.append("3:mother-01", _event(0), "same-key") is True
    assert store.append("3:mother-01", _event(1), "same-key") is False
    assert len(store.events("3:mother-01")) == 1


def test_events_are_returned_ordered_by_seq():
    store = MemoryStore()
    store.append("3:mother-01", _event(2), "k2")
    store.append("3:mother-01", _event(0), "k0")
    store.append("3:mother-01", _event(1), "k1")
    seqs = [e.seq for e in store.events("3:mother-01")]
    assert seqs == [0, 1, 2]


def test_case_ids_filtered_by_namespace():
    store = MemoryStore()
    store.append("3:mother-01", _event(0), "k0")
    store.append("3:mother-02", _event(0), "k0b")
    store.append("4:mother-01", _event(0), "k0c")
    assert store.case_ids("3") == ["3:mother-01", "3:mother-02"]
    assert store.case_ids("4") == ["4:mother-01"]


def test_meta_get_set_roundtrip():
    store = MemoryStore()
    assert store.get_meta("clock") is None
    store.set_meta("clock", {"iso": "2026-08-24T00:00:00+00:00"})
    assert store.get_meta("clock") == {"iso": "2026-08-24T00:00:00+00:00"}


def test_cache_get_put_roundtrip():
    store = MemoryStore()
    assert store.cache_get("hash-1") is None
    store.cache_put("hash-1", {"text": "hello"})
    assert store.cache_get("hash-1") == {"text": "hello"}


def test_reset_clears_only_the_given_namespace():
    store = MemoryStore()
    store.append("3:mother-01", _event(0), "k0")
    store.append("4:mother-01", _event(0), "k0b")
    store.reset("3")
    assert store.case_ids("3") == []
    assert store.case_ids("4") == ["4:mother-01"]


def test_json_persistence_reloads_state(tmp_path):
    path = tmp_path / "store.json"
    store = MemoryStore(path)
    store.append("3:mother-01", _event(0), "k0")
    store.set_meta("clock", {"iso": "now"})

    reloaded = MemoryStore(path)
    assert [e.seq for e in reloaded.events("3:mother-01")] == [0]
    assert reloaded.get_meta("clock") == {"iso": "now"}
    # a retried append with the same key stays a no-op after reload too
    assert reloaded.append("3:mother-01", _event(0), "k0") is False


def test_readonly_view_has_no_append():
    store = MemoryStore()
    view = ReadOnlyStoreView(store)
    assert not hasattr(view, "append")
    assert not hasattr(view, "set_meta")
    assert not hasattr(view, "cache_put")
    assert not hasattr(view, "reset")


def test_readonly_view_proxies_events_and_case_ids():
    store = MemoryStore()
    store.append("3:mother-01", _event(0), "k0")
    view = ReadOnlyStoreView(store)
    assert [e.seq for e in view.events("3:mother-01")] == [0]
    assert view.case_ids("3") == ["3:mother-01"]


def test_make_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("STORE", raising=False)
    monkeypatch.delenv("STORE_PATH", raising=False)
    store = make_store()
    assert isinstance(store, MemoryStore)


def test_make_store_firestore_without_gcp_project_raises_clear_error(monkeypatch):
    monkeypatch.setenv("STORE", "firestore")
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with pytest.raises(RuntimeError, match="GCP_PROJECT"):
        make_store()


def _has_application_default_credentials() -> bool:
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    return (Path.home() / ".config" / "gcloud" / "application_default_credentials.json").exists()


_FIRESTORE_MODULE_EXISTS = (Path(__file__).resolve().parent.parent / "store" / "firestore.py").exists()


@pytest.mark.skipif(
    not _FIRESTORE_MODULE_EXISTS or not _has_application_default_credentials(),
    reason="store/firestore.py lands in T-15, and/or no Application Default Credentials available",
)
def test_firestore_roundtrip():  # pragma: no cover - needs ADC + GCP_PROJECT
    """Runs against real Firestore. Uses a throwaway namespace and cleans up:
    the original version wrote to namespace "3", which is the demo namespace a
    live deploy actually serves, so it both polluted production data and failed
    on a second run (append -> AlreadyExists -> False)."""
    import uuid

    from store.firestore import FirestoreStore

    store = FirestoreStore(project=os.environ["GCP_PROJECT"])
    ns = f"test-{uuid.uuid4().hex[:12]}"
    case = f"{ns}:mother-01"
    try:
        assert store.append(case, _event(0), "k0") is True
        assert len(store.events(case)) == 1
        # a retried append with the same idempotency key is a provable no-op
        assert store.append(case, _event(0), "k0") is False
        assert len(store.events(case)) == 1
        # case_ids must find a case whose parent document was never written
        # (the phantom-ancestor bug that made a live deploy show an empty
        # worklist while every event sat in Firestore intact)
        assert case in store.case_ids(ns)
    finally:
        store.reset(ns)
    assert store.case_ids(ns) == []
    assert store.events(case) == []
