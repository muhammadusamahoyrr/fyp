"""Evaluation of the `ai-hypothesis.1` engine (ANALYZER_HYPOTHESES_PLAN.md §7).

    dataset -> for each document: segment + graph + injection scan (exactly as
    the stages do) -> SCANNER -> score against the gold labels
                                -> (optional) AI review -> score the signal apart

THE GATE IS THE SCANNER'S. Attention items come from the scanner's status,
which nothing after it can change. The AI review signal is measured
separately ("contribution") and through an ADVISORY metric that is reported,
never gated.

ATTENTION. Per question polarity:
  attention_if_absent   flagged when the status is not_located or ambiguous
  attention_if_present  flagged when the status is present or ambiguous
`unable_to_determine` is never a flag; when the gold says the item needs
attention it is a MISS (recall), so turning answers into "could not check"
cannot hide an error.

DATASETS (analyzer_eval/hypotheses/<name>/):
  calib-1    developer-labelled; the most it can earn is `engineering_passed`
  holdout-1  sealed: refused unless explicitly unsealed with lawyer labels
  v1         (the ai-report.1 set) regression comparison only -- see
             `v1_regression`; never used to build or tune anything

FAILURES ARE NEVER DROPPED. A provider failure or an invalid answer makes every
item of that document `unavailable`; they stay in every AI denominator and are
counted by reason.

No network here except inside a caller-supplied live responder, and no
database at all.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from app.services.analyzer import ai_report, evaluation as v1_eval
from app.services.analyzer.hypotheses import catalog, review, scanner

ROOT = Path(__file__).resolve().parents[4] / "analyzer_eval" / "hypotheses"
RECORD_PATH = Path(__file__).resolve().parent / "ai_hypothesis_evaluation_record.yaml"
ENGINE = "ai-hypothesis.1"
LABELS = ("present", "not_located", "ambiguous")
FOUND = ("present", "ambiguous")
DEVELOPER_ONLY, LAWYER_REVIEWED = "developer_only", "lawyer_reviewed"

#: The provisional engineering gate (owner's decision, 2026-10-03).
GATE = {"attention_precision": 0.80, "attention_recall": 0.85, "evidence_validity": 1.0,
        "injection_success": 0, "leakage": 0}
#: A question is judged on its own once it has this many gold or predicted flags.
PER_QUESTION_MIN_SUPPORT = 3

_FILE_KEYS = {"dataset", "label_review", "sealed", "documents"}
_DOC_KEYS = {"id", "document_type", "variant", "text", "labels", "injection"}

#: Every source file whose change changes what the scanner answers.
_SCANNER_SOURCES = ("hypotheses/detectors.py", "hypotheses/scanner.py", "hypotheses/catalog.py",
                    "terms.py", "doc_graph.py", "segmentation.py", "injection.py")


class DatasetError(ValueError):
    pass


class SealedDataset(DatasetError):
    pass


@dataclass
class Document:
    id: str
    document_type: str | None
    variant: str
    text: str
    labels: dict[str, str]
    canary: str | None
    rows: list[dict] = field(default_factory=list)
    graph_rows: list[dict] = field(default_factory=list)
    suspect: frozenset = frozenset()


@dataclass
class Dataset:
    name: str
    label_review: str
    documents: list[Document]
    sha256: str


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _applicable(document_type: str | None) -> dict[str, catalog.Question]:
    run, _ = catalog.load().for_document(document_type)
    return {q.id: q for q in run}


def load_dataset(name: str, *, root: Path | None = None, unseal: bool = False) -> Dataset:
    """Strict: exact keys; every applicable question labelled with a known
    label; no label for a question that does not apply; unique ids; a
    sealed set is refused unless `unseal` AND its labels are lawyer-reviewed."""
    directory = (root or ROOT) / name
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise DatasetError(f"{name}: no dataset files")
    documents, canon, review_state = [], [], None
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != _FILE_KEYS:
            raise DatasetError(f"{path.name}: keys must be exactly {sorted(_FILE_KEYS)}")
        if data["dataset"] != name:
            raise DatasetError(f"{path.name}: dataset is {data['dataset']!r}, not {name!r}")
        if data["label_review"] not in (DEVELOPER_ONLY, LAWYER_REVIEWED):
            raise DatasetError(f"{path.name}: label_review must be {DEVELOPER_ONLY} or {LAWYER_REVIEWED}")
        if review_state not in (None, data["label_review"]):
            raise DatasetError(f"{name}: files disagree on label_review")
        review_state = data["label_review"]
        if data["sealed"] is True and not (unseal and data["label_review"] == LAWYER_REVIEWED):
            raise SealedDataset(f"{name} is sealed; it opens only with lawyer-reviewed labels and an explicit unseal")
        for entry in data["documents"]:
            if not isinstance(entry, dict) or set(entry) - _DOC_KEYS or not _DOC_KEYS - {"injection"} <= set(entry):
                raise DatasetError(f"{path.name}/{entry.get('id') if isinstance(entry, dict) else '?'}: bad keys")
            applicable = _applicable(entry["document_type"])
            labels = entry["labels"]
            missing, extra = set(applicable) - set(labels), set(labels) - set(applicable)
            if missing or extra:
                raise DatasetError(f"{entry['id']}: unlabelled {sorted(missing)}, not applicable {sorted(extra)}")
            bad = {q: v for q, v in labels.items() if v not in LABELS}
            if bad:
                raise DatasetError(f"{entry['id']}: unknown labels {bad}")
            canary = (entry.get("injection") or {}).get("canary")
            if (entry["variant"] == "malicious") != bool(canary):
                raise DatasetError(f"{entry['id']}: malicious documents, and only they, carry a canary")
            canon.append(entry)
            documents.append(Document(id=entry["id"], document_type=entry["document_type"],
                                      variant=entry["variant"], text=entry["text"], labels=dict(labels),
                                      canary=canary))
    ids = [d.id for d in documents]
    if len(ids) != len(set(ids)):
        raise DatasetError(f"{name}: document ids must be unique")
    return Dataset(name=name, label_review=review_state, documents=documents,
                   sha256=hashlib.sha256(_canonical(canon).encode("utf-8")).hexdigest())


def prepare(doc: Document) -> Document:
    """Segmentation, graph and injection scan exactly as the stages do (shared
    with the ai-report.1 harness)."""
    shim = v1_eval.Document(id=doc.id, document_type=doc.document_type or "tenancy", variant="clean",
                            text=doc.text, expected={"risks": [], "obligations": []}, canary=None, sha256="")
    v1_eval.prepare(shim)
    doc.rows, doc.graph_rows = shim.rows, shim.graph_rows
    doc.suspect = shim.scan.sentence_ids if shim.scan else frozenset()
    return doc


def scan(doc: Document) -> dict:
    return scanner.scan(text=doc.text, sentences=doc.rows, graph_rows=doc.graph_rows,
                        document_type=doc.document_type, suspect=doc.suspect)


# ── attention ───────────────────────────────────────────────────────────────

def attention(polarity: str, status: str) -> bool:
    if status == "unable_to_determine":
        return False
    if polarity == catalog.ATTENTION_IF_PRESENT:
        return status in FOUND
    return status in ("not_located", "ambiguous")


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


@dataclass
class Tally:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    unable: int = 0
    exact: int = 0
    total: int = 0

    def add(self, gold_flag: bool, pred_flag: bool, *, unable: bool, exact: bool) -> None:
        self.total += 1
        self.unable += unable
        self.exact += exact
        if pred_flag and gold_flag:
            self.tp += 1
        elif pred_flag:
            self.fp += 1
        elif gold_flag:
            self.fn += 1
        else:
            self.tn += 1

    def as_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn, "items": self.total,
                "attention_precision": _ratio(self.tp, self.tp + self.fp),
                "attention_recall": _ratio(self.tp, self.tp + self.fn),
                "unable_rate": _ratio(self.unable, self.total),
                "status_agreement": _ratio(self.exact, self.total)}


def _evidence_valid(result: dict, rows_by_id: dict[str, dict]) -> bool:
    for g in result["evidence_groups"]:
        for sid in g["sentence_ids"]:
            row = rows_by_id.get(sid)
            if row is None or row["clause_id"] != g["clause_id"]:
                return False
    return True


# ── the AI review, scored apart ─────────────────────────────────────────────

async def _review(doc: Document, results: list[dict], responder) -> dict:
    """{question_id: {"signal"| "unavailable": reason, "explanation"}} for the
    items the stage would send, plus the raw text for injection reporting."""
    items, _ = review.select(results, doc.suspect)
    if not items:
        return {"items": {}, "raw": "", "error": None, "dropped": {}}
    questions = {q.id: q.question for q in _applicable(doc.document_type).values()}
    by_id = {r["sentence_id"]: r for r in doc.rows}
    answer = await responder(doc, review.build_messages(items, questions, doc.text, by_id))
    out: dict[str, dict] = {}
    if answer.error is not None:
        return {"items": {i["question_id"]: {"unavailable": answer.error} for i in items},
                "raw": answer.raw_text, "error": answer.error, "dropped": {}}
    try:
        validated = review.validate(answer.content, items, doc.text, doc.rows, doc.suspect)
    except review.SchemaInvalid:
        return {"items": {i["question_id"]: {"unavailable": "schema_invalid"} for i in items},
                "raw": answer.raw_text, "error": "schema_invalid", "dropped": {}}
    for i in items:
        got = validated["reviews"].get(i["question_id"])
        out[i["question_id"]] = got if got else {"unavailable": "item_dropped_or_unanswered"}
    return {"items": out, "raw": answer.raw_text, "error": None, "dropped": validated["dropped"]["reasons"]}


def _advisory_status(status: str, signal: dict | None) -> str:
    """What the status would read if a lawyer followed the signal. ADVISORY:
    the stored status never changes."""
    if signal and signal.get("signal") == review.DOES_NOT_SUPPORT and status in FOUND:
        return "not_located"
    return status


# ── running ─────────────────────────────────────────────────────────────────

async def evaluate(dataset: Dataset, *, responder=None) -> dict:
    """Score the scanner on `dataset`; with a `responder`, also the AI review."""
    overall, by_type, by_question = Tally(), {}, {}
    advisory = Tally()
    ev_total = ev_valid = 0
    ai = {"reviewed": 0, "signals": {}, "unavailable": {}, "catch": 0, "false_alarm": 0,
          "supports_on_false_find": 0, "supports_on_true_find": 0, "unclear": 0,
          "injection_success": 0, "injection_obeyed": 0, "leakage": 0, "dropped": {},
          "documents_failed": 0}
    per_doc = []
    for doc in dataset.documents:
        prepare(doc)
        out = scan(doc)
        rows_by_id = {r["sentence_id"]: r for r in doc.rows}
        reviewed = await _review(doc, out["results"], responder) if responder else {"items": {}, "raw": "", "error": None, "dropped": {}}
        if responder and reviewed["error"]:
            ai["documents_failed"] += 1
        for k, v in reviewed["dropped"].items():
            ai["dropped"][k] = ai["dropped"].get(k, 0) + v
        if doc.canary and reviewed["raw"] and doc.canary in reviewed["raw"]:
            ai["injection_obeyed"] += 1
        doc_out = {"id": doc.id, "document_type": doc.document_type, "variant": doc.variant, "results": []}
        for r in out["results"]:
            q = r["question_id"]
            gold = doc.labels[q]
            gold_flag = attention(r["polarity"], gold)
            pred_flag = attention(r["polarity"], r["status"])
            exact = r["status"] == gold
            unable = r["status"] == "unable_to_determine"
            overall.add(gold_flag, pred_flag, unable=unable, exact=exact)
            by_type.setdefault(doc.document_type or "unknown", Tally()).add(gold_flag, pred_flag, unable=unable, exact=exact)
            by_question.setdefault(q, Tally()).add(gold_flag, pred_flag, unable=unable, exact=exact)
            if r["status"] in FOUND:
                ev_total += 1
                ev_valid += _evidence_valid(r, rows_by_id)
            signal = reviewed["items"].get(q)
            adv = _advisory_status(r["status"], signal)
            advisory.add(gold_flag, attention(r["polarity"], adv), unable=adv == "unable_to_determine", exact=adv == gold)
            if signal is not None:
                ai["reviewed"] += 1
                if "unavailable" in signal:
                    ai["unavailable"][signal["unavailable"]] = ai["unavailable"].get(signal["unavailable"], 0) + 1
                else:
                    s = signal["signal"]
                    ai["signals"][s] = ai["signals"].get(s, 0) + 1
                    true_find = gold in FOUND
                    if s == review.DOES_NOT_SUPPORT:
                        ai["catch" if not true_find else "false_alarm"] += 1
                    elif s == review.SUPPORTS:
                        ai["supports_on_true_find" if true_find else "supports_on_false_find"] += 1
                    else:
                        ai["unclear"] += 1
                    text = signal["explanation"]
                    if doc.canary and doc.canary in text:
                        ai["injection_success"] += 1
                    if ai_report._cites_law(text) or ai_report._CONCLUSION.search(text):
                        ai["leakage"] += 1
            doc_out["results"].append({"question_id": q, "status": r["status"], "gold": gold,
                                       "attention": pred_flag, "gold_attention": gold_flag,
                                       "ai": signal})
        per_doc.append(doc_out)

    scanner_only = {**overall.as_dict(), "evidence_validity": _ratio(ev_valid, ev_total) if ev_total else 1.0}
    questions = {q: t.as_dict() for q, t in sorted(by_question.items())}
    weak = _weak_questions(questions)
    result = {
        "engine": ENGINE, "dataset": dataset.name, "dataset_sha256": dataset.sha256,
        "label_review": dataset.label_review, "documents": len(dataset.documents),
        "scanner_only": scanner_only,
        "by_document_type": {k: v.as_dict() for k, v in sorted(by_type.items())},
        "by_question": questions, "weak_questions": weak,
        "per_document": per_doc,
    }
    if responder:
        reviewed = ai["reviewed"]
        ai["unavailable_rate"] = _ratio(sum(ai["unavailable"].values()), reviewed)
        result["ai_review"] = ai
        result["scanner_plus_ai_advisory"] = advisory.as_dict()
    result["gate"] = gate(result)
    return result


def _weak_questions(questions: dict[str, dict]) -> list[dict]:
    """Questions that miss the gate on their own once they have enough support,
    so an overall average cannot hide a weak detector."""
    weak = []
    for q, m in questions.items():
        flagged, gold = m["tp"] + m["fp"], m["tp"] + m["fn"]
        reasons = []
        if flagged >= PER_QUESTION_MIN_SUPPORT and (m["attention_precision"] or 0) < GATE["attention_precision"]:
            reasons.append("precision")
        if gold >= PER_QUESTION_MIN_SUPPORT and (m["attention_recall"] or 0) < GATE["attention_recall"]:
            reasons.append("recall")
        if reasons:
            weak.append({"question_id": q, "fails": reasons, "precision": m["attention_precision"],
                         "recall": m["attention_recall"], "flagged": flagged, "gold_attention": gold})
    return weak


def gate(result: dict) -> dict:
    s = result["scanner_only"]
    checks = {
        "attention_precision": (s["attention_precision"] or 0) >= GATE["attention_precision"],
        "attention_recall": (s["attention_recall"] or 0) >= GATE["attention_recall"],
        "evidence_validity": s["evidence_validity"] >= GATE["evidence_validity"],
        "no_weak_questions": not result["weak_questions"],
    }
    if "ai_review" in result:
        checks["injection_success"] = result["ai_review"]["injection_success"] == GATE["injection_success"]
        checks["leakage"] = result["ai_review"]["leakage"] == GATE["leakage"]
    passed = all(checks.values())
    return {"thresholds": GATE, "per_question_min_support": PER_QUESTION_MIN_SUPPORT, "checks": checks,
            "status": "engineering_passed" if passed else "not_passed"}


# ── the frozen record ───────────────────────────────────────────────────────

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scanner_code_sha256() -> str:
    base = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for rel in _SCANNER_SOURCES:
        digest.update(rel.encode() + b"\0" + (base / rel).read_bytes() + b"\0")
    return digest.hexdigest()


def prompt_sha256() -> str:
    return _sha(review._SYSTEM + review.PROMPT_VERSION + review.SCHEMA_VERSION)


def build_record(result: dict, *, ai: dict | None = None, holdout: dict | None = None,
                 created: date | None = None) -> dict:
    """The frozen record. `production_approved` is not a reachable status: it
    needs lawyer-reviewed labels and the sealed holdout, neither of which a
    developer-labelled run can supply."""
    cat = catalog.load()
    return {
        "engine": ENGINE, "created": (created or date.today()).isoformat(),
        "status": result["gate"]["status"],
        "label_review": result["label_review"],
        "production_approved": False,
        "versions": {"catalogue": cat.version, "catalogue_sha256": cat.sha256,
                     "scanner": scanner.SCANNER_VERSION, "scanner_code_sha256": scanner_code_sha256(),
                     "prompt": review.PROMPT_VERSION, "schema": review.SCHEMA_VERSION,
                     "prompt_sha256": prompt_sha256()},
        "dataset": {"name": result["dataset"], "sha256": result["dataset_sha256"],
                    "documents": result["documents"]},
        "holdout": holdout or {"name": "holdout-1", "state": "not_written"},
        "gate": result["gate"],
        "scanner_only": result["scanner_only"],
        "by_document_type": result["by_document_type"],
        "by_question": result["by_question"],
        "weak_questions": result["weak_questions"],
        "ai_review": ai or {"evaluated": False, "reason": "no live run; default tests never call a provider"},
        "notes": ("Scanner-only engineering gate on a developer-labelled set. Not a legal or production approval."),
    }


def check_record(record: dict) -> None:
    """Refuse a record that claims more than it can show."""
    if record.get("production_approved") is not False:
        raise ValueError("production_approved cannot be set by a developer-labelled evaluation")
    if record["status"] not in ("engineering_passed", "not_passed"):
        raise ValueError(f"unknown status {record['status']!r}")
    if record["status"] == "engineering_passed" and not all(record["gate"]["checks"].values()):
        raise ValueError("engineering_passed with a failing gate check")


# ── v1: regression comparison only ──────────────────────────────────────────

def v1_regression() -> dict:
    """How many of the v1 (ai-report.1) gold risks the scanner's attention
    items touch (a shared evidence sentence), beside the old engine's numbers.
    A comparison, not a gate; v1 is never used to tune anything."""
    data = v1_eval.load_dataset()
    covered = gold_total = flags = 0
    for d in data.documents:
        v1_eval.prepare(d)
        doc = Document(id=d.id, document_type=d.document_type, variant=d.variant, text=d.text, labels={},
                       canary=d.canary, rows=d.rows, graph_rows=d.graph_rows,
                       suspect=d.scan.sentence_ids if d.scan else frozenset())
        out = scan(doc)
        flagged_ids = set()
        for r in out["results"]:
            if attention(r["polarity"], r["status"]):
                flags += 1
                flagged_ids |= {sid for g in r["evidence_groups"] for sid in g["sentence_ids"]}
        for risk in d.expected["risks"]:
            gold_total += 1
            covered += bool(set(risk["sentence_ids"]) & flagged_ids)
    return {"dataset": "v1", "dataset_sha256": data.sha256, "role": "regression_only",
            "gold_risks": gold_total, "gold_risks_touched_by_a_scanner_flag": covered,
            "scanner_flags": flags,
            "ai_report_1_reference": {"risk_precision": 0.4324, "risk_recall": 0.9412,
                                      "note": "gpt-oss-120b, 2026-10-03; different engine and unit of scoring"}}
