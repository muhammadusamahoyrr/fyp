"""How much of a case's evidence was actually read — one contract, shared.

WHY THIS IS ITS OWN MODULE

Three places need the same answer and none of them may import the others: the
intake service records it, the case carries it, and `case_context` hands it to a
model when a lawyer drafts. A second copy of the rule in any of them would drift,
and it would drift in the direction that reads best — toward implying the
evidence was complete.

WHAT IT REFUSES TO SAY

That an old case was fine. A case recorded before coverage tracking existed has
NO snapshot, and the honest rendering of that is "unknown", never "complete".
Absence of a limitation record is not evidence that there was no limitation, and
for a legal summary that distinction is the whole point.

SANITISED BY CONSTRUCTION

A snapshot carries counts and versions. No filenames, no paths, no extracted
text, no page-level detail that could reconstruct content. It is safe to store on
a case, return over the API and place in a prompt.
"""
from __future__ import annotations

SCHEMA = "evidence_coverage/1"

#: Statuses that mean the file's text reached the analysis in full.
_FULLY_READ = {"readable"}
#: Read, but the analysis saw only part of what was extracted.
_PARTIAL = {"partially_read"}
#: Extracted fine; left out because the prompt ran out of room. Fixable by the
#: client, unlike anything else here, so it is never folded into "not read".
_BUDGET = {"omitted_limit"}
#: Accepted and stored, but no extractor can read this format. Nothing is wrong
#: with the file.
_STORAGE_ONLY = {"storage_only"}

#: Formats accepted at upload that no extractor can read. Derived from the
#: SERVER-detected mime, never from the client's filename or Content-Type.
STORAGE_ONLY_MIMES = frozenset({
    "application/msword",
    "image/jpeg", "image/png", "image/gif", "image/webp",
})


def derive_analysis_support(meta: dict | None) -> str | None:
    """`storage_only`, or None when the format is analysable or unknown.

    Prefers the value persisted at upload. Falls back to the stored content type
    for records written before that field existed — conservative in the only
    direction that matters: an unrecognised type yields None ("we do not know"),
    never an assertion that the file was analysable.
    """
    if not meta:
        return None
    stored = meta.get("analysis_support")
    if stored:
        return str(stored)
    if str(meta.get("content_type") or "") in STORAGE_ONLY_MIMES:
        return "storage_only"
    return None


def _count_status(statuses: list[dict], wanted: set[str]) -> int:
    return sum(1 for s in statuses if str(s.get("status") or "") in wanted)


def snapshot_from_statuses(
    statuses: list[dict] | None,
    uploaded_count: int | None = None,
) -> dict | None:
    """Sanitised coverage summary, or None when coverage is UNKNOWN.

    MISSING IS NOT EMPTY, and conflating them is the sharper edge of this whole
    feature. `None` means no extraction record was produced — the analysis may
    have failed, or the caller may be older code. `[]` means extraction ran and
    found nothing to report. Both used to render as "No documents were uploaded
    with this case", which is a POSITIVE claim about a case that might have had
    five attachments the pipeline never looked at.

    An empty list alone is not enough to assert zero uploads either. It is only
    a verified zero when it agrees with what was actually attached, which is why
    `uploaded_count` exists: `[]` against three uploaded files is not "no
    documents", it is a missing record, and it returns None.

    Page totals are summed only when EVERY file reported one. A single unknown
    makes the total unknown, because a partial sum presented as a total is a
    smaller number that reads as a complete one.
    """
    if statuses is None:
        # No record at all. Rendering this as a snapshot of zero would state, on
        # the case, that nothing was uploaded.
        return None

    rows = list(statuses)

    if not rows:
        # A verified zero requires corroboration from the evidence actually
        # attached. Without it — or in contradiction of it — this is a gap in
        # the record, not a measurement of nothing.
        if uploaded_count is None or uploaded_count != 0:
            return None

    totals: int | None = 0
    with_text: int | None = 0
    for row in rows:
        pt, pw = row.get("pages_total"), row.get("pages_with_text")
        if pt is None or totals is None:
            totals = None
        else:
            totals += int(pt)
        if pw is None or with_text is None:
            with_text = None
        else:
            with_text += int(pw)

    full = _count_status(rows, _FULLY_READ)
    partial = _count_status(rows, _PARTIAL)
    budget = _count_status(rows, _BUDGET)
    storage = _count_status(rows, _STORAGE_ONLY)
    # Everything else — unreadable, missing, invalid_path, and any status a
    # future extractor introduces. Counted as not-read rather than ignored, so a
    # new status cannot silently vanish from the totals.
    not_read = len(rows) - full - partial - budget - storage

    # A file marked fully read can still have been truncated out of the prompt.
    truncated = sum(1 for r in rows if r.get("truncated"))

    return {
        "schema": SCHEMA,
        "files_total": len(rows),
        "files_read_in_full": full,
        "files_partially_read": partial,
        "files_omitted_for_length": budget,
        "files_storage_only": storage,
        "files_not_read": max(0, not_read),
        "files_prompt_truncated": truncated,
        "pages_total": totals,
        "pages_with_text": with_text,
        "complete": bool(rows) and full == len(rows) and truncated == 0,
    }


#: The count fields a snapshot must carry, all of them, all valid.
_COUNT_FIELDS = (
    "files_total", "files_read_in_full", "files_partially_read",
    "files_omitted_for_length", "files_storage_only", "files_not_read",
    "files_prompt_truncated",
)

#: The categories that must add up to `files_total`. `files_prompt_truncated`
#: is deliberately excluded: a truncated file is ALSO counted in one of these,
#: so including it would double-count and fail a correct snapshot.
_CATEGORY_FIELDS = (
    "files_read_in_full", "files_partially_read", "files_omitted_for_length",
    "files_storage_only", "files_not_read",
)

UNKNOWN_LINE = (
    "Evidence coverage for this case was not recorded or could not be read, so "
    "it is UNKNOWN whether the summary reflects all uploaded evidence. Do not "
    "assume it does."
)


def _count(value) -> int | None:
    """A non-negative integer, or None when the value is not one.

    `bool` is rejected FIRST and explicitly. In Python `isinstance(True, int)`
    is True, so a naive integer check accepts `True` and renders it as the
    number 1 — a count fabricated out of a flag. That is the kind of value that
    reaches a stored document through a migration or a hand edit and then reads
    as a real measurement.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _optional_count(value) -> tuple[bool, int | None]:
    """(valid, value) for a field where None legitimately means unknown."""
    if value is None:
        return True, None
    parsed = _count(value)
    return (parsed is not None), parsed


def validate_snapshot(snapshot) -> dict | None:
    """A structurally sound snapshot, or None. Never raises.

    Everything a caller relies on is checked here rather than at the point of
    use, because the alternative is each renderer deciding for itself what a
    malformed record means — and the convenient answer is always the optimistic
    one.

    `complete` is NOT read. It is recomputed from the counts, so a stored `True`
    on a record whose counts disagree cannot assert completeness.
    """
    if not isinstance(snapshot, dict) or not snapshot:
        return None

    counts: dict[str, int] = {}
    for field in _COUNT_FIELDS:
        parsed = _count(snapshot.get(field))
        if parsed is None:
            return None
        counts[field] = parsed

    # The categories must account for every file. A snapshot whose parts do not
    # sum to its own total is not partially usable — it is a record we cannot
    # interpret, and interpreting it anyway is how a smaller number gets read as
    # a complete one.
    if sum(counts[f] for f in _CATEGORY_FIELDS) != counts["files_total"]:
        return None

    # A file cannot be truncated unless it exists.
    if counts["files_prompt_truncated"] > counts["files_total"]:
        return None

    ok_total, pages_total = _optional_count(snapshot.get("pages_total"))
    ok_text, pages_with_text = _optional_count(snapshot.get("pages_with_text"))
    if not ok_total or not ok_text:
        return None
    if (pages_total is not None and pages_with_text is not None
            and pages_with_text > pages_total):
        return None

    out = dict(counts)
    out["pages_total"] = pages_total
    out["pages_with_text"] = pages_with_text
    out["complete"] = is_complete(counts)
    return out


def is_complete(counts: dict) -> bool:
    """Derived, never trusted from the record.

    Completeness requires that files exist, every one of them was read in full,
    and none was truncated before reaching the analysis. Any other shape is not
    complete however the stored flag reads.
    """
    total = _count(counts.get("files_total"))
    full = _count(counts.get("files_read_in_full"))
    truncated = _count(counts.get("files_prompt_truncated")) or 0
    if not total or full is None:
        return False
    return full == total and truncated == 0


def coverage_line(snapshot: dict | None) -> str:
    """One sentence for a prompt or a screen. Never claims completeness it
    cannot support, and never raises on a malformed record.

    Three distinct situations, kept apart:
      * no record at all, or an unreadable one  -> UNKNOWN
      * a valid record of zero uploads          -> verified "no documents"
      * a valid record of some uploads          -> the breakdown
    """
    checked = validate_snapshot(snapshot)
    if checked is None:
        return UNKNOWN_LINE

    total = checked["files_total"]
    if total == 0:
        # A VERIFIED zero. Distinct from the unknown case above: this case was
        # converted with coverage tracking and genuinely had no uploads, which
        # is a fact rather than an absence of one.
        return "No documents were uploaded with this case."

    if checked["complete"]:
        return f"All {total} uploaded file(s) were read in full."

    snapshot = checked

    bits = []
    for key, label in (
        ("files_read_in_full", "read in full"),
        ("files_partially_read", "only partly read"),
        ("files_omitted_for_length", "left out because the analysis reached its length limit"),
        ("files_storage_only", "stored but not analysable"),
        ("files_not_read", "could not be read"),
    ):
        n = int(snapshot.get(key) or 0)
        if n:
            bits.append(f"{n} {label}")

    truncated = int(snapshot.get("files_prompt_truncated") or 0)
    if truncated:
        bits.append(f"{truncated} truncated before reaching the analysis")

    return (
        f"Of {total} uploaded file(s): " + "; ".join(bits) + ". "
        "The summary may therefore not reflect all of the evidence."
    )
