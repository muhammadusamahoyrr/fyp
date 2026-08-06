"""Labeling pipeline — provenance records → labeled evaluation set.

The export shape is load-bearing: evaluate_retrieval.py reads these exact keys,
and a mismatch would not raise, it would silently score zero.
"""
import pytest

from app.services import labeling_service as ls


# ── In-memory doubles for the two Motor collections ───────────────────────────

class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a):
        return self

    def __aiter__(self):
        async def gen():
            for d in self._docs:
                yield d
        return gen()

    async def to_list(self, length=None):
        return list(self._docs)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match(self, doc, query):
        for key, cond in (query or {}).items():
            if key == "$or":
                if not any(self._match(doc, sub) for sub in cond):
                    return False
                continue
            # dotted path support, e.g. "arbitration.source"
            if "." in key:
                value = doc
                for part in key.split("."):
                    value = (value or {}).get(part) if isinstance(value, dict) else None
            else:
                value = doc.get(key)
            if isinstance(cond, dict):
                if "$in" in cond and value not in cond["$in"]:
                    return False
                if "$nin" in cond and value in cond["$nin"]:
                    return False
                if "$ne" in cond and value == cond["$ne"]:
                    return False
                if "$exists" in cond and (key in doc) != cond["$exists"]:
                    return False
            elif value != cond:
                return False
        return True

    def find(self, query=None, projection=None):
        return FakeCursor([d for d in self.docs if self._match(d, query)])

    async def find_one(self, query=None, projection=None):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def count_documents(self, query=None):
        return len([d for d in self.docs if self._match(d, query)])

    async def replace_one(self, query, doc, upsert=False):
        for i, existing in enumerate(self.docs):
            if self._match(existing, query):
                self.docs[i] = doc
                return
        if upsert:
            self.docs.append(doc)


def _prov(request_id, **over):
    base = {
        "request_id": request_id,
        "turn_type":  "answer",
        "session_id": "s1",
        "query":      "Can a tenant be evicted without notice?",
        "answer_preview": "Under the Punjab Rented Premises Act ...",
        "case_type":  "civil",
        "province":   "punjab",
        "statute_chunks": [
            {"chunk_id": "c1", "statute": "PRPA 2009", "section_number": "12"},
            {"chunk_id": "c2", "statute": "PRPA 2009", "section_number": "13"},
        ],
        "arbitration": {"output": "answer", "source": "llm", "confidence": 0.8},
        "signals": {"relevance_score": 0.72, "bm25_confidence": 0.5,
                    "signal_variance": 0.03},
        "created_at": request_id,
    }
    base.update(over)
    return base


@pytest.fixture
def store(monkeypatch):
    prov   = FakeCollection()
    labels = FakeCollection()
    monkeypatch.setattr(ls, "get_answer_provenance_col", lambda: prov)
    monkeypatch.setattr(ls, "get_retrieval_labels_col",  lambda: labels)
    return prov, labels


# ── saving ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_saving_a_label_derives_the_relevant_chunk_list(store):
    prov, labels = store
    prov.docs.append(_prov("r1"))

    doc = await ls.save_label("r1", {"c1": True, "c2": False},
                              ls.VERDICT_CORRECT, labeler="usama")

    assert doc["relevant_chunks"] == ["c1"]
    assert doc["answer_verdict"] == ls.VERDICT_CORRECT
    assert doc["case_type"] == "civil"      # denormalised from provenance
    assert len(labels.docs) == 1


@pytest.mark.asyncio
async def test_relabelling_replaces_rather_than_duplicates(store):
    prov, labels = store
    prov.docs.append(_prov("r1"))

    await ls.save_label("r1", {"c1": True},  ls.VERDICT_CORRECT)
    await ls.save_label("r1", {"c1": False}, ls.VERDICT_INCORRECT)

    assert len(labels.docs) == 1, "a corrected judgement must not accumulate"
    assert labels.docs[0]["answer_verdict"] == ls.VERDICT_INCORRECT
    assert labels.docs[0]["relevant_chunks"] == []


@pytest.mark.asyncio
async def test_an_unknown_verdict_is_rejected(store):
    prov, _ = store
    prov.docs.append(_prov("r1"))
    with pytest.raises(ls.LabelError):
        await ls.save_label("r1", {"c1": True}, "probably_fine")


@pytest.mark.asyncio
async def test_labelling_an_unknown_request_is_rejected(store):
    with pytest.raises(ls.LabelError):
        await ls.save_label("nope", {"c1": True}, ls.VERDICT_CORRECT)


# ── work selection (resumability) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_already_labeled_records_are_not_offered_again(store):
    prov, _ = store
    prov.docs.extend([_prov("r1"), _prov("r2"), _prov("r3")])

    await ls.save_label("r2", {"c1": True}, ls.VERDICT_CORRECT)
    remaining = await ls.unlabeled_records(limit=10)

    assert {r["request_id"] for r in remaining} == {"r1", "r3"}


# ── turn types (clarification / blocked are audited but not labelable) ────────

@pytest.mark.asyncio
async def test_clarification_and_blocked_turns_are_not_offered_for_labelling(store):
    """Asking a human 'was this answer correct?' about a clarifying QUESTION is
    meaningless, and it would dilute the verdict distribution."""
    prov, _ = store
    prov.docs.extend([
        _prov("r1", turn_type="answer"),
        _prov("r2", turn_type="clarification"),
        _prov("r3", turn_type="blocked"),
    ])

    offered = await ls.unlabeled_records(limit=10)
    assert {r["request_id"] for r in offered} == {"r1"}


@pytest.mark.asyncio
async def test_retrieval_faults_are_not_offered_for_labelling(store):
    """A refusal caused by a crashed retriever is not an abstention decision;
    labelling it would put a system outage into the risk-coverage curve."""
    prov, _ = store
    prov.docs.extend([
        _prov("r1"),
        _prov("r2", arbitration={"output": "refuse", "source": "error",
                                 "confidence": 0.0}),
    ])
    offered = await ls.unlabeled_records(limit=10)
    assert {r["request_id"] for r in offered} == {"r1"}


@pytest.mark.asyncio
async def test_a_genuine_no_evidence_refusal_is_still_labelable(store):
    """Only faults are excluded. An honest 'nothing relevant found' refusal is
    exactly the case the abstention benchmark needs."""
    prov, _ = store
    prov.docs.append(_prov("r1", arbitration={"output": "refuse", "source": "none",
                                              "confidence": 0.0}))
    offered = await ls.unlabeled_records(limit=10)
    assert [r["request_id"] for r in offered] == ["r1"]


@pytest.mark.asyncio
async def test_all_turn_types_can_be_inspected_on_request(store):
    prov, _ = store
    prov.docs.extend([
        _prov("r1", turn_type="answer"),
        _prov("r2", turn_type="clarification"),
    ])
    offered = await ls.unlabeled_records(limit=10, include_all_turns=True)
    assert {r["request_id"] for r in offered} == {"r1", "r2"}


@pytest.mark.asyncio
async def test_records_predating_turn_type_still_count_as_answers(store):
    """Back-compat: rows written before the field existed were all answer turns,
    so a missing field must not silently drop them from the pool."""
    prov, _ = store
    legacy = _prov("r1")
    legacy.pop("turn_type", None)
    prov.docs.append(legacy)

    offered = await ls.unlabeled_records(limit=10)
    assert [r["request_id"] for r in offered] == ["r1"]


@pytest.mark.asyncio
async def test_progress_is_measured_against_labelable_turns_only(store):
    """Counting clarification/blocked turns in the denominator would report work
    remaining that can never be done."""
    prov, _ = store
    prov.docs.extend([
        _prov("r1", turn_type="answer"),
        _prov("r2", turn_type="answer"),
        _prov("r3", turn_type="clarification"),
        _prov("r4", turn_type="blocked"),
    ])
    await ls.save_label("r1", {"c1": True}, ls.VERDICT_CORRECT)

    s = await ls.stats()
    assert s["provenance_records"] == 4
    assert s["labelable"] == 2
    assert s["remaining"] == 1
    assert s["coverage"] == 0.5
    assert s["by_turn_type"] == {"answer": 2, "clarification": 1, "blocked": 1}


@pytest.mark.asyncio
async def test_pooling_depth_is_recorded_with_the_label(store):
    """Chunks below the depth are UNJUDGED, not known-irrelevant. Without this
    number, nDCG@10 from depth-5 labels would silently score five unjudged
    ranks as irrelevant."""
    prov, labels = store
    prov.docs.append(_prov("r1"))

    await ls.save_label("r1", {"c1": True, "c2": False},
                        ls.VERDICT_CORRECT, labeled_depth=5)
    assert labels.docs[0]["labeled_depth"] == 5


@pytest.mark.asyncio
async def test_depth_defaults_to_the_number_actually_judged(store):
    prov, labels = store
    prov.docs.append(_prov("r1"))

    await ls.save_label("r1", {"c1": True, "c2": False}, ls.VERDICT_CORRECT)
    assert labels.docs[0]["labeled_depth"] == 2


@pytest.mark.asyncio
async def test_stats_expose_the_shallowest_pool(store):
    """Metrics are only trustworthy up to the SHALLOWEST depth in the set."""
    prov, _ = store
    prov.docs.extend([_prov("r1"), _prov("r2")])

    await ls.save_label("r1", {"c1": True},  ls.VERDICT_CORRECT, labeled_depth=5)
    await ls.save_label("r2", {"c1": False}, ls.VERDICT_CORRECT, labeled_depth=3)

    s = await ls.stats()
    assert s["min_labeled_depth"] == 3
    assert s["max_labeled_depth"] == 5


@pytest.mark.asyncio
async def test_stats_report_progress_and_verdict_breakdown(store):
    prov, _ = store
    prov.docs.extend([_prov("r1"), _prov("r2"), _prov("r3"), _prov("r4")])

    await ls.save_label("r1", {"c1": True},  ls.VERDICT_CORRECT)
    await ls.save_label("r2", {"c1": False}, ls.VERDICT_CORRECT_REFUSAL)

    s = await ls.stats()
    assert s["provenance_records"] == 4
    assert s["labeled"]   == 2
    assert s["remaining"] == 2
    assert s["coverage"]  == 0.5
    assert s["by_verdict"][ls.VERDICT_CORRECT] == 1
    assert s["by_verdict"][ls.VERDICT_CORRECT_REFUSAL] == 1


# ── retrieval export ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_matches_the_keys_evaluate_retrieval_reads(store):
    """A key mismatch here would not raise — it would silently score zero."""
    prov, _ = store
    prov.docs.append(_prov("r1"))
    await ls.save_label("r1", {"c1": True, "c2": True}, ls.VERDICT_CORRECT)

    answerable, _ = await ls.export_retrieval_dataset()

    assert set(answerable[0]) == {
        "question", "answer", "case_type", "province", "relevant_chunks"
    }
    assert answerable[0]["relevant_chunks"] == ["c1", "c2"]
    assert answerable[0]["case_type"] == "civil"
    assert answerable[0]["province"]  == "punjab"


@pytest.mark.asyncio
async def test_records_with_no_relevant_chunk_become_the_abstention_split(store):
    """These are the queries where refusing is correct — the abstention paper
    needs them more than another easy positive, so they must not be dropped."""
    prov, _ = store
    prov.docs.extend([_prov("r1"), _prov("r2")])

    await ls.save_label("r1", {"c1": True,  "c2": False}, ls.VERDICT_CORRECT)
    await ls.save_label("r2", {"c1": False, "c2": False}, ls.VERDICT_CORRECT_REFUSAL)

    answerable, unanswerable = await ls.export_retrieval_dataset()

    assert [i["relevant_chunks"] for i in answerable]   == [["c1"]]
    assert [i["relevant_chunks"] for i in unanswerable] == [[]]


@pytest.mark.asyncio
async def test_unlabeled_records_are_excluded_from_the_export(store):
    prov, _ = store
    prov.docs.extend([_prov("r1"), _prov("r2")])
    await ls.save_label("r1", {"c1": True}, ls.VERDICT_CORRECT)

    answerable, unanswerable = await ls.export_retrieval_dataset()
    assert len(answerable) + len(unanswerable) == 1


@pytest.mark.asyncio
async def test_exporting_with_no_labels_is_empty_not_an_error(store):
    assert await ls.export_retrieval_dataset() == ([], [])
    assert await ls.export_calibration_pairs() == []


# ── calibration export ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calibration_pairs_carry_the_raw_score_and_the_outcome(store):
    """Platt/isotonic fit P(correct | raw score) — both halves must be present."""
    prov, _ = store
    prov.docs.append(_prov("r1"))
    await ls.save_label("r1", {"c1": True}, ls.VERDICT_CORRECT)

    pair = (await ls.export_calibration_pairs())[0]
    assert pair["relevance_score"] == 0.72
    assert pair["correct"]  is True
    assert pair["answered"] is True


@pytest.mark.asyncio
async def test_a_correct_refusal_counts_as_a_good_outcome_but_not_an_answer(store):
    """The distinction risk-coverage curves are built on: abstaining correctly is
    a success, but it is not an answer and must not inflate answer accuracy."""
    prov, _ = store
    prov.docs.append(_prov("r1", arbitration={"output": "refuse", "source": "none",
                                              "confidence": 0.0}))
    await ls.save_label("r1", {"c1": False}, ls.VERDICT_CORRECT_REFUSAL)

    pair = (await ls.export_calibration_pairs())[0]
    assert pair["correct"]  is True
    assert pair["answered"] is False
    assert pair["arbitration"] == "refuse"


@pytest.mark.asyncio
async def test_a_wrong_refusal_is_a_bad_outcome(store):
    prov, _ = store
    prov.docs.append(_prov("r1"))
    await ls.save_label("r1", {"c1": True}, ls.VERDICT_WRONG_REFUSAL)

    pair = (await ls.export_calibration_pairs())[0]
    assert pair["correct"]  is False
    assert pair["answered"] is False
