"""Firestore-backed Store (PLAN §4.2, T-15). Selected via `STORE=firestore`
— `store/__init__.py::make_store()` already validates `GCP_PROJECT` is set
*before* ever importing this module, so a missing project raises a clear
`RuntimeError` rather than a traceback from an unconfigured google-cloud
client (T-15's own accept criterion).

Layout:
    ns/{namespace}/cases/{case_id_suffix}/events/{idempotency_key}
    ns/{namespace}/meta/{meta_key_suffix}
    meta_global/{key}          (a non-namespaced meta key — rare, but the
                                 Store protocol's get_meta/set_meta never
                                 require one)
    cache/{hash}                (shared across every namespace, by design —
                                 cache_key is content-addressed, not
                                 namespace-addressed, and MemoryStore.reset()
                                 leaves it alone too)

`case_id` (Store protocol) and any namespaced meta key are always given to
us as "{namespace}:{rest}" strings by callers (T-14's convention — the
memory store emulates the same split in one flat dict; this module is
where that split becomes two real path segments, matching PLAN's
`ns/{seed}/...` layout literally: namespace and case_id are already
separate segments there, so the Firestore document id under `cases/` is
just the `{rest}` suffix — case_ids() reconstructs the full
"{namespace}:{rest}" form on the way back out so this backend is
behaviourally interchangeable with MemoryStore).

Idempotency: every event is written with `.create()`, which raises
AlreadyExists on a retried write with the same doc id — caught here and
turned into `append() -> False`, exactly mirroring MemoryStore's semantics
(PLAN §4.2: a retried append is a provable no-op, on either backend).

The `google.cloud.firestore` client is constructed lazily (on first real
use, not at `FirestoreStore.__init__`), so simply selecting
`STORE=firestore` and building a store never itself attempts auth or a
network call — only calling one of its methods does.
"""
from __future__ import annotations

import dataclasses

from core.events import Event


def _split_namespace(key: str) -> tuple[str, str]:
    if ":" not in key:
        raise ValueError(f"expected a namespaced id of the form 'namespace:rest', got {key!r}")
    namespace, rest = key.split(":", 1)
    return namespace, rest


class FirestoreStore:
    def __init__(self, project: str):
        self._project = project
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import firestore  # imported lazily: a memory-only run never needs this importable

            self._client = firestore.Client(project=self._project)
        return self._client

    # ---------------------------------------------------------- events --

    def append(self, case_id: str, event: Event, idempotency_key: str) -> bool:
        from google.api_core import exceptions as gexc

        namespace, case_suffix = _split_namespace(case_id)
        doc_ref = (
            self.client.collection("ns")
            .document(namespace)
            .collection("cases")
            .document(case_suffix)
            .collection("events")
            .document(idempotency_key)
        )
        try:
            doc_ref.create(dataclasses.asdict(event))
            return True
        except gexc.AlreadyExists:
            return False

    def events(self, case_id: str) -> list[Event]:
        namespace, case_suffix = _split_namespace(case_id)
        docs = (
            self.client.collection("ns")
            .document(namespace)
            .collection("cases")
            .document(case_suffix)
            .collection("events")
            .stream()
        )
        found = [Event(**doc.to_dict()) for doc in docs]
        return sorted(found, key=lambda e: e.seq)

    def case_ids(self, namespace: str) -> list[str]:
        docs = self.client.collection("ns").document(namespace).collection("cases").stream()
        return sorted(f"{namespace}:{doc.id}" for doc in docs)

    # ------------------------------------------------------------ meta --

    def get_meta(self, key: str) -> dict | None:
        snap = self._meta_doc_ref(key).get()
        return snap.to_dict() if snap.exists else None

    def set_meta(self, key: str, value: dict) -> None:
        self._meta_doc_ref(key).set(value)

    def _meta_doc_ref(self, key: str):
        if ":" in key:
            namespace, rest = _split_namespace(key)
            return self.client.collection("ns").document(namespace).collection("meta").document(rest)
        return self.client.collection("meta_global").document(key)

    # ----------------------------------------------------------- cache --

    def cache_get(self, key: str) -> dict | None:
        snap = self.client.collection("cache").document(key).get()
        return snap.to_dict() if snap.exists else None

    def cache_put(self, key: str, value: dict) -> None:
        self.client.collection("cache").document(key).set(value)

    # ----------------------------------------------------------- reset --

    def reset(self, namespace: str) -> None:
        """Demo/test only. Wipes every case, its events, and every meta doc
        under this namespace. Cache entries are shared across namespaces
        (content-addressed, not namespace-addressed) and are deliberately
        left alone, mirroring MemoryStore.reset()'s own behaviour."""
        ns_ref = self.client.collection("ns").document(namespace)
        for case_doc in ns_ref.collection("cases").stream():
            for event_doc in case_doc.reference.collection("events").stream():
                event_doc.reference.delete()
            case_doc.reference.delete()
        for meta_doc in ns_ref.collection("meta").stream():
            meta_doc.reference.delete()
