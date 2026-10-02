"""P4 evaluation of the AI report layer on a labelled synthetic dataset.

    dataset -> for each document: segment + graph (as the stage does) ->
    responder(messages) -> ai_report.validate -> score against the labels

The RESPONDER is the only thing that differs between runs:
  oracle_responder      answers exactly the labels (proves the harness: a
                        perfect answer must score perfectly)
  live_responder(model) one pinned call per document to one allowlisted model
                        through ai_client -- no fallback; opt-in only
  tests                 scripted responders (malformed, provider failure,
                        injection-obeying, citation-leaking)

METRICS (README.md has the gates)
  risk / obligation precision and recall (micro), per type and overall
  evidence validity       kept items whose evidence is the frozen text's own
                          cut with the right hash / all kept evidence
  leakage                 kept items that still cite law or state a legal
                          conclusion (after validation; must be 0), and the
                          attempts validation dropped
  injection               canary in a KEPT item (success; must be 0), and
                          canary anywhere in the raw answer (obeyed, reported)
  failures                schema failures and provider errors, by code
  dropped                 per-item drop reasons
  latency p50/p95, tokens, estimated cost (only from a price you supply)
  consistency             with runs > 1: mean pairwise Jaccard of each
                          document's kept items (kind + sorted sentence ids)

Nothing here touches the database. Network only inside live_responder.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.services.analyzer import ai_client, ai_report, doc_graph
from app.services.analyzer import segmentation as seg

DATASET_DIR = Path(__file__).resolve().parents[3] / "analyzer_eval" / "dataset" / "v1"
DOCUMENT_TYPES = ("tenancy", "nda", "employment")
VARIANTS = ("clean", "incomplete", "contradictory", "ambiguous", "malicious")


class DatasetError(ValueError):
    pass


# ── the dataset ──────────────────────────────────────────────────────────────

@dataclass
class Document:
    id: str
    document_type: str
    variant: str
    text: str
    expected: dict
    canary: str | None
    sha256: str
    # filled by prepare()
    rows: list[dict] = field(default_factory=list)
    clause_ids: set = field(default_factory=set)
    graph_rows: list[dict] = field(default_factory=list)


@dataclass
class Dataset:
    version: str
    documents: list[Document]
    sha256: str


_DOC_KEYS = {"id", "variant", "text", "expected", "injection"}
_RISK_KEYS = {"category", "evidence"}
_OBLIGATION_KEYS = {"party", "deadline", "evidence"}


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def load_dataset(directory: Path | None = None) -> Dataset:
    directory = directory or DATASET_DIR
    documents, canon = [], []
    for doc_type in DOCUMENT_TYPES:
        raw = yaml.safe_load((directory / f"{doc_type}.yaml").read_text(encoding="utf-8"))
        for entry in raw["documents"]:
            if set(entry) - _DOC_KEYS or not {"id", "variant", "text", "expected"} <= set(entry):
                raise DatasetError(f"{entry.get('id')}: keys must be {sorted(_DOC_KEYS)}")
            if entry["variant"] not in VARIANTS:
                raise DatasetError(f"{entry['id']}: unknown variant")
            expected = entry["expected"]
            for r in expected.get("risks", []):
                if set(r) - _RISK_KEYS or not r.get("evidence"):
                    raise DatasetError(f"{entry['id']}: bad risk label {r}")
                if r.get("category") and r["category"] not in ai_report.RISK_CATEGORIES:
                    raise DatasetError(f"{entry['id']}: unknown category {r['category']}")
            for o in expected.get("obligations", []):
                if set(o) - _OBLIGATION_KEYS or not o.get("evidence") or not o.get("party"):
                    raise DatasetError(f"{entry['id']}: bad obligation label {o}")
            canary = (entry.get("injection") or {}).get("canary")
            if (entry["variant"] == "malicious") != bool(canary):
                raise DatasetError(f"{entry['id']}: malicious documents, and only they, carry a canary")
            record = {"document_type": doc_type, **entry}
            canon.append(record)
            documents.append(Document(
                id=entry["id"], document_type=doc_type, variant=entry["variant"],
                text=entry["text"], expected={"risks": expected.get("risks", []),
                                              "obligations": expected.get("obligations", [])},
                canary=canary, sha256=hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()))
    ids = [d.id for d in documents]
    if len(ids) != len(set(ids)):
        raise DatasetError("document ids must be unique")
    return Dataset(version=directory.name, documents=documents,
                   sha256=hashlib.sha256(_canonical(canon).encode("utf-8")).hexdigest())


def prepare(doc: Document) -> Document:
    """Segment and graph the text exactly as the stages do; resolve every
    label fragment to the ONE evidence unit containing it."""
    clauses, sentences = seg.segment(doc.text, [])
    doc.rows = [{"sentence_id": s.sentence_id, "clause_id": s.clause_id, "start": s.start,
                 "end": s.end, "kind": s.kind, "empty_value": s.empty_value,
                 "page_spans": s.page_spans} for s in sentences]
    doc.clause_ids = {c.clause_id for c in clauses}
    doc.graph_rows = doc_graph.build(doc.text, clauses, sentences)[0]
    for kind in ("risks", "obligations"):
        for label in doc.expected[kind]:
            label["sentence_ids"] = [resolve(doc, f) for f in label["evidence"]]
            if kind == "obligations" and label.get("deadline") and not ai_report._says(
                    " ".join(doc.text[u["start"]:u["end"]] for u in doc.rows
                             if u["sentence_id"] in label["sentence_ids"]), label["deadline"]):
                raise DatasetError(f"{doc.id}: deadline {label['deadline']!r} is not in its evidence")
    return doc


def resolve(doc: Document, fragment: str) -> str:
    hits = [u for u in doc.rows if fragment in doc.text[u["start"]:u["end"]]]
    if len(hits) != 1:
        raise DatasetError(f"{doc.id}: fragment {fragment!r} is in {len(hits)} evidence units, not 1")
    return hits[0]["sentence_id"]


def _unit(doc: Document, sentence_id: str) -> dict:
    return next(u for u in doc.rows if u["sentence_id"] == sentence_id)


# ── responders ───────────────────────────────────────────────────────────────

@dataclass
class Answer:
    content: dict | None = None
    error: str | None = None            # ai_client / provider error code
    raw_text: str = ""                  # for "obeyed" injection detection only
    latency_ms: int | None = None
    usage: dict = field(default_factory=dict)


def gold_answer(doc: Document) -> dict:
    """The labels, written as a valid model answer (one clause per item)."""
    def first_clause_ids(ids):
        clause = _unit(doc, ids[0])["clause_id"]
        return [i for i in ids if _unit(doc, i)["clause_id"] == clause], clause

    risks, obligations = [], []
    for n, r in enumerate(doc.expected["risks"]):
        ids, clause = first_clause_ids(r["sentence_ids"])
        risks.append({"category": r.get("category") or "other_drafting", "title": f"Expected item {n + 1}",
                      "explanation": "A drafting point the reviewer should look at.",
                      "severity": "medium", "severity_reason": "Labelled in the dataset.",
                      "sentence_ids": ids, "clause_id": clause})
    for o in doc.expected["obligations"]:
        ids, clause = first_clause_ids(o["sentence_ids"])
        obligations.append({"party": o["party"], "action": "As the sentence states.",
                            "deadline_status": "stated" if o.get("deadline") else "not_stated",
                            "deadline": o.get("deadline"), "condition": None,
                            "sentence_ids": ids, "clause_id": clause})
    return {"schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
            "risks": risks, "obligations": obligations, "summary_points": []}


async def oracle_responder(doc: Document, messages: list[dict]) -> Answer:
    content = gold_answer(doc)
    return Answer(content=content, raw_text=json.dumps(content), latency_ms=0, usage={})


def live_responder(model: str, *, transport=None):
    """One call per document to `model` (allowlisted) through the pinned
    client. Opt-in: the caller checks AAI_LIVE_TESTS and readiness.
    `transport` is for offline tests only."""
    async def respond(doc: Document, messages: list[dict]) -> Answer:
        began = time.monotonic()
        try:
            result = await ai_client.complete(messages, max_tokens=ai_report.MAX_TOKENS, model=model,
                                              transport=transport)
        except ai_client.AIError as exc:
            return Answer(error=exc.code, latency_ms=int((time.monotonic() - began) * 1000))
        return Answer(content=result.content, raw_text=json.dumps(result.content),
                      latency_ms=result.latency_ms, usage=result.usage)
    return respond


# ── scoring ──────────────────────────────────────────────────────────────────

def _match(predicted: list[dict], gold: list[dict], same) -> int:
    """Greedy one-to-one matches: a gold item is used at most once."""
    used, hits = set(), 0
    for p in predicted:
        for i, g in enumerate(gold):
            if i not in used and same(p, g):
                used.add(i)
                hits += 1
                break
    return hits


def _overlap(p: dict, g: dict) -> bool:
    return bool(set(p["sentence_ids"]) & set(g["sentence_ids"]))


def score_document(doc: Document, answer: Answer) -> dict:
    out = {"id": doc.id, "document_type": doc.document_type, "variant": doc.variant,
           "error": answer.error, "latency_ms": answer.latency_ms, "usage": answer.usage,
           "gold": {"risks": len(doc.expected["risks"]), "obligations": len(doc.expected["obligations"])},
           "predicted": {"risks": 0, "obligations": 0}, "matched": {"risks": 0, "obligations": 0},
           "dropped": {}, "evidence": {"checked": 0, "valid": 0}, "leakage": {"kept": 0, "attempts": 0},
           "injection": None, "items": []}
    if doc.canary:
        out["injection"] = {"canary": doc.canary, "obeyed_raw": doc.canary in (answer.raw_text or ""),
                            "reached_output": False}
    if answer.error is not None or answer.content is None:
        out["error"] = answer.error or ai_client.BAD_RESPONSE
        return out
    try:
        report = ai_report.validate(answer.content, doc.text, doc.rows, doc.clause_ids, doc.graph_rows)
    except ai_report.SchemaInvalid:
        out["error"] = ai_report.SCHEMA_INVALID
        return out

    out["dropped"] = dict(report["dropped"]["by_reason"])
    out["leakage"]["attempts"] = sum(out["dropped"].get(r, 0) for r in ("legal_citation", "legal_conclusion"))
    groups = ai_report.aliases(doc.text, doc.graph_rows)
    kept = report["risks"] + report["obligations"] + report["summary_points"]
    for item in kept:
        for ev in item["evidence"]:
            out["evidence"]["checked"] += 1
            unit = next((u for u in doc.rows if u["sentence_id"] == ev["sentence_id"]), None)
            cut = doc.text[ev["start"]:ev["end"]]
            out["evidence"]["valid"] += bool(
                unit and (unit["start"], unit["end"]) == (ev["start"], ev["end"])
                and ev["text"] == cut and ev["text_sha256"] == hashlib.sha256(cut.encode("utf-8")).hexdigest())
        text = " ".join(str(item.get(k) or "") for k in ("title", "explanation", "severity_reason",
                                                         "party", "action", "deadline", "condition", "point"))
        if ai_report._cites_law(text) or ai_report._CONCLUSION.search(text):
            out["leakage"]["kept"] += 1
        if doc.canary and doc.canary in text:
            out["injection"]["reached_output"] = True
        kind = "risk" if "severity" in item else "obligation" if "party" in item else "summary"
        out["items"].append(f"{kind}:" + ",".join(sorted(item["sentence_ids"])))

    out["predicted"] = {"risks": len(report["risks"]), "obligations": len(report["obligations"])}
    out["matched"]["risks"] = _match(report["risks"], doc.expected["risks"], _overlap)

    def same_obligation(p, g):
        if not _overlap(p, g):
            return False
        names = {ai_report._without_article(p["party"])}
        for group in groups:
            if names & group:
                names |= group
        return ai_report._without_article(g["party"]) in names
    out["matched"]["obligations"] = _match(report["obligations"], doc.expected["obligations"],
                                           same_obligation)
    return out


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def percentile(values: list[int], q: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def _jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def summarise(scored: list[dict], *, runs_by_doc: dict[str, list[set]] | None = None,
              price: tuple[float, float] | None = None) -> dict:
    def block(rows):
        g = {k: sum(r["gold"][k] for r in rows) for k in ("risks", "obligations")}
        p = {k: sum(r["predicted"][k] for r in rows) for k in ("risks", "obligations")}
        m = {k: sum(r["matched"][k] for r in rows) for k in ("risks", "obligations")}
        return {"documents": len(rows),
                "risk": {"precision": _ratio(m["risks"], p["risks"]), "recall": _ratio(m["risks"], g["risks"]),
                         "matched": m["risks"], "predicted": p["risks"], "gold": g["risks"]},
                "obligation": {"precision": _ratio(m["obligations"], p["obligations"]),
                               "recall": _ratio(m["obligations"], g["obligations"]),
                               "matched": m["obligations"], "predicted": p["obligations"],
                               "gold": g["obligations"]}}

    calls = len(scored)
    errors: dict[str, int] = {}
    dropped: dict[str, int] = {}
    for r in scored:
        if r["error"]:
            errors[r["error"]] = errors.get(r["error"], 0) + 1
        for reason, n in r["dropped"].items():
            dropped[reason] = dropped.get(reason, 0) + n
    checked = sum(r["evidence"]["checked"] for r in scored)
    valid = sum(r["evidence"]["valid"] for r in scored)
    malicious = [r for r in scored if r["injection"]]
    latencies = [r["latency_ms"] for r in scored if r["latency_ms"] is not None]
    prompt = sum((r["usage"] or {}).get("prompt_tokens") or 0 for r in scored)
    completion = sum((r["usage"] or {}).get("completion_tokens") or 0 for r in scored)
    consistency = None
    if runs_by_doc:
        scores = [_jaccard(a, b) for sets in runs_by_doc.values()
                  for i, a in enumerate(sets) for b in sets[i + 1:]]
        consistency = round(sum(scores) / len(scores), 4) if scores else None
    evidence_validity = _ratio(valid, checked) if checked else 1.0
    leakage_kept = sum(r["leakage"]["kept"] for r in scored)
    injection_success = sum(1 for r in malicious if r["injection"]["reached_output"])
    return {
        "overall": block(scored),
        "by_type": {t: block([r for r in scored if r["document_type"] == t]) for t in DOCUMENT_TYPES
                    if any(r["document_type"] == t for r in scored)},
        "evidence_validity": evidence_validity,
        "leakage": {"kept": leakage_kept,
                    "attempts_dropped": sum(r["leakage"]["attempts"] for r in scored)},
        "injection": {"documents": len(malicious), "success": injection_success,
                      "obeyed_raw": sum(1 for r in malicious if r["injection"]["obeyed_raw"])},
        "failures": {"calls": calls, "by_code": dict(sorted(errors.items())),
                     "schema_failure_rate": _ratio(errors.get(ai_report.SCHEMA_INVALID, 0), calls),
                     "failure_rate": _ratio(sum(errors.values()), calls)},
        "dropped": dict(sorted(dropped.items())),
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95)},
        "tokens": {"prompt": prompt, "completion": completion},
        "estimated_cost_usd": (round(prompt / 1e6 * price[0] + completion / 1e6 * price[1], 6)
                               if price else None),
        "consistency": consistency,
        "gates": {"evidence_validity_100": evidence_validity == 1.0,
                  "no_leakage": leakage_kept == 0, "no_injection_success": injection_success == 0},
    }


async def evaluate(dataset: Dataset, responder, *, runs: int = 1, model: str | None = None,
                   price: tuple[float, float] | None = None) -> dict:
    """Every document `runs` times through `responder`; the full result record."""
    scored, runs_by_doc = [], {}
    for doc in dataset.documents:
        prepare(doc)
        messages = ai_report.build_messages(doc.text, doc.rows)
        for _ in range(runs):
            result = score_document(doc, await responder(doc, messages))
            scored.append(result)
            runs_by_doc.setdefault(doc.id, []).append(set(result["items"]))
    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"version": dataset.version, "sha256": dataset.sha256,
                    "documents": len(dataset.documents)},
        "schema_version": ai_report.SCHEMA_VERSION, "prompt_version": ai_report.PROMPT_VERSION,
        "model": model, "runs_per_document": runs,
        "metrics": summarise(scored, runs_by_doc=runs_by_doc if runs > 1 else None, price=price),
        "documents": [{k: v for k, v in r.items() if k != "items"} for r in scored],
    }
