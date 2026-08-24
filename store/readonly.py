"""ReadOnlyStoreView — the only store object the ADK agent ever sees
(agent/tools.py, T-18). It exposes events() and case_ids() ONLY: no append,
no meta, no cache, no reset. This is a structural guarantee, not a
convention — a prompt-injected reply has no write method to call even if it
somehow talked the model into trying (PLAN §1.3).
"""
from __future__ import annotations

from core.events import Event


class ReadOnlyStoreView:
    def __init__(self, store):
        self._store = store

    def events(self, case_id: str) -> list[Event]:
        return self._store.events(case_id)

    def case_ids(self, namespace: str) -> list[str]:
        return self._store.case_ids(namespace)
