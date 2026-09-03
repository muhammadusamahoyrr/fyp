"""Measure what case-derived query widening actually changes in retrieval.

Read-only: builds the retriever over the existing Chroma index and compares the
hits for the bare question against the hits for `augment_query(question, case)`.
No LLM call (the node's query-expansion step is skipped on purpose so the
measurement isolates the case supplement), no writes anywhere.
"""
import sys, json

sys.path.insert(0, ".")

from app.ai.case_context import augment_query, is_vague
from app.ai.pipelines.retriever import build_retriever
from app.db.chroma import connect_chroma

connect_chroma()   # read-only: opens the existing on-disk index

# Three representative matters, one per case_type the workspace actually uses.
CASES = [
    {"label": "civil / tenancy (punjab)",
     "ctx": {"case_type": "civil", "province": "punjab",
             "title": "Ali v. Landlord",
             "description": "Tenant evicted from a rented shop without notice."},
     "questions": ["What should I prepare?",
                   "What are the next steps?"]},
    {"label": "criminal / cheque dishonour",
     "ctx": {"case_type": "criminal", "province": "punjab",
             "title": "State v. Ahmed",
             "description": "Accused issued a dishonoured cheque for payment of a debt."},
     "questions": ["What should I prepare?",
                   "Any advice?"]},
    {"label": "family / custody",
     "ctx": {"case_type": "family", "province": "punjab",
             "title": "Fatima v. Bilal",
             "description": "Mother seeking custody of two minor children after divorce."},
     "questions": ["What should I prepare?",
                   "What do I do next?"]},
]

K = 8


def hits(query, case_type, province):
    r = build_retriever(case_type=case_type, province=province)
    docs = r.invoke(query)[:K]
    out = []
    for d in docs:
        m = d.metadata or {}
        out.append(f"{m.get('statute', '?')} s.{m.get('section_number', '?')}")
    return out


report = []
for case in CASES:
    ctx, ct, prov = case["ctx"], case["ctx"]["case_type"], case["ctx"]["province"]
    for q in case["questions"]:
        aug = augment_query(q, ctx)
        before = hits(q, ct, prov)
        after = hits(aug, ct, prov) if aug != q else before
        report.append({
            "case": case["label"], "question": q,
            "vague": is_vague(q), "widened": aug != q,
            "supplement": aug[len(q):].strip(),
            "before": before, "after": after,
            "changed": sum(1 for a, b in zip(before, after) if a != b),
            "new": [x for x in after if x not in before],
            "dropped": [x for x in before if x not in after],
        })

print(json.dumps(report, indent=1, ensure_ascii=False))
