"""PII masking DETECTION evaluation (`pii-eval.1`, analyzer_eval/pii/PII_DETECTION_RUBRIC.md).

Scores the masker (`pii-mask.1`) on synthetic documents whose personal
details are marked inline (`[[NAME:p1|Kashif Raza]]`). Everything follows
the rubric, which was frozen before the first scored run:

  * two modes, reported apart:
      auto   -- masking alone; anything uncertain BLOCKS the document;
      manual -- a reviewer confirms each uncertain span by the gold labels;
  * per gold span: character coverage (half a name is not a success),
    detected (fully masked), detection miss (neither masked nor flagged),
    transmission leak (only in a document actually SENT);
  * per document: blocked, unnecessary block, false candidates;
  * meaning: party-token consistency, deadline preservation;
  * request hygiene: the CAPTURED provider request never carries a mark, an
    entity id or a label.

The request is captured by `send(messages) -> str`: the script passes one
that goes through the real provider client with a capturing fake transport,
so what is inspected is the actual HTTP request body. No live call, ever.

A pass is `detection_passed` at most -- never real-document or model-quality
approval.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.services.analyzer import ai_report, injection, pii_mask
from app.services.analyzer import segmentation as seg

EVAL_VERSION = "pii-eval.1"
ROOT = Path(__file__).resolve().parents[3] / "analyzer_eval" / "pii"
RUBRIC_PATH = ROOT / "PII_DETECTION_RUBRIC.md"
RECORD_PATH = Path(__file__).resolve().parent / "pii_detection_record.yaml"
PERSONAL = ("NAME", "CNIC", "PHONE", "EMAIL", "ACCOUNT", "ADDRESS")
KINDS = PERSONAL + ("NOT", "DEADLINE")
FEATURES = ("repeated_names", "aliases", "urdu_script", "roman_urdu", "ocr_errors", "table", "overlap",
            "untitled_names", "lookalikes", "deadlines")
#: The rubric's thresholds (frozen before the first scored run).
THRESHOLDS = {
    "auto_leaks": 0, "manual_leaks": 0,
    "auto_character_coverage": 0.95, "auto_detected_rate": 0.85, "auto_miss_rate": 0.05,
    "unnecessary_block_rate": 0.15, "false_candidate_rate": 0.30,
    "party_consistency": 1.0, "deadline_preservation": 1.0, "request_hygiene": 1.0,
}
COVERAGE = {"documents": 40, "per_feature": 6, "personal_spans": 150}
_OPEN = re.compile(r"\[\[(?P<kind>[A-Z]+):(?P<entity>[A-Za-z0-9_-]+)\|")
_WORD = re.compile(r"[^\W_]{3,}|\d{3,}", re.UNICODE)


class DatasetError(ValueError):
    pass


@dataclass
class Span:
    kind: str
    entity: str
    start: int
    end: int


@dataclass
class Doc:
    id: str
    document_type: str
    features: list[str]
    parties: list[str]
    text: str
    spans: list[Span] = field(default_factory=list)


def parse_marks(marked: str) -> tuple[str, list[Span]]:
    """Plain text and gold spans (offsets into the plain text). Only NAME
    may sit inside ADDRESS, one level deep."""
    out: list[str] = []
    spans: list[Span] = []
    stack: list[tuple[str, str, int]] = []
    i, length = 0, 0
    while i < len(marked):
        m = _OPEN.match(marked, i)
        if m:
            kind = m.group("kind")
            if kind not in KINDS:
                raise DatasetError(f"unknown kind {kind!r}")
            if stack and not (stack[-1][0] == "ADDRESS" and kind == "NAME" and len(stack) == 1):
                raise DatasetError(f"{kind} cannot sit inside {stack[-1][0]}")
            stack.append((kind, m.group("entity"), length))
            i = m.end()
            continue
        if marked.startswith("]]", i) and stack:
            kind, entity, start = stack.pop()
            if length == start:
                raise DatasetError(f"empty {kind} mark")
            spans.append(Span(kind, entity, start, length))
            i += 2
            continue
        out.append(marked[i])
        length += 1
        i += 1
    if stack:
        raise DatasetError("unclosed mark")
    return "".join(out), sorted(spans, key=lambda s: (s.start, -s.end))


@dataclass
class Dataset:
    name: str
    documents: list[Doc]
    sha256: str


def load_dataset(name: str, root: Path | None = None) -> Dataset:
    directory = (root or ROOT) / name
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise DatasetError(f"{name}: no dataset files")
    docs, canon = [], []
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"dataset", "label_review", "documents"}:
            raise DatasetError(f"{path.name}: keys must be dataset, label_review, documents")
        if data["dataset"] != name or data["label_review"] != "developer_only":
            raise DatasetError(f"{path.name}: dataset name or label_review is wrong")
        for entry in data["documents"]:
            if set(entry) != {"id", "document_type", "features", "parties", "text"}:
                raise DatasetError(f"{entry.get('id')}: bad keys")
            if unknown := set(entry["features"]) - set(FEATURES):
                raise DatasetError(f"{entry['id']}: unknown features {sorted(unknown)}")
            text, spans = parse_marks(entry["text"])
            names = {s.entity for s in spans if s.kind == "NAME"}
            if missing := set(entry["parties"]) - names:
                raise DatasetError(f"{entry['id']}: parties without a NAME mark {sorted(missing)}")
            docs.append(Doc(entry["id"], entry["document_type"], list(entry["features"]), list(entry["parties"]),
                            text, spans))
            canon.append(entry)
    ids = [d.id for d in docs]
    if len(ids) != len(set(ids)):
        raise DatasetError("document ids must be unique")
    digest = hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return Dataset(name, docs, digest)


def coverage(dataset: Dataset) -> dict:
    per_feature = {f: sum(f in d.features for d in dataset.documents) for f in FEATURES}
    personal = sum(s.kind in PERSONAL for d in dataset.documents for s in d.spans)
    short = sorted(f for f, n in per_feature.items() if n < COVERAGE["per_feature"])
    ok = (len(dataset.documents) >= COVERAGE["documents"] and not short and personal >= COVERAGE["personal_spans"])
    return {"documents": len(dataset.documents), "per_feature": per_feature, "personal_spans": personal,
            "features_short": short, "met": ok}


# ── scoring one document ────────────────────────────────────────────────────

def _rows(text: str) -> list[dict]:
    _, sentences = seg.segment(text, [])
    return [{"sentence_id": s.sentence_id, "clause_id": s.clause_id, "start": s.start, "end": s.end,
             "kind": s.kind, "empty_value": s.empty_value} for s in sentences]


def _covered(masked_spans, start: int, end: int) -> int:
    return sum(max(0, min(b, end) - max(a, start)) for a, b, _, _ in masked_spans)


def _overlaps(a1: int, b1: int, a2: int, b2: int) -> bool:
    return a1 < b2 and a2 < b1


def _norm(s: str) -> str:
    return " ".join(s.split())


def _oracle(uncertain: list[dict], gold: list[Span]) -> list[dict]:
    """The manual mode's reviewer: decides each uncertain span by the labels."""
    out = []
    for u in uncertain:
        hit = [g for g in gold if g.kind in PERSONAL and _overlaps(u["start"], u["end"], g.start, g.end)]
        decision = (pii_mask.NAME_DECISION if any(g.kind == "NAME" for g in hit)
                    else pii_mask.ADDRESS_DECISION if hit else pii_mask.NOT_PERSONAL)
        out.append({"start": u["start"], "end": u["end"], "decision": decision})
    return out


def _hygiene(request: str, doc: Doc) -> bool:
    if "[[" in request or re.search(r"\b(?:NAME|CNIC|PHONE|EMAIL|ACCOUNT|ADDRESS|NOT|DEADLINE):[A-Za-z0-9_-]+\|", request):
        return False
    return "PII_DETECTION_RUBRIC" not in request and "pii-eval" not in request


def score_document(doc: Doc, send, *, mode: str) -> dict:
    """`send(messages) -> str`: the captured provider request body (text)."""
    rows = _rows(doc.text)
    scan = injection.scan(doc.text, rows)
    suspect = scan.sentence_ids
    send_ids = {r["sentence_id"] for r in rows if not r.get("empty_value") and r["sentence_id"] not in suspect}
    in_request = [r for r in rows if r["sentence_id"] in send_ids]
    gold = [g for g in doc.spans if any(r["start"] <= g.start and g.end <= r["end"] for r in in_request)]
    personal = [g for g in gold if g.kind in PERSONAL]

    first = pii_mask.prepare(doc.text, rows, send_ids)
    uncertain = list(first.uncertain)
    masking = first
    if mode == "manual" and uncertain:
        masking = pii_mask.prepare(doc.text, rows, send_ids, _oracle(uncertain, doc.spans))
    blocked = bool(masking.uncertain)

    request = None
    if not blocked:
        messages = ai_report.build_messages(doc.text, rows, suspect, masking.bodies)
        request = send(messages)

    spans_out = []
    for g in personal:
        covered = _covered(masking.masked_spans, g.start, g.end)
        size = g.end - g.start
        flagged = any(_overlaps(u["start"], u["end"], g.start, g.end) for u in uncertain)
        leaked = False
        if request is not None and covered < size:
            # The span's OWN unmasked characters, in its own sentence's line of the captured request.
            unmasked = "".join(ch if not any(a <= g.start + k < b for a, b, _, _ in masking.masked_spans) else " "
                               for k, ch in enumerate(doc.text[g.start:g.end]))
            sid = next(r["sentence_id"] for r in in_request if r["start"] <= g.start and g.end <= r["end"])
            body = _norm(masking.bodies[sid])
            leaked = any(w in body for w in _WORD.findall(unmasked)) and body[:60] in _norm(request)
        spans_out.append({"kind": g.kind, "entity": g.entity, "size": size, "covered": covered,
                          "detected": covered == size, "flagged": flagged,
                          "miss": covered < size and not flagged, "leak": leaked})

    false_candidates = [u for u in uncertain
                        if not any(g.kind in PERSONAL and _overlaps(u["start"], u["end"], g.start, g.end)
                                   for g in doc.spans)]
    unnecessary_block = bool(first.uncertain) and len(false_candidates) == len(uncertain) and mode == "auto"

    # Meaning: one token per party entity, distinct across entities (fully masked mentions only).
    tokens: dict[str, set[str]] = {}
    for g in personal:
        if g.kind == "NAME" and g.entity in doc.parties:
            for a, b, _, tok in masking.masked_spans:
                if a <= g.start and g.end <= b:
                    tokens.setdefault(g.entity, set()).add(tok)
    consistent = all(len(v) == 1 for v in tokens.values()) and \
        len(set().union(*tokens.values()) if tokens else set()) == len(tokens)
    deadlines = [g for g in gold if g.kind == "DEADLINE"]
    preserved = (all(_norm(doc.text[g.start:g.end]) in _norm(request) for g in deadlines)
                 if request is not None else None)
    return {"id": doc.id, "mode": mode, "blocked": blocked, "sent": request is not None,
            "uncertain": len(uncertain), "false_candidates": len(false_candidates),
            "unnecessary_block": unnecessary_block, "spans": spans_out,
            "party_consistent": consistent if tokens else None,
            "deadlines_preserved": preserved, "deadline_count": len(deadlines),
            "hygiene": _hygiene(request, doc) if request is not None else None}


# ── the whole set ───────────────────────────────────────────────────────────

def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def summarise(results: list[dict]) -> dict:
    spans = [s for r in results for s in r["spans"]]
    size = sum(s["size"] for s in spans)
    party = [r["party_consistent"] for r in results if r["party_consistent"] is not None]
    dl = [r for r in results if r["deadlines_preserved"] is not None and r["deadline_count"]]
    hyg = [r["hygiene"] for r in results if r["hygiene"] is not None]
    cands = sum(r["uncertain"] for r in results)
    return {
        "documents": len(results), "sent": sum(r["sent"] for r in results),
        "blocked": sum(r["blocked"] for r in results),
        "personal_spans": len(spans),
        "character_coverage": _ratio(sum(s["covered"] for s in spans), size),
        "detected_rate": _ratio(sum(s["detected"] for s in spans), len(spans)),
        "miss_rate": _ratio(sum(s["miss"] for s in spans), len(spans)),
        "flagged_spans": sum(s["flagged"] for s in spans),
        "leaks": sum(s["leak"] for s in spans),
        "unnecessary_blocks": sum(r["unnecessary_block"] for r in results),
        "unnecessary_block_rate": _ratio(sum(r["unnecessary_block"] for r in results), len(results)),
        "uncertain_spans": cands,
        "false_candidate_rate": _ratio(sum(r["false_candidates"] for r in results), cands),
        "party_consistency": _ratio(sum(party), len(party)),
        "deadline_preservation": _ratio(sum(r["deadlines_preserved"] for r in dl), len(dl)),
        "request_hygiene": _ratio(sum(hyg), len(hyg)),
        "by_kind": {k: {"spans": sum(s["kind"] == k for s in spans),
                        "detected": sum(s["kind"] == k and s["detected"] for s in spans),
                        "missed": sum(s["kind"] == k and s["miss"] for s in spans),
                        "leaked": sum(s["kind"] == k and s["leak"] for s in spans)} for k in PERSONAL},
    }


def gate(auto: dict, manual: dict) -> dict:
    checks = {
        "auto_leaks": auto["leaks"] <= THRESHOLDS["auto_leaks"],
        "manual_leaks": manual["leaks"] <= THRESHOLDS["manual_leaks"],
        "auto_character_coverage": (auto["character_coverage"] or 0) >= THRESHOLDS["auto_character_coverage"],
        "auto_detected_rate": (auto["detected_rate"] or 0) >= THRESHOLDS["auto_detected_rate"],
        "auto_miss_rate": (auto["miss_rate"] if auto["miss_rate"] is not None else 1) <= THRESHOLDS["auto_miss_rate"],
        "unnecessary_block_rate": (auto["unnecessary_block_rate"] or 0) <= THRESHOLDS["unnecessary_block_rate"],
        "false_candidate_rate": (auto["false_candidate_rate"] or 0) <= THRESHOLDS["false_candidate_rate"],
        "party_consistency": all((x["party_consistency"] if x["party_consistency"] is not None else 1)
                                 >= THRESHOLDS["party_consistency"] for x in (auto, manual)),
        "deadline_preservation": all((x["deadline_preservation"] if x["deadline_preservation"] is not None else 1)
                                     >= THRESHOLDS["deadline_preservation"] for x in (auto, manual)),
        "request_hygiene": all((x["request_hygiene"] if x["request_hygiene"] is not None else 1)
                               >= THRESHOLDS["request_hygiene"] for x in (auto, manual)),
    }
    return {"thresholds": THRESHOLDS, "checks": checks,
            "status": "detection_passed" if all(checks.values()) else "not_passed"}


def evaluate(dataset: Dataset, send) -> dict:
    out = {"eval_version": EVAL_VERSION, "dataset": dataset.name, "dataset_sha256": dataset.sha256,
           "masking_version": pii_mask.MASKING_VERSION, "policy_sha256": pii_mask.POLICY_SHA256,
           "rubric_sha256": hashlib.sha256(RUBRIC_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
           "coverage": coverage(dataset)}
    per = {mode: [score_document(d, send, mode=mode) for d in dataset.documents] for mode in ("auto", "manual")}
    out["auto"], out["manual"] = summarise(per["auto"]), summarise(per["manual"])
    out["gate"] = gate(out["auto"], out["manual"])
    out["per_document"] = per
    return out
