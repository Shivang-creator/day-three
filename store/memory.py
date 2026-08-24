"""Dict-backed Store, with optional JSON-file persistence at STORE_PATH.

Case-id convention: a case_id is namespaced as "{namespace}:{rest}" (e.g.
"3:mother-07" for seed 3). case_ids(namespace) and reset(namespace) filter on
that prefix. This mirrors how store/firestore.py (T-15) segregates cases
under ns/{seed}/cases/{case_id} — the memory store just emulates the same
split in one flat dict, so callers write the same case_id shape regardless
of backend.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from core.events import Event


class MemoryStore:
    def __init__(self, path: str | Path | None = None):
        self._events: dict[str, list[Event]] = {}
        self._seen_keys: set[str] = set()
        self._meta: dict[str, dict] = {}
        self._cache: dict[str, dict] = {}
        self._path = Path(path) if path else None
        if self._path and self._path.exists():
            self._load()

    def append(self, case_id: str, event: Event, idempotency_key: str) -> bool:
        dedupe_key = f"{case_id}|{idempotency_key}"
        if dedupe_key in self._seen_keys:
            return False
        self._seen_keys.add(dedupe_key)
        self._events.setdefault(case_id, []).append(event)
        self._persist()
        return True

    def events(self, case_id: str) -> list[Event]:
        return sorted(self._events.get(case_id, []), key=lambda e: e.seq)

    def case_ids(self, namespace: str) -> list[str]:
        prefix = f"{namespace}:"
        return sorted(cid for cid in self._events if cid.startswith(prefix))

    def get_meta(self, key: str) -> dict | None:
        return self._meta.get(key)

    def set_meta(self, key: str, value: dict) -> None:
        self._meta[key] = value
        self._persist()

    def cache_get(self, key: str) -> dict | None:
        return self._cache.get(key)

    def cache_put(self, key: str, value: dict) -> None:
        self._cache[key] = value
        self._persist()

    def reset(self, namespace: str) -> None:
        prefix = f"{namespace}:"
        for cid in [c for c in self._events if c.startswith(prefix)]:
            del self._events[cid]
        self._seen_keys = {k for k in self._seen_keys if not k.startswith(prefix)}
        self._meta = {k: v for k, v in self._meta.items() if not k.startswith(prefix)}
        self._persist()

    # ------------------------------------------------------- persistence --

    def _persist(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "events": {
                cid: [dataclasses.asdict(e) for e in evs] for cid, evs in self._events.items()
            },
            "seen_keys": sorted(self._seen_keys),
            "meta": self._meta,
            "cache": self._cache,
        }
        self._path.write_text(json.dumps(payload, sort_keys=True))

    def _load(self) -> None:
        payload = json.loads(self._path.read_text())
        self._events = {
            cid: [Event(**e) for e in evs] for cid, evs in payload.get("events", {}).items()
        }
        self._seen_keys = set(payload.get("seen_keys", []))
        self._meta = payload.get("meta", {})
        self._cache = payload.get("cache", {})
