"""DEVELOPMENT-ONLY identity trace: every gold NAME mention of a development
set through the review path (ANALYZER_PII_IDENTITY.md).

    python scripts/analyzer_pii_identity_trace.py --dataset identity-dev-2 [--doc ID] [--json OUT]

Per mention: source offsets, whether it crosses a sentence, the token masking
PROPOSED (no review), the simulated reviewer's decision on it, the FINAL
token(s), and the document's block reasons. Per document: party and person
consistency, and the person groups the reviewer would have to confirm.

Refuses any set whose role is not `development` (gate sets are never read).
Synthetic text only; it prints mention text to the developer's terminal and
writes nothing to logs, receipts or stored records. Rules-only masking: the
production pipeline (no locator).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.analyzer import injection, pii_mask  # noqa: E402
from app.services.analyzer import pii_evaluation as ev  # noqa: E402


def _tokens_over(masking, a: int, b: int) -> list[str]:
    return sorted({f"{tok}:{kind}" for x, y, kind, tok in masking.masked_spans if x < b and a < y})


def trace_document(doc: ev.Doc) -> dict:
    rows = ev._rows(doc.text)
    send_ids = {r["sentence_id"] for r in rows if not r.get("empty_value")
                and r["sentence_id"] not in injection.scan(doc.text, rows).sentence_ids}
    first = pii_mask.prepare(doc.text, rows, send_ids)
    decisions = ev.simulated_decisions(doc, mode="review")
    final = pii_mask.prepare(doc.text, rows, send_ids, decisions)
    scored = ev.score_document(doc, lambda m: "\n".join(x["content"] for x in m), mode="review")
    mentions = []
    for g in doc.spans:
        if g.kind != "NAME":
            continue
        crosses = sum(1 for r in rows if r["start"] < g.end and g.start < r["end"]) > 1
        decided = [d for d in decisions if d["start"] < g.end and g.start < d["end"]]
        mentions.append({"entity": g.entity, "party": g.entity in doc.parties, "start": g.start, "end": g.end,
                         "text": doc.text[g.start:g.end], "crosses_sentence": crosses,
                         "proposed": _tokens_over(first, g.start, g.end),
                         "decisions": [{k: d[k] for k in ("start", "end", "decision", "target_start", "target_end")
                                        if k in d} for d in decided],
                         "final": _tokens_over(final, g.start, g.end)})
    return {"id": doc.id, "sent": scored["sent"], "block_reasons": scored["block_reasons"],
            "party_consistent": scored["party_consistent"],
            "person_consistent": scored.get("person_consistent"),
            "people_to_confirm": scored.get("people_to_confirm"),
            "review_converged": scored.get("review_converged"),
            "leaks": sum(s["leak"] for s in scored["spans"]), "mentions": mentions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--doc")
    parser.add_argument("--json")
    args = parser.parse_args()
    if ev.DATASET_ROLES.get(args.dataset) != "development":
        print(f"refused: {args.dataset} is not a development set", file=sys.stderr)
        return 2
    traces = [trace_document(d) for d in ev.load_dataset(args.dataset).documents if args.doc in (None, d.id)]
    if args.json:
        Path(args.json).write_text(json.dumps(traces, indent=1, ensure_ascii=False), encoding="utf-8")
    for t in traces:
        bad = t["party_consistent"] is False or t["person_consistent"] is False or t["leaks"]
        print(f"{'!!' if bad else '  '} {t['id']}: sent={t['sent']} party={t['party_consistent']} "
              f"person={t['person_consistent']} leaks={t['leaks']} reasons={t['block_reasons']}")
        if bad or args.doc:
            for m in t["mentions"]:
                print(f"     {m['entity']:>4}{'*' if m['party'] else ' '} [{m['start']},{m['end']}) "
                      f"{m['text']!r}{' CROSSES' if m['crosses_sentence'] else ''} "
                      f"proposed={m['proposed']} final={m['final']} decisions={[d['decision'] for d in m['decisions']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
