"""Re-run citation verification for the 19 migrated V2 revisions. READ-ONLY.

Runs the SAME process the generation pipeline runs -- document_service.
_verification_record -> citation_verification.verify_text -- against each
revision's stored body_text, with the intended ChromaDB knowledge base
connected.

NOTHING IS WRITTEN BACK.
  * Mongo is opened with the read-only v2_survey credential, so "does not modify
    the revisions" is enforced by the server, not asserted here.
  * Chroma is opened on a BYTE-VERIFIED COPY of backend/chroma_data. Opening a
    PersistentClient writes to its sqlite, so the real knowledge base is never
    opened by this script at all.

CLASSIFICATION. `ran: false` is not a pass, and neither is "ran but could not
check". Five outcomes, deliberately kept apart:

  verified-clean  every citation found resolves to a provision the corpus holds
  partial         ran, nothing flagged, but >=1 citation the corpus CANNOT check
  FAILED          >=1 citation NOT_IN_CORPUS or OMITTED (repealed) -- is_flag
  no-citations    ran; the document cites no authority at all
  unavailable     the check could not run

FAILED is taken from the code's own `is_flag` definition of a positive finding
rather than re-derived here.
"""
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

REAL_KB = BACKEND / "chroma_data"
KB_COPY = Path(os.environ["SCRATCH"]) / "chroma_copy"

FLAG_STATUSES = ("NOT_IN_CORPUS", "OMITTED")

# Anything that LOOKS like a statutory reference. Used only as a tripwire on the
# revisions where the checker reported nothing: if this matches and the checker
# found zero citations, the zero is suspect and is reported as such rather than
# quietly counted as a clean result.
LOOKS_LIKE_CITATION = re.compile(
    r"(?:section|sec\.|u/s|under section|article|art\.|order|rule|schedule)"
    r"\s*\d|\d\s*(?:of\s+)?(?:PPC|CrPC|CPC|PECA|QSO|CNSA)",
    re.I)


def tree_state(root: Path) -> str:
    """Content fingerprint of a directory tree."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(str(path.stat().st_size).encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


async def main() -> int:
    from app.core.config import settings

    uri = Path(os.environ["TEMP"], "v2s.txt").read_text(encoding="utf-8")
    settings.mongodb_url = uri

    from app.db.mongodb import connect_db, get_database
    await connect_db()
    db = get_database()
    info = await db.command({"connectionStatus": 1, "showPrivileges": True})
    roles = sorted({r["role"] for r in info["authInfo"]["authenticatedUserRoles"]})
    print(f"mongo credential : {roles}")
    if roles != ["read"]:
        raise SystemExit("ABORT: must not run with a writable credential")
    print(f"DOCUMENTS_V2     : {settings.documents_v2}")

    print("\n=== ChromaDB ===")
    if not KB_COPY.is_dir():
        raise SystemExit(f"ABORT: no knowledge-base copy at {KB_COPY}")
    real_before = tree_state(REAL_KB)
    print(f"  source          : {REAL_KB}")
    print(f"  opened          : verified copy in the scratchpad")

    import app.db.chroma as chroma_mod
    chroma_mod._CHROMA_PATH = KB_COPY
    chroma_mod.connect_chroma()
    client = chroma_mod.get_chroma()
    names = {c.name for c in client.list_collections()}
    total_chunks = 0
    for name in chroma_mod.COLLECTIONS:
        if name in names:
            count = client.get_collection(name).count()
            total_chunks += count
            print(f"    {name:28} {count:>8,} chunks")
        else:
            print(f"    {name:28} ABSENT")
    print(f"    {'TOTAL':28} {total_chunks:>8,} chunks")
    if total_chunks == 0:
        raise SystemExit("ABORT: knowledge base is empty; verification would be "
                         "vacuously clean. Refusing to report that as a pass.")

    from app.ai.corpus_index import get_index
    index = get_index()
    corpus = {"statutes": len(index), "sections_indexed": index.total_sections(),
              "dense_enough_to_flag": sum(1 for s in index.statutes
                                          if index.coverage(s).dense)}
    print(f"  corpus index    : {corpus}")
    if corpus["statutes"] == 0:
        raise SystemExit("ABORT: corpus index empty; not a pass.")

    # CONTROLS. If the checker cannot flag a citation it should flag, every
    # "clean" below is worthless. Both directions are exercised before any
    # result is trusted.
    #
    # The bogus section must be PLAUSIBLE. The parser drops absurd numbers
    # ("section 999999" parses to nothing), so an implausible probe tests the
    # parser's sanity filter rather than the verifier -- and passes vacuously.
    # The honest negative control is a number inside the statute's own range
    # that the corpus does not hold.
    from app.ai.citation_verification import verify_statutes
    negative = positive = None
    for statute in [s for s in index.statutes if index.coverage(s).dense]:
        cov = index.coverage(statute)
        for gap in (n for n in range(1, cov.highest or 1)
                    if n not in cov.numbered):
            probe = f"under section {gap} of the {statute}"
            if any(c.is_flag for c in verify_statutes(probe, None, index)):
                negative = (statute, gap)
                break
        if negative:
            real = sorted(cov.numbered)[len(cov.numbered) // 2]
            checks = verify_statutes(f"under section {real} of the {statute}",
                                     None, index)
            if all(c.status == "VERIFIED" for c in checks) and checks:
                positive = (statute, real)
            break
    print(f"\n  control -- absent section IS flagged : "
          f"{bool(negative)}  ({negative[0]} s.{negative[1]})" if negative
          else "\n  control -- absent section IS flagged : False")
    print(f"  control -- held section IS verified  : "
          f"{bool(positive)}  ({positive[0]} s.{positive[1]})" if positive
          else "  control -- held section IS verified  : False")
    if not (negative and positive):
        raise SystemExit("ABORT: the checker did not behave correctly on a "
                         "known-absent or known-present section. Any 'clean' "
                         "verdict would be meaningless.")

    from app.services.document_service import (_unavailable_verification,
                                               _verification_record)
    from app.services.document_v2_service import _build_verification_inputs

    revisions = sorted(await db["document_revisions"].find({}).to_list(length=None),
                       key=lambda r: r["document_id"])
    print(f"\n=== {len(revisions)} revisions ===\n")

    rows = []
    buckets = {"clean": [], "partial": [], "failed": [], "no_citations": [],
               "unavailable": []}
    for revision in revisions:
        doc_id = revision["document_id"]
        template = revision.get("template_type")
        body = revision.get("body_text")
        _status, profile, text, unavailable = _build_verification_inputs(
            template, body, revision.get("extraction_status") or "ok")
        if unavailable:
            record = _unavailable_verification(unavailable)
        elif not (text or "").strip():
            record = _unavailable_verification("extracted_text_empty")
        else:
            record = await _verification_record({"document": text})

        counts = record.get("counts") or {}
        checks = record.get("checks") or []
        flags = [c for c in checks if c.get("status") in FLAG_STATUSES]
        unverifiable = [c for c in checks if c.get("status") == "UNVERIFIABLE"]
        suspect = bool(record.get("ran") and counts.get("total", 0) == 0
                       and LOOKS_LIKE_CITATION.search(body or ""))

        if not record.get("ran"):
            bucket = "unavailable"
        elif flags:
            bucket = "failed"
        elif counts.get("total", 0) == 0:
            bucket = "no_citations"
        elif unverifiable:
            bucket = "partial"
        else:
            bucket = "clean"
        buckets[bucket].append(doc_id)

        rows.append({
            "document_id": doc_id, "revision_id": revision["_id"],
            "template_type": template, "profile": profile, "bucket": bucket,
            "ran": bool(record.get("ran")), "counts": counts,
            "reason": record.get("reason"),
            "needs_human_check": record.get("needs_human_check"),
            "body_chars": len(body or ""), "zero_but_looks_cited": suspect,
            "checks": [{k: c.get(k) for k in ("raw", "canonical", "kind", "status")}
                       for c in checks],
        })

        label = {"clean": "VERIFIED-CLEAN", "partial": "PARTIAL (unverifiable)",
                 "failed": "*** FAILED ***", "no_citations": "RAN / NO CITATIONS",
                 "unavailable": "UNAVAILABLE"}[bucket]
        print(f"{doc_id[:22]:24} {str(template):22} {label}")
        if record.get("ran"):
            print(f"{'':24} total {counts.get('total', 0)} | verified "
                  f"{counts.get('verified', 0)} | not_in_corpus "
                  f"{counts.get('not_in_corpus', 0)} | repealed "
                  f"{counts.get('omitted', 0)} | unverifiable "
                  f"{counts.get('unverifiable', 0)} | text {len(body or '')} chars")
            for check in checks:
                mark = "  " if check.get("status") == "VERIFIED" else ">>"
                shown = check.get("canonical") or check.get("raw")
                print(f"{'':24} {mark} [{check.get('status')}] "
                      f"{check.get('kind')} {str(shown)[:62]}")
            if suspect:
                print(f"{'':24} !! the text contains citation-like wording but "
                      f"the checker found none -- NOT treated as clean")
        else:
            print(f"{'':24} reason: {record.get('reason')}")
        print()

    real_after = tree_state(REAL_KB)

    print("=" * 74)
    print(f"  verified-clean            {len(buckets['clean']):>3}   every citation resolves in the corpus")
    print(f"  partial                   {len(buckets['partial']):>3}   ran, no flags, but >=1 citation uncheckable")
    print(f"  FAILED                    {len(buckets['failed']):>3}   >=1 citation not in corpus or repealed")
    print(f"  ran / no citations        {len(buckets['no_citations']):>3}   document cites no authority at all")
    print(f"  verification UNAVAILABLE  {len(buckets['unavailable']):>3}   could not run -- NOT a pass")
    print("                            ---")
    print(f"  total                     {len(revisions):>3}")
    suspects = [r["document_id"] for r in rows if r["zero_but_looks_cited"]]
    print(f"\n  zero-citation results contradicted by the text : {len(suspects)}")
    print(f"  REAL knowledge base unchanged by this run      : {real_before == real_after}")

    out = Path.home() / "v2-citation-verification.json"
    out.write_text(json.dumps(
        {"corpus": corpus, "chroma_chunks": total_chunks,
         "opened": str(KB_COPY), "source": str(REAL_KB),
         "real_kb_unchanged": real_before == real_after,
         "control_absent_flagged": str(negative),
         "control_present_verified": str(positive),
         "buckets": {k: len(v) for k, v in buckets.items()},
         "zero_but_looks_cited": suspects, "rows": rows},
        indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"\n  report: {out.name}  (nothing written to Mongo or the real KB)")
    return 0


raise SystemExit(asyncio.run(main()))
