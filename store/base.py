"""The Store protocol (PLAN §4.2). Every implementation (MemoryStore today,
FirestoreStore in T-15) satisfies this shape; app/orchestrator.py is the only
caller of .append() outside tests (enforced by tests/test_boundary.py).
"""
from __future__ import annotations

from typing import Protocol

from core.events import Event


class Store(Protocol):
    def append(self, case_id: str, event: Event, idempotency_key: str) -> bool:
        """Append one event. Returns False (and writes nothing) if
        idempotency_key was already applied for this case_id."""
        ...

    def events(self, case_id: str) -> list[Event]:
        """All events for a case, ordered by seq."""
        ...

    def case_ids(self, namespace: str) -> list[str]:
        """Every case_id enrolled under this namespace (namespace = seed)."""
        ...

    def get_meta(self, key: str) -> dict | None: ...

    def set_meta(self, key: str, value: dict) -> None: ...

    def cache_get(self, key: str) -> dict | None: ...

    def cache_put(self, key: str, value: dict) -> None: ...

    def reset(self, namespace: str) -> None:
        """Wipe every case, key, and cache entry under this namespace. Demo /
        test use only."""
        ...
