"""Pure/offline coverage for store/firestore.py that doesn't need ADC or a
real Firestore project — the network-touching path (append/events/etc. via
a real client) is exercised by tests/test_store.py::test_firestore_roundtrip,
which skips without Application Default Credentials (T-15's own accept
criterion covers that). This file only checks what can be checked without
ever calling `.client`.
"""
from __future__ import annotations

import pytest

from store.firestore import FirestoreStore, _split_namespace


def test_split_namespace_splits_on_first_colon():
    assert _split_namespace("3:mother-01") == ("3", "mother-01")
    assert _split_namespace("3:mother:with:colons") == ("3", "mother:with:colons")


def test_split_namespace_rejects_a_bare_key():
    with pytest.raises(ValueError, match="namespaced"):
        _split_namespace("mother-01")


def test_construction_is_lazy_and_touches_no_network():
    # Constructing a FirestoreStore must never attempt auth/network — only
    # touching .client (via append/events/etc.) does. If this constructor
    # tried to build a real google.cloud.firestore.Client it would either
    # raise (no ADC on this machine) or hang; neither happens here.
    store = FirestoreStore(project="not-a-real-project")
    assert store._client is None


def test_client_property_is_memoized(monkeypatch):
    store = FirestoreStore(project="not-a-real-project")
    sentinel = object()
    calls = []

    def fake_client_ctor(project):
        calls.append(project)
        return sentinel

    import google.cloud.firestore as firestore_module

    monkeypatch.setattr(firestore_module, "Client", fake_client_ctor)
    first = store.client
    second = store.client
    assert first is second is sentinel
    assert calls == ["not-a-real-project"]
