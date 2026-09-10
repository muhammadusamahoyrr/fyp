"""
Lawyer profile embedding pipeline.

Inspired by:
- EF_in_Legal_CQA (ECIR 2022): expert score = aggregated past work, not just bio
- FreeLawProject/Inception: structured profile text with sentence-aware chunking
"""
import asyncio
import hashlib
import logging
import re
from typing import Sequence

from app.ai.pipelines.retriever import _embeddings
from app.db.chroma import get_chroma

logger = logging.getLogger(__name__)

LAWYERS_COLLECTION = "lawyers_collection"

# ── Similarity calibration ───────────────────────────────────────────────────
# Raw cosine similarity from multilingual-e5-base does not start at zero. Every
# pair of legal-ish sentences sits high, so the raw number is dominated by a
# near-constant offset and only the last few hundredths carry signal.
#
# Measured 2026-09-01 against this collection, 20 candidates per query:
#
#   off-topic queries (sourdough, marathons, photosynthesis, gibberish, …)
#       n=120   min 0.7200   p50 0.7476   p95 0.7690   max 0.7837
#   on-topic queries (bail, khula, ejectment, Article 199, 489-F, inheritance)
#       n=120   min 0.7481   p50 0.7802   p95 0.8198   max 0.8506
#
# So a question about baking bread scored 0.72-0.78 against every lawyer on the
# platform, and the reason thresholds below (0.60 / 0.35) could never fire:
# everything read as "strong profile match", and the UI rendered that raw
# number as "72% case compatibility".
#
# FLOOR is the off-topic p95 — above the noise, so an irrelevant query lands at
# or near zero. CEILING is just above the on-topic p99, so a genuine best match
# approaches 1.0 without saturating. The transform is monotonic, so retrieval
# ORDER is untouched: it was already good (the correct specialism placed in the
# top 5 on 17 of 20 province x case-type probes, against ~7 for random).
#
# These are properties of THIS model and THIS corpus. Re-derive them if either
# changes: run off-topic and on-topic queries through query_similar_lawyers,
# read `raw_similarity`, and take the off-topic p95 and on-topic p99.
_SIM_FLOOR = 0.77
_SIM_CEILING = 0.86

# ── Provenance of the two constants above ────────────────────────────────────
#
# They are not tunable knobs; they are measurements, and a measurement is only
# valid for what it was measured on. Nothing in the running system can notice
# that they have stopped describing reality — a swapped embedding model or a
# re-ingested corpus moves the whole similarity distribution and these numbers
# keep quietly rescaling it wrongly, which is silent because the output is still
# a plausible 0..1 figure.
#
# So the inputs are recorded here and asserted by `tests/test_lawyer_calibration_guard.py`.
# That test is the alarm: change the model and it fails, telling you to re-derive
# rather than letting the matcher drift.
#
# Two things now depend on this calibration, not one:
#   * the 0.50 semantic weight in `_score_lawyer`
#   * `_MATCH_SEMANTIC_FLOOR` in lawyer_service, which decides whether a lawyer
#     may be called a match at all
# Re-deriving means revisiting both.
_CALIBRATED_FOR_MODEL = "intfloat/multilingual-e5-base"
_CALIBRATED_ON = "2026-09-01"
# Raw cosine extremes actually observed, 120 samples each. `calibrate_similarity`
# maps OFFTOPIC_MAX to ~0.15 and ONTOPIC_MAX to ~1.0; the qualification floor
# must stay clear of the first.
_MEASURED_OFFTOPIC_MAX_RAW = 0.7837
_MEASURED_ONTOPIC_MAX_RAW = 0.8506


def calibrate_similarity(raw: float) -> float:
    """Map raw cosine similarity onto a usable 0..1 scale.

    Below the noise floor is 0.0 — "no measured relevance" — not a small
    positive number that still buys half the semantic weight.
    """
    if _SIM_CEILING <= _SIM_FLOOR:  # misconfigured; fail open rather than divide by zero
        return max(0.0, min(1.0, float(raw)))
    scaled = (float(raw) - _SIM_FLOOR) / (_SIM_CEILING - _SIM_FLOOR)
    return round(max(0.0, min(1.0, scaled)), 4)

# ── Case → domain vocabulary ─────────────────────────────────────────────────
#
# A lawyer's profile text used to embed the client's own case descriptions
# verbatim ("Past cases handled: " + 150 characters of each). Those are clients
# writing about their legal problems — often the most sensitive thing they will
# ever type into this system — and Chroma stores the profile text in PLAINTEXT
# in the `documents` field beside the vector. So a client's account of their
# divorce, their criminal charge or their debt became part of a different
# person's searchable profile, readable by anyone with the database file, with
# no consent and no way to withdraw it.
#
# The signal that motivated it is real and worth keeping: EF_in_Legal_CQA's
# finding that an expert is described by their past work, not only their bio.
# The mistake was the mechanism, not the goal.
#
# So the case is read for VOCABULARY and never for prose. Every token that can
# reach a profile is either a constant from the allowlists below or a section
# number matched by a digit-bounded pattern anchored to a known statute. There
# is no path by which arbitrary case text can be emitted — that is a property of
# construction, not of a redaction pass. Blacklisting names, CNICs and phone
# numbers would have been the obvious approach and would leak forever; a
# whitelist cannot.
#
# What is lost: the specific facts of a matter. What is kept: that this lawyer
# has worked on bail, on khula, on ejectment, under PPC 380. That is what a
# client's query needs to rank against, and it is exactly what the design note
# meant by "assault, criminal, FIR, PPC naturally embedded".

_DOMAIN_TERMS: tuple[str, ...] = (
    # criminal
    "fir", "bail", "pre-arrest bail", "remand", "acquittal", "quashment",
    "prosecution", "narcotics", "qatl", "hurt", "theft", "robbery", "dacoity",
    "forgery", "cheque dishonour", "cybercrime", "defamation",
    # civil
    "property", "possession", "ejectment", "rent", "tenancy", "contract",
    "specific performance", "injunction", "partition", "declaration",
    "damages", "mutation", "easement", "pre-emption",
    # family
    "divorce", "khula", "talaq", "custody", "guardianship", "maintenance",
    "dower", "haq mehr", "nikah", "inheritance", "succession", "dowry",
    # constitutional / public
    "writ", "fundamental rights", "mandamus", "certiorari", "habeas corpus",
    "quo warranto", "service tribunal", "judicial review",
    # procedure and forums that cut across all of the above
    "appeal", "revision", "stay", "execution", "arbitration", "labour",
    "banking", "taxation", "customs", "rent tribunal",
)

# alias (matched case-insensitively) → the canonical token that gets emitted
_STATUTE_ALIASES: dict[str, str] = {
    "ppc": "PPC", "pakistan penal code": "PPC",
    "crpc": "CrPC", "cr.p.c": "CrPC", "code of criminal procedure": "CrPC",
    "cpc": "CPC", "code of civil procedure": "CPC",
    "peca": "PECA", "prevention of electronic crimes act": "PECA",
    "qanun-e-shahadat": "Qanun-e-Shahadat",
    "constitution": "Constitution",
    "family courts act": "Family Courts Act",
    "guardians and wards act": "Guardians and Wards Act",
    "transfer of property act": "Transfer of Property Act",
    "specific relief act": "Specific Relief Act",
    "contract act": "Contract Act",
    "registration act": "Registration Act",
    "limitation act": "Limitation Act",
    "anti-terrorism act": "Anti-Terrorism Act",
    "companies act": "Companies Act",
}

# A section number attached to one of the statutes above. The capture is
# `\d{1,4}` plus at most one letter, so nothing that is not a section number can
# be emitted through it. Anchored to the alias so a bare number in prose ("we
# paid 50000") cannot become a citation.
_SECTION_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in sorted(_STATUTE_ALIASES,
                                                   key=len, reverse=True)) + r")"
    r"[\s.,]*(?:u/s|under\s+)?[\s.,]*"
    r"(?:s|sec|section|art|article)?\.?\s*"
    r"(\d{1,4})\s*[-\s]?\s*([A-Za-z])?\b",
    re.IGNORECASE,
)


def _statute_references(text: str) -> list[str]:
    """Canonical "STATUTE section" strings found in `text`. Nothing else."""
    out: list[str] = []
    for alias, num, letter in _SECTION_RE.findall(text):
        canon = _STATUTE_ALIASES[alias.lower()]
        # "PPC 1860" is the statute's YEAR, not a section. The citation checker
        # makes the same exclusion for the same reason; inventing a section from
        # a year would put a fabricated authority into a lawyer's profile.
        if 1800 <= int(num) <= 2100:
            continue
        section = f"{num}-{letter.upper()}" if letter else num
        ref = f"{canon} {section}"
        if ref not in out:
            out.append(ref)
    return out


def case_domain_terms(cases: Sequence[dict]) -> list[str]:
    """Domain vocabulary for a lawyer's recent matters. Never their clients' words.

    Reads `case_type`, `title` and `description` but emits only:
      * the case type, which is a closed enum the client never writes freely;
      * terms from `_DOMAIN_TERMS`, matched as substrings;
      * statute references from `_statute_references`.

    Order is first-seen so the output is deterministic, which matters because
    the embedding is only stable if its input is.
    """
    terms: list[str] = []

    def add(t: str) -> None:
        if t not in terms:
            terms.append(t)

    for case in list(cases)[:5]:
        ct = (case.get("case_type") or "").strip().lower()
        if ct in {"criminal", "civil", "family", "constitutional"}:
            add(ct)
        # Read, never emitted. Only allowlist hits derived from it escape.
        haystack = " ".join([
            str(case.get("title") or ""),
            str(case.get("description") or ""),
        ]).lower()
        if not haystack.strip():
            continue
        for term in _DOMAIN_TERMS:
            if term in haystack:
                add(term)
        for ref in _statute_references(haystack):
            add(ref)

    return terms


def build_profile_text(lawyer: dict, recent_cases: Sequence[dict]) -> str:
    """
    Construct a rich text blob for embedding.

    EF_in_Legal_CQA insight: expert score = aggregated past work. A lawyer's
    past matters carry domain signal their own profile labels do not.

    That signal is taken as VOCABULARY, never as the client's prose — see
    `case_domain_terms`. Everything else here is the lawyer's own material:
    their specializations, their province, their experience and a bio they
    wrote for a profile meant to be read.
    """
    lp = lawyer.get("lawyer_profile") or {}
    specs = lp.get("specializations") or []
    parts: list[str] = []

    if specs:
        parts.append(
            f"Pakistani legal professional specializing in {', '.join(specs)}."
        )

    province = lawyer.get("province", "")
    if province:
        parts.append(f"Province: {province}.")

    exp = lp.get("experience_years", 0)
    if exp:
        parts.append(f"{exp} years of experience in Pakistani law.")

    bio = (lp.get("bio") or "").strip()
    if bio:
        parts.append(bio)

    # Past matters, as domain vocabulary only. This used to be
    #   "Past cases handled: " + 150 characters of each client's own words,
    # which put a client's account of their divorce or their criminal charge
    # into a different person's profile, in plaintext, in a shared index.
    terms = case_domain_terms(recent_cases)
    if terms:
        parts.append("Experienced in matters involving: " + ", ".join(terms) + ".")

    return " ".join(parts)


def _fingerprint(profile_text: str) -> str:
    """A short digest of the exact text a vector was built from.

    Deliberately fingerprints the BUILT TEXT rather than a chosen list of
    fields. Any list would have to be kept in step with `build_profile_text` by
    hand, and the moment the two disagree the fingerprint stops meaning "this
    vector is current" while still looking like it does. Fingerprinting the
    output makes that impossible: if the text that gets embedded changes for any
    reason — a new bio, an edited specialization, a newly assigned case
    contributing domain terms, or a change to how the text is assembled — the
    digest changes with it.

    Truncated to 16 hex characters. This guards against staleness, not against
    an adversary, and Chroma metadata is cheaper kept small.
    """
    return hashlib.sha256(profile_text.encode("utf-8")).hexdigest()[:16]


async def profile_fingerprint(lawyer_id: str) -> str | None:
    """What this lawyer's vector SHOULD be built from, right now.

    None when the lawyer is not indexable at all, which the caller must treat as
    "should not be in the store" rather than as "unchanged".
    """
    from app.repositories.case_repo import CaseRepository
    from app.repositories.user_repo import UserRepository

    lawyer = await UserRepository().find_by_id(lawyer_id)
    if not _indexable(lawyer):
        return None
    recent_cases = await CaseRepository().find_many(
        {"lawyer_id": lawyer_id}, sort=[("created_at", -1)], limit=5,
    )
    text = build_profile_text(lawyer, recent_cases)
    return _fingerprint(text) if text.strip() else None


def _get_collection():
    """Get or create the lawyers ChromaDB collection."""
    return get_chroma().get_or_create_collection(
        name=LAWYERS_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _indexable(lawyer: dict | None) -> bool:
    """Whether this lawyer may hold a vector at all.

    Everything in `lawyers_collection` is someone a client can be shown, so the
    membership rule is the same one the matcher applies. Factored out because it
    is now evaluated TWICE per embed — see the re-check in `embed_lawyer`.
    """
    if not lawyer or lawyer.get("role") != "lawyer":
        return False
    if not lawyer.get("is_active", True):
        return False
    return bool((lawyer.get("lawyer_profile") or {}).get("kyc_verified"))


async def embed_lawyer(lawyer_id: str) -> bool:
    """
    Embed one lawyer's profile and upsert into ChromaDB lawyers_collection.
    Called after KYC approval and after any profile update.

    Only KYC-verified, active lawyers are embedded. Anything in this collection
    is a candidate a client can be shown, so verification is enforced at the
    point of entry rather than left for the matcher to filter out later.
    """
    from app.repositories.case_repo import CaseRepository
    from app.repositories.user_repo import UserRepository

    user_repo = UserRepository()
    case_repo = CaseRepository()

    lawyer = await user_repo.find_by_id(lawyer_id)
    if not _indexable(lawyer):
        return False

    recent_cases = await case_repo.find_many(
        {"lawyer_id": lawyer_id},
        sort=[("created_at", -1)],
        limit=5,
    )

    profile_text = build_profile_text(lawyer, recent_cases)
    if not profile_text.strip():
        return False

    # Run CPU-bound embedding in thread pool (Inception pattern: non-blocking async)
    emb_model = _embeddings()
    vector = await asyncio.to_thread(emb_model.embed_documents, [profile_text])
    vector = vector[0]

    # Re-check immediately before writing, NOT only at the top.
    #
    # The gate above was evaluated before a multi-second model load on a machine
    # with no GPU. An admin rejecting KYC inside that window called
    # `forget_lawyers` against a row that did not exist yet, and this upsert then
    # landed AFTER the removal — seating a rejected lawyer in the candidate pool
    # with nothing left to take them out again. Measured: the stale writer won
    # the race every time.
    #
    # This narrows the window from seconds to the microseconds between the read
    # below and the upsert; it does not eliminate it. Closing it completely
    # needs a tombstone the writer checks, which is not worth the machinery for
    # a window this small when the next profile edit or backfill repairs it.
    fresh = await user_repo.find_by_id(lawyer_id)
    if not _indexable(fresh):
        logger.info(
            "lawyer %s stopped being matchable while embedding; not indexed",
            lawyer_id,
        )
        return False

    col = _get_collection()
    col.upsert(
        ids=[lawyer_id],
        embeddings=[vector],
        documents=[profile_text],
        # Only `province` is stored, because only `province` is READ — it is the
        # filter in `query_similar_lawyers`. Rating, availability, experience and
        # specializations used to be written here too and never read once: the
        # matcher scores from the MongoDB document. They changed on every review
        # and profile edit while the copy here stayed frozen at embed time, so
        # they were a stale mirror waiting for someone to trust it.
        metadatas=[{
            "lawyer_id": lawyer_id,
            "province":  lawyer.get("province", "federal"),
            # What this vector was built FROM. Lets the reconciler tell a stale
            # vector from a current one — see `profile_fingerprint`.
            "fingerprint": _fingerprint(profile_text),
        }],
    )
    return True


# Strong references to in-flight background embeds. asyncio only holds a weak
# reference to a running task, so without this the garbage collector can cancel
# one mid-flight.
_PENDING: set[asyncio.Task] = set()


async def _embed_quietly(lawyer_id: str) -> None:
    try:
        embedded = await embed_lawyer(lawyer_id)
        if not embedded:
            logger.info(
                "lawyer %s not embedded: unverified, inactive, or empty profile",
                lawyer_id,
            )
    except Exception:
        logger.warning("background embed failed for lawyer %s", lawyer_id,
                       exc_info=True)


def schedule_embed(lawyer_id: str) -> bool:
    """Refresh a lawyer's vector in the background. Never raises.

    Background rather than inline because the first embedding in a process pays
    a multi-second model load (`_embeddings()` is lru_cached, there is no GPU),
    and the callers are an admin clicking Approve and a lawyer saving their
    profile. Neither should wait on the index, and neither should fail if the
    index does — the approval and the profile edit are already committed by the
    time this is scheduled.

    Returns whether a task was actually started, so a synchronous caller (a
    script, a test) can tell that it needs to await `embed_lawyer` itself.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False  # no event loop — nothing to schedule onto
    task = loop.create_task(_embed_quietly(lawyer_id))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return True


def forget_lawyers(lawyer_ids: Sequence[str]) -> int:
    """Remove lawyers from the vector store. Never raises.

    The counterpart nobody wrote. Embeds were written on demand and removed
    never, so a deleted lawyer's vector outlived the lawyer — and because
    matching used to branch on whether the vector query returned *any* rows,
    two such ghosts were enough to suppress the entire real candidate pool.

    Called on KYC rejection, deactivation, account closure, and whenever a
    query surfaces a hit that no longer resolves to a matchable lawyer.
    Failure to forget must never fail the action that triggered it: the caller
    is deleting an account, not maintaining an index.
    """
    ids = [str(i) for i in lawyer_ids if i]
    if not ids:
        return 0
    try:
        _get_collection().delete(ids=ids)
        return len(ids)
    except Exception:
        logger.warning("could not remove %d lawyer(s) from %s",
                       len(ids), LAWYERS_COLLECTION, exc_info=True)
        return 0


def indexed_lawyer_ids(lawyer_ids: Sequence[str]) -> set[str]:
    """Which of these lawyers actually hold a vector. Never raises.

    The matcher needs to tell two very different situations apart:

      * this lawyer has no vector          -> we have no semantic evidence
      * this lawyer has one, but this query did not rank them highly
                                           -> we have evidence, and it is poor

    Without this it could only observe "not in the hit list", which conflates
    the two — and because the no-evidence branch redistributes the semantic
    weight across the remaining factors, conflating them turned a poor semantic
    match into a HIGHER score than a good one. See `_score_lawyer`.

    Returns the empty set on any failure, which reads as "no vectors" and sends
    every candidate down the no-evidence branch — the same behaviour as a vector
    store that is down, and the same behaviour as before this existed.
    """
    ids = [str(i) for i in lawyer_ids if i]
    if not ids:
        return set()
    try:
        got = _get_collection().get(ids=ids, include=[])
        return set(got.get("ids") or [])
    except Exception:
        logger.warning("could not check %s membership for %d id(s)",
                       LAWYERS_COLLECTION, len(ids), exc_info=True)
        return set()


async def embed_all_lawyers() -> int:
    """
    Batch embed all KYC-verified active lawyers.
    Called once on setup or via admin endpoint.
    Returns number of lawyers successfully embedded.

    Prefer `scripts/backfill_lawyer_embeddings.py` for a bulk run: it reports
    per-lawyer outcomes and does not do a model load inside a request.
    """
    from app.repositories.user_repo import UserRepository

    user_repo = UserRepository()
    lawyers = await user_repo.find_many(
        {
            "role": "lawyer",
            "lawyer_profile.kyc_verified": True,
            "is_active": True,
        }
    )

    count = 0
    for lawyer in lawyers:
        try:
            ok = await embed_lawyer(str(lawyer["_id"]))
            if ok:
                count += 1
        except Exception:
            # Was a bare `except: pass`, which made a crashed model load and an
            # empty profile indistinguishable — "embedded 9" told you nothing
            # about the other 16. Still continues (one bad profile must not
            # abandon the rest), but no longer silently.
            logger.warning("bulk embed failed for lawyer %s",
                           lawyer.get("_id"), exc_info=True)

    return count


async def reconcile_index() -> dict[str, int]:
    """Make the vector store agree with MongoDB again. Returns what it changed.

    Every write to the index is event-driven — KYC approval, profile edits,
    reactivation, rejection, closure, case assignment — and every one of those
    is fire-and-forget by design, because none of them should fail a user's
    action just because an index is unavailable. The consequence is that drift
    is possible and, until now, nothing could observe it: a lawyer approved
    while Chroma was down was simply never indexed, and no code path would ever
    notice. The repair existed only as a script somebody had to remember to run,
    which is how the store came to hold two smoke-test rows and no real lawyer.

    Fixing drift is cheap. NOTICING it was the missing part, so this reports
    counts even when it changes nothing.

    Three kinds of disagreement, not one. Membership was the obvious pair:

      missing  — should be indexed, is not
      extra    — is indexed, should not be

    and comparing id sets finds both. It cannot find the third:

      stale    — indexed, but built from a profile that has since changed

    which is invisible to a set comparison because the id is present and
    correct. That is the drift most likely to survive, because it is produced by
    the same fire-and-forget writes as the others: a lawyer edits their
    specializations while Chroma is unreachable, `schedule_embed` logs and gives
    up, and the vector keeps describing a lawyer who no longer exists. Every
    later sweep saw the id, called it healthy, and moved on. Now each stored
    vector carries a `fingerprint` of the text it was built from, so "the id is
    there" and "it is current" are separate questions.

    Still conservative about WORK: a lawyer whose fingerprint matches is never
    re-embedded, so a clean sweep costs one Chroma read and one Mongo query and
    loads no model. Only genuinely changed profiles pay for inference, which
    matters on a machine with no GPU.

    A vector with no stored fingerprint predates this and is treated as current,
    not as stale. Treating it as stale would re-embed the entire index on the
    first sweep after deploy — a model load per lawyer, all at once, to fix
    nothing that is known to be wrong.
    """
    from app.repositories.user_repo import UserRepository

    lawyers = await UserRepository().find_many(
        {"role": "lawyer", "lawyer_profile.kyc_verified": True, "is_active": True}
    )
    should_be = {str(lawyer["_id"]) for lawyer in lawyers}

    try:
        got = _get_collection().get(include=["metadatas"])
        stored_ids = list(got.get("ids") or [])
        metas = list(got.get("metadatas") or [])
        stored_fp = {
            lid: (meta or {}).get("fingerprint")
            for lid, meta in zip(stored_ids, metas)
        }
    except Exception:
        logger.warning("reconcile: could not read %s; skipping this sweep",
                       LAWYERS_COLLECTION, exc_info=True)
        return {"checked": len(should_be), "embedded": 0, "refreshed": 0,
                "forgotten": 0, "failed": 0, "skipped": 1}

    stored = set(stored_ids)
    missing = should_be - stored
    extra = stored - should_be

    # Stale: present on both sides, but the stored vector was built from text
    # that no longer matches the profile.
    stale: list[str] = []
    for lawyer_id in sorted(should_be & stored):
        recorded = stored_fp.get(lawyer_id)
        if not recorded:
            continue  # predates fingerprinting — see the docstring
        current = await profile_fingerprint(lawyer_id)
        if current and current != recorded:
            stale.append(lawyer_id)

    embedded = refreshed = failed = 0
    for lawyer_id in sorted(missing) + stale:
        try:
            if await embed_lawyer(lawyer_id):
                if lawyer_id in stale:
                    refreshed += 1
                else:
                    embedded += 1
        except Exception:
            failed += 1
            logger.warning("reconcile: embed failed for lawyer %s", lawyer_id,
                           exc_info=True)

    forgotten = forget_lawyers(sorted(extra)) if extra else 0

    if missing or extra or stale:
        logger.warning(
            "reconcile: %s drifted from MongoDB — %d missing (%d embedded), "
            "%d stale (%d refreshed), %d orphaned (%d removed), %d failed",
            LAWYERS_COLLECTION, len(missing), embedded,
            len(stale), refreshed, len(extra), forgotten, failed,
        )
    else:
        logger.info("reconcile: %s agrees with MongoDB (%d lawyers)",
                    LAWYERS_COLLECTION, len(should_be))

    return {"checked": len(should_be), "embedded": embedded,
            "refreshed": refreshed, "forgotten": forgotten,
            "failed": failed, "skipped": 0}


async def query_similar_lawyers(
    query_text: str,
    province: str,
    n_results: int = 20,
) -> list[dict]:
    """
    Semantic search in lawyers_collection.

    Returns list of dicts: {"lawyer_id": str, "semantic_score": float, "metadata": dict}
    Returns [] if collection is empty or query fails.
    """
    col = _get_collection()
    if col.count() == 0:
        return []

    emb_model = _embeddings()
    query_vec = await asyncio.to_thread(emb_model.embed_query, query_text)

    # Province filter: match province OR "federal" lawyers
    if province and province != "federal":
        where = {"$or": [
            {"province": {"$eq": province}},
            {"province": {"$eq": "federal"}},
        ]}
    else:
        where = None  # federal case → all lawyers are candidates

    kwargs: dict = {
        "query_embeddings": [query_vec],
        "n_results":        min(n_results, col.count()),
        "include":          ["metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)

    output = []
    for i, lawyer_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        # ChromaDB cosine space: distance = 1 - cosine_similarity → similarity = 1 - distance
        raw = max(0.0, 1.0 - float(distance))
        output.append({
            "lawyer_id":      lawyer_id,
            # Calibrated, because the raw figure is unusable as a score: see
            # the measurements above calibrate_similarity. Ordering is
            # unchanged — the transform is monotonic.
            "semantic_score": calibrate_similarity(raw),
            # Kept for debugging and for reproducing the calibration.
            "raw_similarity": round(raw, 4),
            "metadata":       results["metadatas"][0][i],
        })

    return output
