"""PII masking DETECTION evaluation (`pii-eval.2`; rubric 2 = analyzer_eval/pii/PII_DETECTION_RUBRIC_2.md,
rubric 1 = PII_DETECTION_RUBRIC.md, kept unchanged for pii-eval-1).

Scores the masker (`pii-mask.2`) on synthetic documents whose personal
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

Harness corrections in pii-eval.1.1 (2026-10-04, labelled; the pii-eval.1
baseline record stays as recorded):
  * party consistency is scored only on documents actually SENT -- the
    rubric's "in what is sent"; pii-eval.1 also scored blocked documents;
  * the L6 leak guard (`pii_mask.leak_check`) runs on the final request, as
    the stages do: a hit BLOCKS the document before anything is sent;
  * every blocked document carries its reasons; blocking is reported per
    reason, apart from leaks, with the documents a block cost needlessly;
  * a locator's spans are passed as DETECTIONS: pii-eval.1 passed them as
    reviewer confirmations, so they also silenced every uncertainty they
    overlapped (this affected the 2026-10-04 locator benchmark);
  * pii-eval.2 (rubric 2, owner-decided 2026-10-04): party consistency is
    scored on person-name references (a name inside an address under the
    address token is not a split); the pii-eval.1 definition is reported
    alongside as `party_consistency_any_token`; address character coverage
    and the sent rate are reported as their own metrics;
  * the manual reviewer links an undefined alias to its person
    (`same_person`), never a policy block (Urdu script).

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

EVAL_VERSION = "pii-eval.2"
ROOT = Path(__file__).resolve().parents[3] / "analyzer_eval" / "pii"
RUBRIC_PATH = ROOT / "PII_DETECTION_RUBRIC.md"          # pii-eval.1, kept unchanged (its hash is frozen)
RUBRIC_2_PATH = ROOT / "PII_DETECTION_RUBRIC_2.md"
RUBRIC_3_PATH = ROOT / "PII_DETECTION_RUBRIC_3.md"
#: The rubric each set is scored under; pii-eval-2 and later use rubric 2.
RUBRIC_BY_DATASET = {"pii-eval-1": RUBRIC_PATH, "pii-eval-3": RUBRIC_3_PATH, "pii-eval-4": RUBRIC_3_PATH}


def rubric_path(dataset_name: str) -> Path:
    return RUBRIC_BY_DATASET.get(dataset_name, RUBRIC_2_PATH)


def rubric_number(dataset_name: str) -> int:
    return {RUBRIC_PATH: 1, RUBRIC_3_PATH: 3}.get(rubric_path(dataset_name), 2)


def modes_for(dataset_name: str) -> tuple[str, ...]:
    """Rubric 3 adds the `review` (lawyer-confirm) mode beside auto and flag-only."""
    return ("auto", "manual", "review") if rubric_number(dataset_name) == 3 else ("auto", "manual")
RECORD_PATH = Path(__file__).resolve().parent / "pii_detection_record.yaml"   # pii-eval-1's kept record


def record_path(dataset_name: str) -> Path:
    """Each gate set keeps its own record; pii-eval-1's stays where it was."""
    if dataset_name == "pii-eval-1":
        return RECORD_PATH
    return Path(__file__).resolve().parent / f"pii_detection_record_{dataset_name.replace('-', '_')}.yaml"
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
#: pii-eval-1 became a DEVELOPMENT set on 2026-10-04, at the first tuning step
#: (the local entity-locator benchmark). Its failed baseline -- 194 leaks in
#: auto mode -- stays kept, unchanged, in pii_detection_record.yaml (7424f38).
#: The next gate is a fresh independent pii-eval-2.
DATASET_ROLES = {"pii-eval-1": "development",
                 "pii-eval-2": "gate_spent",       # scored once 2026-10-04: NOT passed
                 "pii-eval-3": "gate_spent",       # scored once 2026-10-04 (b907a96): NOT passed
                 "pii-eval-4": "gate_sealed"}     # authored 2026-10-04; never read for tuning; see AUTHORED.txt
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
        if u["kind"] in pii_mask.UNRESOLVABLE:
            continue                                   # a policy block: no reviewer decision lifts it
        hit = [g for g in gold if g.kind in PERSONAL and _overlaps(u["start"], u["end"], g.start, g.end)]
        if u["reason"] in ("alias_unlinked", "name_variant", "ocr_unmasked"):
            # The reviewer links the mention to the same person's fullest OTHER mention.
            names = [g for g in hit if g.kind == "NAME"]
            same = [g for g in gold if names and g.kind == "NAME" and g.entity == names[0].entity
                    and not _overlaps(u["start"], u["end"], g.start, g.end)
                    and g.end - g.start >= u["end"] - u["start"]]
            if same:
                target = max(same, key=lambda g: g.end - g.start)
                out.append({"start": u["start"], "end": u["end"], "decision": pii_mask.SAME_PERSON,
                            "target_start": target.start, "target_end": target.end})
                continue
        decision = (pii_mask.NAME_DECISION if any(g.kind == "NAME" for g in hit)
                    else pii_mask.ADDRESS_DECISION if hit else pii_mask.NOT_PERSONAL)
        out.append({"start": u["start"], "end": u["end"], "decision": decision})
    return out


_KIND_DECISION = {"NAME": pii_mask.NAME_DECISION, "ADDRESS": pii_mask.ADDRESS_DECISION,
                  **{kind: decision for decision, kind in pii_mask.KIND_DECISIONS.items()}}


def _missed(doc: Doc, personal: list[Span], masking, decisions: list[dict]) -> list[dict]:
    """`review` mode: the gold personal details still not fully masked, as the
    reviewer would mark them -- the outermost span only; a person's other
    mention linked to their fullest masked mention (`same person`)."""
    out: list[dict] = []
    for g in sorted(personal, key=lambda g: (g.start, -(g.end - g.start))):
        if _covered(masking.masked_spans, g.start, g.end) >= g.end - g.start:
            continue
        if any(o["start"] <= g.start and g.end <= o["end"] for o in out):
            continue                                         # inside a span already marked
        mark = {"start": g.start, "end": g.end, "decision": _KIND_DECISION[g.kind]}
        if g.kind == "NAME":
            # The person's fullest mention that is masked already, or that this
            # reviewer marked earlier in the same pass (the screen offers both).
            marked_here = [(o["start"], o["end"]) for o in out if o["decision"] == pii_mask.NAME_DECISION]
            same = [x for x in doc.spans if x.kind == "NAME" and x.entity == g.entity and x is not g
                    and not _overlaps(x.start, x.end, g.start, g.end) and x.end - x.start >= g.end - g.start
                    and (_covered(masking.masked_spans, x.start, x.end) == x.end - x.start
                         or (x.start, x.end) in marked_here)]
            if same:
                target = max(same, key=lambda x: x.end - x.start)
                mark.update(decision=pii_mask.SAME_PERSON, target_start=target.start, target_end=target.end)
        out.append(mark)
    return out


def _hygiene(request: str, doc: Doc) -> bool:
    if "[[" in request or re.search(r"\b(?:NAME|CNIC|PHONE|EMAIL|ACCOUNT|ADDRESS|NOT|DEADLINE):[A-Za-z0-9_-]+\|", request):
        return False
    return "PII_DETECTION_RUBRIC" not in request and "pii-eval" not in request


def score_document(doc: Doc, send, *, mode: str, extra: list[dict] | None = None) -> dict:
    """`send(messages) -> str`: the captured provider request body (text).
    `extra`: spans a development locator proposes, as `[{start, end, decision}]`
    (personal_name / address) -- masked like confirmed spans. None = the masker alone."""
    rows = _rows(doc.text)
    scan = injection.scan(doc.text, rows)
    suspect = scan.sentence_ids
    send_ids = {r["sentence_id"] for r in rows if not r.get("empty_value") and r["sentence_id"] not in suspect}
    in_request = [r for r in rows if r["sentence_id"] in send_ids]
    gold = [g for g in doc.spans if any(r["start"] <= g.start and g.end <= r["end"] for r in in_request)]
    personal = [g for g in gold if g.kind in PERSONAL]

    # Locator spans are DETECTIONS, never reviewer confirmations: they mask, and
    # resolve no uncertainty (pii-eval.1 passed them as confirmations).
    first = pii_mask.prepare(doc.text, rows, send_ids, None, list(extra or []))
    uncertain = list(first.uncertain)
    masking = first
    marked = 0
    if mode in ("manual", "review") and (uncertain or mode == "review"):
        # The reviewer sees the re-masked document again: a flag that appears
        # only after their decisions is decided too (at most three rounds).
        # In `review` mode (lawyer-confirm, rubric 3) the reviewer ALSO marks
        # every personal detail masking missed without flagging it. That
        # simulates a reviewer who catches everything: it tests the MECHANISM
        # (marked details are masked, never sent, one token per person), not
        # whether a real lawyer would catch them -- `reviewer_marked` reports
        # how much was left to the lawyer.
        decisions: list[dict] = []
        for _ in range(3):
            fresh = [u for u in masking.uncertain
                     if not any(c["start"] == u["start"] and c["end"] == u["end"] for c in decisions)]
            added: list[dict] = []
            if mode == "review":
                added = _missed(doc, personal, masking, decisions)
            if not fresh and not added:
                break
            decisions += _oracle(fresh, doc.spans)
            for a in added:
                decisions = [c for c in decisions if not (c["start"] < a["end"] and a["start"] < c["end"])] + [a]
            marked += len(added)
            masking = pii_mask.prepare(doc.text, rows, send_ids, decisions, list(extra or []))
    reasons = sorted({u["reason"] for u in masking.uncertain})
    guard: list[str] = []
    request = None
    if not reasons:
        messages = ai_report.build_messages(doc.text, rows, suspect, masking.bodies)
        guard = pii_mask.leak_check(messages)
        if guard:
            reasons = [f"leak_guard:{c}" for c in guard]
        else:
            request = send(messages)
    blocked = bool(reasons)

    spans_out = []
    for g in personal:
        covered = _covered(masking.masked_spans, g.start, g.end)
        size = g.end - g.start
        flagged = any(_overlaps(u["start"], u["end"], g.start, g.end) for u in uncertain)
        leaked = would_leak = False
        if covered < size and not masking.uncertain:
            # The span's OWN unmasked characters, in its own sentence's line of the captured request.
            unmasked = "".join(ch if not any(a <= g.start + k < b for a, b, _, _ in masking.masked_spans) else " "
                               for k, ch in enumerate(doc.text[g.start:g.end]))
            sid = next(r["sentence_id"] for r in in_request if r["start"] <= g.start and g.end <= r["end"])
            body = _norm(masking.bodies[sid])
            would_leak = any(w in body for w in _WORD.findall(unmasked))
            leaked = would_leak and request is not None and body[:60] in _norm(request)
        spans_out.append({"kind": g.kind, "entity": g.entity, "start": g.start, "end": g.end,
                          "size": size, "covered": covered,
                          "detected": covered == size, "flagged": flagged,
                          "miss": covered < size and not flagged, "leak": leaked, "would_leak": would_leak})

    false_candidates = [u for u in uncertain
                        if not any(g.kind in PERSONAL and _overlaps(u["start"], u["end"], g.start, g.end)
                                   for g in doc.spans)]
    if guard:
        # The guard stopped a request: needless only if no personal detail would have gone out.
        unnecessary_block = mode == "auto" and not any(s["would_leak"] for s in spans_out)
    else:
        unnecessary_block = bool(first.uncertain) and len(false_candidates) == len(uncertain) and mode == "auto"

    # Meaning: one token per party entity, distinct across entities (fully masked mentions only).
    # pii-eval.2 scores PERSON-NAME REFERENCES: a party's name inside an
    # address ("Zaman Street") masked under that address's token is a place
    # reference, not a second token for the person. Any other mention masked
    # under a non-NAME token still counts (and breaks consistency). The
    # pii-eval.1 definition (any covering token) is kept as `_any_token`.
    addresses = [g for g in doc.spans if g.kind == "ADDRESS"]
    tokens: dict[str, set[str]] = {}
    tokens_any: dict[str, set[str]] = {}
    for g in personal:
        if g.kind == "NAME" and g.entity in doc.parties:
            for a, b, kind, tok in masking.masked_spans:
                if a <= g.start and g.end <= b:
                    tokens_any.setdefault(g.entity, set()).add(tok)
                    in_address = any(x.start <= g.start and g.end <= x.end for x in addresses)
                    if kind == "NAME" or not in_address:
                        tokens.setdefault(g.entity, set()).add(tok)

    def _consistent(t: dict[str, set[str]]) -> bool:
        return all(len(v) == 1 for v in t.values()) and len(set().union(*t.values()) if t else set()) == len(t)

    consistent, consistent_any = _consistent(tokens), _consistent(tokens_any)
    deadlines = [g for g in gold if g.kind == "DEADLINE"]
    preserved = (all(_norm(doc.text[g.start:g.end]) in _norm(request) for g in deadlines)
                 if request is not None else None)
    return {"id": doc.id, "mode": mode, "blocked": blocked, "sent": request is not None, "block_reasons": reasons,
            "uncertain": len(uncertain), "false_candidates": len(false_candidates), "reviewer_marked": marked,
            "unnecessary_block": unnecessary_block, "spans": spans_out,
            "party_consistent": consistent if tokens and request is not None else None,
            "party_consistent_any_token": consistent_any if tokens_any and request is not None else None,
            "deadlines_preserved": preserved, "deadline_count": len(deadlines),
            "hygiene": _hygiene(request, doc) if request is not None else None}


# ── the whole set ───────────────────────────────────────────────────────────

def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def summarise(results: list[dict]) -> dict:
    spans = [s for r in results for s in r["spans"]]
    size = sum(s["size"] for s in spans)
    party = [r["party_consistent"] for r in results if r["party_consistent"] is not None]
    party_any = [r["party_consistent_any_token"] for r in results if r["party_consistent_any_token"] is not None]
    dl = [r for r in results if r["deadlines_preserved"] is not None and r["deadline_count"]]
    hyg = [r["hygiene"] for r in results if r["hygiene"] is not None]
    cands = sum(r["uncertain"] for r in results)
    by_reason: dict[str, int] = {}
    for r in results:
        for reason in r["block_reasons"]:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "documents": len(results), "sent": sum(r["sent"] for r in results),
        "blocked": sum(r["blocked"] for r in results),
        "sent_rate": _ratio(sum(r["sent"] for r in results), len(results)),
        "blocked_by_reason": dict(sorted(by_reason.items())),
        "blocked_only_by_policy": sum(r["block_reasons"] == ["unsupported_script"] for r in results),
        "party_scored_documents": len(party),
        "personal_spans": len(spans),
        "character_coverage": _ratio(sum(s["covered"] for s in spans), size),
        "detected_rate": _ratio(sum(s["detected"] for s in spans), len(spans)),
        "miss_rate": _ratio(sum(s["miss"] for s in spans), len(spans)),
        "flagged_spans": sum(s["flagged"] for s in spans),
        "leaks": sum(s["leak"] for s in spans),
        "unnecessary_blocks": sum(r["unnecessary_block"] for r in results),
        "reviewer_marked": sum(r.get("reviewer_marked", 0) for r in results),
        "unnecessary_block_rate": _ratio(sum(r["unnecessary_block"] for r in results), len(results)),
        "uncertain_spans": cands,
        "false_candidate_rate": _ratio(sum(r["false_candidates"] for r in results), cands),
        "party_consistency": _ratio(sum(party), len(party)),
        "party_consistency_any_token": _ratio(sum(party_any), len(party_any)),
        "address_character_coverage": _ratio(sum(s["covered"] for s in spans if s["kind"] == "ADDRESS"),
                                             sum(s["size"] for s in spans if s["kind"] == "ADDRESS")),
        "deadline_preservation": _ratio(sum(r["deadlines_preserved"] for r in dl), len(dl)),
        "request_hygiene": _ratio(sum(hyg), len(hyg)),
        "by_kind": {k: {"spans": sum(s["kind"] == k for s in spans),
                        "detected": sum(s["kind"] == k and s["detected"] for s in spans),
                        "missed": sum(s["kind"] == k and s["miss"] for s in spans),
                        "leaked": sum(s["kind"] == k and s["leak"] for s in spans),
                        "character_coverage": _ratio(sum(s["covered"] for s in spans if s["kind"] == k),
                                                     sum(s["size"] for s in spans if s["kind"] == k))}
                    for k in PERSONAL},
    }


#: Rubric 2 adds these (owner decision 2026-10-04): the first launch mode is
#: lawyer-confirm, so the SENT RATE is gated in manual mode only (auto mode's
#: is reported), and address coverage is gated in both modes.
THRESHOLDS_2 = {**THRESHOLDS, "manual_sent_rate": 0.60, "address_character_coverage": 0.95}


#: Rubric 3 (owner-approved 2026-10-04): the gate is the REVIEW (lawyer-confirm)
#: mode only; auto and flag-only results are report-only. A pass is a synthetic
#: engineering gate of the masking mechanism -- not lawyer validation, not
#: production approval.
THRESHOLDS_3 = {"review_leaks": 0, "review_character_coverage": 0.99, "review_address_character_coverage": 0.95,
                "review_party_consistency": 1.0, "review_deadline_preservation": 1.0, "review_sent_rate": 0.60}


def gate_3(review: dict) -> dict:
    def value(key, missing):
        return review[key] if review.get(key) is not None else missing
    checks = {
        "review_leaks": review["leaks"] <= THRESHOLDS_3["review_leaks"],
        "review_character_coverage": value("character_coverage", 0) >= THRESHOLDS_3["review_character_coverage"],
        "review_address_character_coverage":
            value("address_character_coverage", 1) >= THRESHOLDS_3["review_address_character_coverage"],
        "review_party_consistency": value("party_consistency", 1) >= THRESHOLDS_3["review_party_consistency"],
        "review_deadline_preservation":
            value("deadline_preservation", 1) >= THRESHOLDS_3["review_deadline_preservation"],
        "review_sent_rate": value("sent_rate", 0) >= THRESHOLDS_3["review_sent_rate"],
    }
    return {"thresholds": THRESHOLDS_3, "checks": checks, "report_only": ["auto", "manual", "request_hygiene"],
            "status": "detection_passed" if all(checks.values()) else "not_passed"}


def gate(auto: dict, manual: dict, rubric: int = 1) -> dict:
    thresholds = THRESHOLDS_2 if rubric == 2 else THRESHOLDS
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
    if rubric == 2:
        checks["manual_sent_rate"] = (manual["sent_rate"] or 0) >= thresholds["manual_sent_rate"]
        checks["address_character_coverage"] = all(
            (x["address_character_coverage"] if x["address_character_coverage"] is not None else 1)
            >= thresholds["address_character_coverage"] for x in (auto, manual))
    return {"thresholds": thresholds, "checks": checks, "auto_sent_rate_reported": auto.get("sent_rate"),
            "status": "detection_passed" if all(checks.values()) else "not_passed"}


def evaluate(dataset: Dataset, send, extra_by_doc: dict[str, list[dict]] | None = None,
             modes: tuple[str, ...] = ("auto", "manual")) -> dict:
    out = {"eval_version": EVAL_VERSION, "dataset": dataset.name, "dataset_sha256": dataset.sha256,
           "masking_version": pii_mask.MASKING_VERSION, "policy_sha256": pii_mask.POLICY_SHA256,
           "rubric_sha256": hashlib.sha256(rubric_path(dataset.name).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
           "coverage": coverage(dataset)}
    extra_by_doc = extra_by_doc or {}
    per = {mode: [score_document(d, send, mode=mode, extra=extra_by_doc.get(d.id)) for d in dataset.documents]
           for mode in modes}
    for mode in modes:
        out[mode] = summarise(per[mode])
    rubric = rubric_number(dataset.name)
    out["gate"] = gate_3(out["review"]) if rubric == 3 else gate(out["auto"], out["manual"], rubric=rubric)
    out["per_document"] = per
    return out
