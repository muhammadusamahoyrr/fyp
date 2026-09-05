"""Read-only pre-activation check for the V2 index contract.

WHAT THIS IS FOR

Enabling DOCUMENTS_V2 makes `enforce_v2_correctness_indexes` fatal: the app will
refuse to start if any declared index is missing or malformed. Discovering that
during a deploy is a bad time to discover it. This answers the same question
beforehand, against a running database, without changing anything.

IT WRITES NOTHING. Not the indexes it says are missing, not the obsolete ones it
recommends removing. Both are printed as commands for a person to read, decide
on, and run — because an index build on a large collection is a capacity event,
and dropping one is irreversible without another build. A preflight that fixed
things itself would also destroy the evidence used to approve the fix.

    python -m app.db.v2_index_preflight
"""
from __future__ import annotations

import asyncio
import json

from app.db.v2_index_spec import (
    CORRECTNESS,
    V2_INDEX_REQUIREMENTS,
    IndexSpec,
)

# Indexes THIS SYSTEM created and has since superseded.
#
# A curated list, not "anything undeclared". Every V2 collection also carries
# legacy indexes that predate this work and are still used by legacy queries;
# recommending those for deletion because they are absent from a V2 manifest
# would be advice that breaks the running system.
OBSOLETE_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("documents", "v2_review_queue",
     "Superseded by v2_queue_pending. It carried `submitted_at` between the "
     "equality prefix and `_id`, so it could satisfy the queue's filter but "
     "not its sort — every page paid a blocking SORT over the lawyer's whole "
     "inbox. Replaced rather than altered because Mongo refuses to change an "
     "existing index's keys under the same name."),
    ("documents", "v2_review_cycles",
     "Superseded by v2_queue_cycles, which appends `_id` so the index provides "
     "the sort as well as the match. Without it the decided tabs examined "
     "every matching document on every page, including deep ones."),
    ("documents", "v2_reviewed_queue",
     "Keyed on (reviewer_id, review_status) — the queue predicate from before "
     "multi-cycle review. `reviewer_id` holds one lawyer and the decided tabs "
     "now ask review_cycles $elemMatch {lawyer_id, action}, so nothing queries "
     "this shape. It costs a write on every decision and returns nothing."),
)


def _create_command(spec: IndexSpec) -> str:
    options: list[str] = [f'name: "{spec.name}"']
    if spec.unique:
        options.append("unique: true")
    if spec.sparse:
        options.append("sparse: true")
    if spec.partial_filter:
        options.append(
            f"partialFilterExpression: {json.dumps(dict(spec.partial_filter))}")
    keys = ", ".join(f'"{f}": {d}' for f, d in spec.keys)
    return (f'db.{spec.collection}.createIndex({{{keys}}}, '
            f'{{{", ".join(options)}}})')


async def preflight() -> dict:
    """Everything an operator needs to decide whether the flag can be flipped.

    Read-only. Returns a structure; `report()` renders it.
    """
    from app.db.indexes import validate_v2_indexes
    from app.db.mongodb import get_database

    problems = await validate_v2_indexes()
    db = get_database()

    # Obsolete indexes that are actually present. Reported, never dropped.
    obsolete: list[dict] = []
    for collection, name, why in OBSOLETE_INDEXES:
        try:
            info = await db[collection].index_information()
        except Exception as exc:  # noqa: BLE001
            obsolete.append({"collection": collection, "name": name,
                             "present": None,
                             "why": ("could not be checked "
                                     f"(error_class={type(exc).__name__})")})
            continue
        if name in info:
            obsolete.append({"collection": collection, "name": name,
                             "present": True, "why": why})

    by_name = {s.name: s for s in V2_INDEX_REQUIREMENTS}
    fixes = [_create_command(by_name[p.name])
             for p in problems if p.name in by_name]
    drops = [f'db.{o["collection"]}.dropIndex("{o["name"]}")'
             for o in obsolete if o.get("present")]

    correctness_problems = [p for p in problems if p.kind == CORRECTNESS]

    return {
        # RENAMED from `safe_to_enable`, which claimed more than this check can
        # know. It inspects indexes. Whether the flag may be flipped ALSO
        # depends on the migration having run and on the queue-visibility gap
        # being empty, and neither is looked at here — a name promising overall
        # safety invites someone to read a green line as permission.
        "indexes_ready": not problems,
        "database": db.name,
        "problems": [
            {"code": p.code, "collection": p.collection, "name": p.name,
             "kind": p.kind, "message": p.message}
            for p in problems
        ],
        "correctness_problems": len(correctness_problems),
        "query_problems": len(problems) - len(correctness_problems),
        "obsolete_present": obsolete,
        # Commands, not actions.
        "recommended_create": fixes,
        "recommended_drop": drops,
    }


def render(result: dict) -> str:
    lines = [
        f"V2 index preflight — database {result['database']!r}",
        "",
    ]
    if result["indexes_ready"]:
        lines.append("  INDEXES READY: every declared index is present and valid.")
    else:
        lines.append(
            f"  INDEXES NOT READY: {len(result['problems'])} problem(s) "
            f"({result['correctness_problems']} correctness, "
            f"{result['query_problems']} query).")
        lines.append("")
        for problem in result["problems"]:
            lines.append(f"    [{problem['kind']}/{problem['code']}] "
                         f"{problem['collection']}.{problem['name']}: "
                         f"{problem['message']}")

    if result["recommended_create"]:
        lines += ["", "  Run to fix (review first — an index build on a large",
                  "  collection is a capacity event):"]
        lines += [f"    {c}" for c in result["recommended_create"]]

    if result["obsolete_present"]:
        lines += ["", "  Obsolete indexes present. NOT dropped by this check:"]
        for entry in result["obsolete_present"]:
            lines.append(f"    {entry['collection']}.{entry['name']}")
            lines.append(f"        {entry['why']}")
        lines += ["", "  Cleanup, once reviewed:"]
        lines += [f"    {c}" for c in result["recommended_drop"]]
        lines += ["",
                  "  Dropping is irreversible without another build. Do it in a",
                  "  maintenance window, after confirming no deploy still runs",
                  "  the previous queue code."]

    lines += [
        "",
        "  THIS CHECK COVERS INDEXES ONLY. Indexes ready is a necessary",
        "  condition, not permission.",
        "",
        "  For the decision itself run:",
        "      document_migration.activation_readiness()",
        "  which composes this check with the three gates it does not cover —",
        "  the migration having been applied, the queue-visibility gap, and",
        "  whether the migrated documents are actually usable.",
    ]
    return "\n".join(lines) + "\n"


async def _main() -> int:
    from app.db.mongodb import close_db, connect_db

    await connect_db()
    try:
        result = await preflight()
    finally:
        await close_db()
    print(render(result))
    return 0 if result["indexes_ready"] else 1


if __name__ == "__main__":   # pragma: no cover - operator entry point
    raise SystemExit(asyncio.run(_main()))
