"""Every path that writes a judgment must record its jurisdiction.

WHY THIS FILE EXISTS
--------------------
`province` and `authority` are what the precedent-aware ranker reads. Omitting
them does not leave a judgment unranked — it ranks it as persuasive everywhere,
so a Lahore judgment that binds in Punjab quietly loses its binding weight.
Nothing raises, no response looks wrong, and the ordering is simply worse.

That failure has now happened twice, in two different layers of the same
feature:

  * citator_service._embed_and_upsert wrote Chroma metadata without the fields,
    so 200 judgments — every one fetched from the LHC site — landed with no
    jurisdiction at all: 3,230 chunks.
  * build_doc omitted them from the Mongo document. That one is subtler and
    survived the first fix: rebuild_judgments_vectors.py regenerates Chroma
    metadata FROM Mongo, so repairing only the Chroma write looks correct and
    then loses jurisdiction again on the next rebuild.

test_corpus_health.py::test_every_judgment_chunk_has_a_jurisdiction catches the
consequence, but only after a bad ingest has already run, and only against
whatever happens to be in the store. These tests catch the cause, offline, in
the code — including in a writer nobody has written yet.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

REQUIRED = {"province", "authority"}

# A Chroma metadata dict for a judgment chunk. Both keys, so that a bare
# `where={"judgment_id": jid}` filter is not mistaken for a metadata literal.
CHROMA_SHAPE = {"judgment_id", "court"}

# A judgment document headed for Mongo.
MONGO_SHAPE = {"_id", "court", "text"}

SCAN_DIRS = [BACKEND / "app", BACKEND / "scripts"]


def _is_projection(node: ast.Dict) -> bool:
    """True for a Mongo projection/filter such as {"_id": 1, "text": 1}.

    These share their key shape with the documents they select but are reads,
    not writes, so requiring jurisdiction of them is meaningless. A projection
    is all-int/bool values; a real document's values are expressions.
    """
    return bool(node.values) and all(
        isinstance(v, ast.Constant) and isinstance(v.value, (int, bool))
        for v in node.values
    )


def _dict_literals(path: Path):
    """Yield (lineno, {string keys}) for every dict literal that is written."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):  # not ours to police
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or _is_projection(node):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if keys:
            yield node.lineno, keys


def _sources():
    for root in SCAN_DIRS:
        for path in root.rglob("*.py"):
            if "venv" in path.parts or "__pycache__" in path.parts:
                continue
            yield path


# ── the contract, enforced structurally ──────────────────────────────────────

def test_every_chroma_metadata_literal_carries_jurisdiction():
    """Any dict written as judgment-chunk metadata must name both fields.

    This is the check that survives a new writer: add a fifth ingest path that
    upserts chunks and forgets province/authority, and this fails on the dict
    literal itself, before the path is ever run against a real collection.
    """
    offenders = [
        f"{p.relative_to(BACKEND)}:{line} missing {sorted(REQUIRED - keys)}"
        for p in _sources()
        for line, keys in _dict_literals(p)
        if CHROMA_SHAPE <= keys and not REQUIRED <= keys
    ]
    assert not offenders, (
        "judgment chunk metadata without jurisdiction:\n  " + "\n  ".join(offenders))


def test_every_judgment_document_literal_carries_jurisdiction():
    """The Mongo document must carry them too, not just the Chroma metadata.

    rebuild_judgments_vectors.py rebuilds chunk metadata out of these documents.
    A document without the fields yields chunks without them the next time the
    collection is regenerated, however correct the ingest-time write was.
    """
    offenders = [
        f"{p.relative_to(BACKEND)}:{line} missing {sorted(REQUIRED - keys)}"
        for p in _sources()
        for line, keys in _dict_literals(p)
        if MONGO_SHAPE <= keys and not REQUIRED <= keys
    ]
    assert not offenders, (
        "judgment documents without jurisdiction:\n  " + "\n  ".join(offenders))


# ── the contract, enforced behaviourally ─────────────────────────────────────

class _FakeEmbeddings:
    def embed_documents(self, docs):
        return [[0.0, 1.0] for _ in docs]


class _Recorder:
    """Stands in for a Chroma collection and keeps what was written."""

    def __init__(self):
        self.metadatas: list[dict] = []

    def upsert(self, ids, embeddings, documents, metadatas):
        self.metadatas.extend(metadatas)


def test_ingest_judgments_embed_writes_jurisdiction(monkeypatch):
    """The shared _embed — used by ingest_judgments and ingest_sc_parquet."""
    import app.ai.pipelines.retriever as retriever
    import app.db.chroma as chroma
    import ingest_judgments as ij

    recorder = _Recorder()
    monkeypatch.setattr(retriever, "_embeddings", lambda: _FakeEmbeddings())
    monkeypatch.setattr(chroma, "get_collection", lambda name: recorder)

    ij._embed("LHC:1", ["a", "b"], "LHC", "punjab", "binding_provincial",
              {"year": 2021, "judge": "", "title": ""})

    assert recorder.metadatas, "nothing was written"
    for meta in recorder.metadatas:
        assert meta["province"] == "punjab"
        assert meta["authority"] == "binding_provincial"


def test_citator_embed_writes_jurisdiction(monkeypatch):
    """The citator's own path — the one that omitted them for 200 judgments."""
    import app.ai.pipelines.retriever as retriever
    from app.services import citator_service as cs

    recorder = _Recorder()
    monkeypatch.setattr(retriever, "_embeddings", lambda: _FakeEmbeddings())
    monkeypatch.setattr(cs, "get_collection", lambda name: recorder)

    cs._embed_and_upsert("2026LHC1", ["a"], 2026, {"judge": "", "title": ""})

    assert recorder.metadatas, "nothing was written"
    for meta in recorder.metadatas:
        assert meta["province"] == cs.PROVINCE
        assert meta["authority"] == cs.AUTHORITY


def test_build_doc_persists_jurisdiction():
    """The Mongo half of the citator path."""
    from app.services import citator_service as cs

    doc = cs.build_doc("2026LHC1", "x" * 900)
    assert doc["province"] == cs.PROVINCE
    assert doc["authority"] == cs.AUTHORITY


def test_the_citator_constants_match_the_courts_table():
    """One court, two hard-coded copies of its jurisdiction.

    The ranker compares these values literally, so a spelling that drifts from
    the COURTS table reads as no match and reintroduces the same bug without
    either copy looking wrong on its own.
    """
    from app.services import citator_service as cs
    from ingest_judgments import COURTS

    assert (cs.COURT, cs.PROVINCE, cs.AUTHORITY) == COURTS["lahore high court"]


@pytest.mark.parametrize("code,expected", sorted(
    (code, (province, authority))
    for code, province, authority in
    __import__("ingest_judgments").COURTS.values()
))
def test_each_court_maps_to_one_jurisdiction(code, expected):
    """No court may carry two different jurisdictions across the table."""
    from ingest_judgments import COURTS

    seen = {(p, a) for c, p, a in COURTS.values() if c == code}
    assert seen == {expected}, f"{code} has conflicting jurisdictions: {seen}"
