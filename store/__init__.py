"""make_store() selects the Store backend from the STORE env var.

STORE=memory (default): MemoryStore, optionally persisted at STORE_PATH.
STORE=firestore: FirestoreStore (store/firestore.py, lands in T-15). Requires
GCP_PROJECT — raises a clear RuntimeError naming the missing var rather than
letting an unconfigured google-cloud client fail with an opaque traceback.
"""
from __future__ import annotations

import os

from store.memory import MemoryStore


def make_store():
    backend = os.environ.get("STORE", "memory")
    if backend == "memory":
        return MemoryStore(os.environ.get("STORE_PATH"))
    if backend == "firestore":
        project = os.environ.get("GCP_PROJECT")
        if not project:
            raise RuntimeError("STORE=firestore requires GCP_PROJECT to be set")
        from store.firestore import FirestoreStore  # local import: keeps google-cloud out of memory-only runs

        return FirestoreStore(project=project)
    raise ValueError(f"unknown STORE backend: {backend!r}")
