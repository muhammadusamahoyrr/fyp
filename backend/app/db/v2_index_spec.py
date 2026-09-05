"""THE index specification for DOCUMENTS_V2. One structure, three consumers.

WHY THIS FILE EXISTS

The same indexes were declared in three places: production created them in
`indexes.py`, readiness checked a separate tuple beside it, and the test suite
built its own list in `conftest.py`. Three declarations of one fact drift, and
they had already drifted in a way that mattered:

  * `review_events(document_id, event_seq)` is created in production WITHOUT an
    explicit name, so Mongo calls it `document_id_1_event_seq_1`. The test
    fixture created it as `uniq_review_event_document_seq` — a name production
    never uses. It appeared to work only because Mongo refused the duplicate and
    the fixture swallowed "already exists".
  * readiness checked `unique` and nothing else, so the notifications index
    would have passed validation without `sparse` — which is the option that
    stops every legacy notification with no `logical_event_id` from colliding
    with every other one.

So the shape of each index, the options that make it mean something, and whether
it is a correctness guarantee or a query path are stated once, here. Production
creation, readiness validation and test setup all read this and cannot disagree.

CORRECTNESS vs QUERY

A CORRECTNESS index is the enforcement mechanism for a guarantee the application
code cannot provide on its own — the code races, and the index resolves the
race. Losing one does not slow the system down, it makes it wrong.

A QUERY index is what keeps a bounded, paginated read bounded. Losing one turns
a lawyer's inbox into a collection scan, which is an outage at the size where
pagination was the point.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from pymongo import ASCENDING, DESCENDING, IndexModel

CORRECTNESS = "correctness"
QUERY = "query"


@dataclass(frozen=True)
class IndexSpec:
    """One index, completely described.

    `name` is the name PRODUCTION USES, which for one entry is the name Mongo
    generates rather than one we chose — see `review_events` below. Getting that
    wrong does not fail loudly: Mongo refuses to create a second index with the
    same keys under a different name, so the mistake shows up as an index that
    silently was not created.
    """

    collection: str
    name: str
    keys: tuple[tuple[str, int], ...]
    kind: str
    unique: bool = False
    sparse: bool = False
    partial_filter: Mapping[str, Any] | None = None
    why: str = ""

    def options(self) -> dict:
        """The options that must hold for this index to mean what it claims.

        Only the ones that CHANGE BEHAVIOUR — and ALL of those, in both
        directions. An index carrying an extra `background` or a `v` is still
        the index we asked for. One that gained `sparse`, `hidden` or a
        case-insensitive collation is a different index that behaves
        differently, and every one of those differences is silent:

          * SPARSE where none was asked for silently drops documents missing the
            field from the index, so a unique constraint stops applying to them
            and a query that should scan the index falls back to a collection
            scan.
          * HIDDEN keeps the index maintained and unique — so it still costs
            writes and still rejects duplicates — while making it invisible to
            the planner. Every query it was built for silently becomes a scan.
          * COLLATION changes what "equal" means. A case-insensitive index over
            `idempotency_key` would reject two distinct keys as duplicates.
        """
        return {
            "unique": self.unique,
            "sparse": self.sparse,
            "hidden": False,
            "collation": None,
            "partial_filter": dict(self.partial_filter) if self.partial_filter else None,
        }

    def model(self) -> IndexModel:
        kwargs: dict = {"name": self.name}
        if self.unique:
            kwargs["unique"] = True
        if self.sparse:
            kwargs["sparse"] = True
        if self.partial_filter:
            kwargs["partialFilterExpression"] = dict(self.partial_filter)
        return IndexModel(list(self.keys), **kwargs)


def observed_options(spec: Mapping[str, Any]) -> dict:
    """The same three options, read out of Mongo's `index_information()` entry.

    Normalised so a missing key and an explicit False compare equal — Mongo
    omits `unique` entirely rather than storing False, and comparing raw dicts
    would report every ordinary index as "not unique but should not be".
    """
    partial = spec.get("partialFilterExpression")
    collation = spec.get("collation")
    if collation:
        # `locale: "simple"` IS the absence of a collation — Mongo reports it
        # that way for an index created without one on some versions. Anything
        # else changes comparison semantics.
        collation = None if collation.get("locale") == "simple" else dict(collation)
    return {
        "unique": bool(spec.get("unique", False)),
        "sparse": bool(spec.get("sparse", False)),
        "hidden": bool(spec.get("hidden", False)),
        "collation": collation,
        "partial_filter": dict(partial) if partial else None,
    }


def observed_keys(spec: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    return tuple((field_name, int(direction))
                 for field_name, direction in spec.get("key", []))


# ── THE MANIFEST ─────────────────────────────────────────────────────────────

V2_INDEX_REQUIREMENTS: tuple[IndexSpec, ...] = (
    # 1 — one version number per document, whoever asks for it.
    IndexSpec(
        collection="document_revisions",
        name="uniq_revision_document_version",
        keys=(("document_id", ASCENDING), ("version", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why="Two concurrent generations cannot reserve the same version.",
    ),
    # 2 — one revision per intent.
    IndexSpec(
        collection="document_revisions",
        name="uniq_revision_document_idempotency",
        keys=(("document_id", ASCENDING), ("idempotency_key", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why=("A retry of one intent yields ONE revision. The service genuinely "
             "races — every attempt reads 'no revision yet' — and this index is "
             "what makes all but one insert fail so the losers read the winner."),
    ),
    # 3 — one ledger row per document event.
    IndexSpec(
        collection="review_events",
        # MONGO'S GENERATED NAME, not one we chose. `_review_events_indexes`
        # creates this IndexModel without `name=`, so renaming it here would not
        # rename the index — it would make production try to create a SECOND
        # index over the same keys, which Mongo refuses outright.
        name="document_id_1_event_seq_1",
        keys=(("document_id", ASCENDING), ("event_seq", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        why="The ordered history of one document cannot contain a duplicate seq.",
    ),
    # 4 — at-least-once delivery becomes exactly-once.
    IndexSpec(
        collection="notifications",
        name="uniq_notification_logical_event",
        keys=(("logical_event_id", ASCENDING),),
        kind=CORRECTNESS, unique=True, sparse=True,
        why=("SPARSE IS NOT OPTIONAL. Legacy notifications carry no "
             "logical_event_id, and a plain unique index treats every missing "
             "field as one shared null — so the second legacy notification ever "
             "written would collide with the first. Sparse omits them from the "
             "index entirely, which is what lets the guarantee apply to V2 rows "
             "without breaking every row that predates it."),
    ),
    # 5 — the pending half of a lawyer's inbox.
    IndexSpec(
        collection="documents",
        name="v2_queue_pending",
        keys=(("submitted_to", ASCENDING), ("review_status", ASCENDING),
              ("_id", ASCENDING)),
        kind=QUERY,
        why=("Equality on the first two, then the SORT KEY. Its predecessor "
             "`v2_review_queue` put `submitted_at` between them, for a "
             "newest-first ordering the queue does not ask for — so the index "
             "could satisfy the filter but not the sort, and every page paid a "
             "blocking SORT over the lawyer's whole inbox to return 25 rows. "
             "Measured before: 30 documents examined for 26 returned, with a "
             "SORT stage; after: 26 examined for 26, no SORT."),
    ),
    # 6 — the decided half.
    IndexSpec(
        collection="documents",
        name="v2_queue_cycles",
        keys=(("review_cycles.lawyer_id", ASCENDING),
              ("review_cycles.action", ASCENDING), ("_id", ASCENDING)),
        kind=QUERY,
        why=("Compound multikey over ONE array — the 'parallel arrays' "
             "restriction is about two different arrays — with `_id` appended "
             "so the index also provides the sort. Measured: a multikey index "
             "DOES serve an `_id` sort when the array fields are equality "
             "bounds. Its predecessor `v2_review_cycles` omitted `_id`, so the "
             "Returned tab examined all 60 matching documents on every page, "
             "including page two."),
    ),
    # 6b — the decided half with NO action fixed: the All tab's second stream.
    IndexSpec(
        collection="documents",
        name="v2_queue_cycles_any",
        keys=(("review_cycles.lawyer_id", ASCENDING), ("_id", ASCENDING)),
        kind=QUERY,
        why=("The All tab asks 'anything I decided', with no action to pin. "
             "`v2_queue_cycles` cannot serve that sort: with `action` "
             "unconstrained it is a range rather than an equality bound, and a "
             "sort key after a range is not deliverable by the index. Measured "
             "without this: the All tab's decided stream sorted 116 documents "
             "in memory to return 52. With it, both streams are bounded scans."),
    ),
    # 7 — everything a caller owns.
    IndexSpec(
        collection="documents",
        name="v2_owner_documents",
        keys=(("client_id", ASCENDING), ("schema_version", ASCENDING),
              ("created_at", DESCENDING), ("_id", ASCENDING)),
        kind=QUERY,
        why=("/documents/v2/mine, for clients and lawyers alike. The last two "
             "keys are the SORT, and they follow the equality prefix so the "
             "index delivers the order rather than the server sorting a "
             "result set in memory. Previously the endpoint sorted by `_id` "
             "alone while documenting 'newest first' — ids are random, so the "
             "index matched the query and the query was not the one the "
             "caller had been promised."),
    ),
)


def requirements_for(collection: str) -> tuple[IndexSpec, ...]:
    return tuple(s for s in V2_INDEX_REQUIREMENTS if s.collection == collection)


def correctness_requirements() -> tuple[IndexSpec, ...]:
    return tuple(s for s in V2_INDEX_REQUIREMENTS if s.kind == CORRECTNESS)


def query_requirements() -> tuple[IndexSpec, ...]:
    return tuple(s for s in V2_INDEX_REQUIREMENTS if s.kind == QUERY)


# ── validation ───────────────────────────────────────────────────────────────

CODE_UNREADABLE = "unreadable"
CODE_MISSING = "missing"
CODE_WRONG_KEYS = "wrong_keys"
CODE_NOT_UNIQUE = "not_unique"
CODE_NOT_SPARSE = "not_sparse"
CODE_WRONG_PARTIAL = "wrong_partial_filter"
CODE_UNEXPECTED_OPTION = "unexpected_option"
CODE_UNEXPECTED_SPARSE = "unexpected_sparse"
CODE_HIDDEN = "hidden"
CODE_UNEXPECTED_COLLATION = "unexpected_collation"


@dataclass(frozen=True)
class IndexProblem:
    """One index that is not what it must be.

    Carries a code so a caller can branch, and a message a human can act on.
    `__str__` is the message, so existing string-based reporting keeps working.
    """

    code: str
    collection: str
    name: str
    message: str
    kind: str = QUERY

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.collection}.{self.name}: {self.message}"


def _matches(spec: IndexSpec, observed: Mapping[str, Any]) -> bool:
    """Is this observed index EXACTLY the one required?

    Keys in order and every behaviour-changing option. Used for the
    another-name fallback, where a partial match must NOT be accepted: an index
    with the right keys and the wrong options is a different guarantee, and
    accepting it is how a non-sparse notifications index would slip through.
    """
    return (observed_keys(observed) == spec.keys
            and observed_options(observed) == spec.options())


def evaluate(spec: IndexSpec, info: Mapping[str, Mapping[str, Any]]) -> IndexProblem | None:
    """Check one requirement against a collection's `index_information()`."""
    present = info.get(spec.name)

    if present is None:
        # An operator may have created it by hand under another name. Accepted
        # ONLY on an exact match of keys and options — see `_matches`.
        if any(_matches(spec, other) for other in info.values()):
            return None
        return IndexProblem(
            CODE_MISSING, spec.collection, spec.name, kind=spec.kind,
            message=(f"missing — expected {_describe(spec)}"))

    keys = observed_keys(present)
    if keys != spec.keys:
        return IndexProblem(
            CODE_WRONG_KEYS, spec.collection, spec.name, kind=spec.kind,
            message=(f"has keys {list(keys)} but must have {list(spec.keys)} "
                     "— key ORDER is part of the index, not a detail"))

    options = observed_options(present)
    wanted = spec.options()

    if wanted["unique"] and not options["unique"]:
        return IndexProblem(
            CODE_NOT_UNIQUE, spec.collection, spec.name, kind=spec.kind,
            message="exists but is NOT unique — it enforces nothing")

    if wanted["sparse"] and not options["sparse"]:
        return IndexProblem(
            CODE_NOT_SPARSE, spec.collection, spec.name, kind=spec.kind,
            message=("exists but is NOT sparse — every document missing "
                     f"{spec.keys[0][0]} collides with every other one"))

    if options["partial_filter"] != wanted["partial_filter"]:
        return IndexProblem(
            CODE_WRONG_PARTIAL, spec.collection, spec.name, kind=spec.kind,
            message=(f"has partial filter {options['partial_filter']!r} but "
                     f"must have {wanted['partial_filter']!r} — a partial "
                     "index enforces its guarantee only over the rows it "
                     "covers"))

    if options["unique"] and not wanted["unique"]:
        return IndexProblem(
            CODE_UNEXPECTED_OPTION, spec.collection, spec.name, kind=spec.kind,
            message=("is unique but must not be — it will reject writes the "
                     "application considers valid"))

    if options["sparse"] and not wanted["sparse"]:
        return IndexProblem(
            CODE_UNEXPECTED_SPARSE, spec.collection, spec.name, kind=spec.kind,
            message=("is sparse but must not be — documents missing "
                     f"{spec.keys[0][0]} are absent from it, so any constraint "
                     "stops applying to them and queries fall back to a scan"))

    if options["hidden"]:
        return IndexProblem(
            CODE_HIDDEN, spec.collection, spec.name, kind=spec.kind,
            message=("is hidden — still maintained and still enforcing, but "
                     "invisible to the planner, so every query it exists for "
                     "silently becomes a collection scan"))

    if options["collation"] is not None:
        return IndexProblem(
            CODE_UNEXPECTED_COLLATION, spec.collection, spec.name,
            kind=spec.kind,
            message=(f"has collation {options['collation']!r} — it changes what "
                     "equality means, so the keys it treats as duplicates are "
                     "not the ones the application considers equal"))

    return None


def _describe(spec: IndexSpec) -> str:
    bits = [f"keys {list(spec.keys)}"]
    if spec.unique:
        bits.append("unique")
    if spec.sparse:
        bits.append("sparse")
    if spec.partial_filter:
        bits.append(f"partial {dict(spec.partial_filter)!r}")
    return ", ".join(bits)
