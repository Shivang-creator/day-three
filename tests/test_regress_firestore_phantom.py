"""Regression: FirestoreStore.case_ids() must find cases whose parent document
was never materialised.

`append()` writes ns/{ns}/cases/{suffix}/events/{key} and never creates the
`cases/{suffix}` document itself, so that parent is a Firestore "phantom"
ancestor. `collection.stream()` skips phantoms; `collection.list_documents()`
includes them. Using stream() made a live Cloud Run deploy enroll 38 mothers
successfully and then report an empty worklist (26 Aug 2026). MemoryStore keeps
one flat dict, so only the Firestore backend could ever show this.

This test asserts the source uses list_documents() for case discovery and
deletion, which is checkable without credentials; the live behaviour itself is
covered by tests/test_store.py's roundtrip when ADC is present.
"""
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "store" / "firestore.py"


def _body(fn: str) -> str:
    text = SRC.read_text()
    start = text.index(f"def {fn}(")
    nxt = text.find("\n    def ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_case_ids_uses_list_documents_not_stream():
    body = _body("case_ids")
    assert "list_documents()" in body
    assert ".stream()" not in body, "stream() skips phantom case parents"


def test_reset_uses_list_documents_for_cases():
    body = _body("reset")
    assert 'collection("cases").list_documents()' in body
    assert 'collection("cases").stream()' not in body
