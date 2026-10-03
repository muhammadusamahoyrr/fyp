"""The local scanner: every drafting question, over the whole document, no model
(ANALYZER_HYPOTHESES_PLAN.md §4).

`scan()` is pure: same text, segmentation, graph and type -> same results. Its
statuses are FINAL. Later stages (the AI review signal, the lawyer's decision)
are stored beside a result and never rewrite it.

Each result carries `evidence_groups`: one group per clause, in document order,
`{clause_id, sentence_ids[]}` -- parties, conflicting values and references
often span several clauses. A detector that raises is recorded as
`unable_to_determine` / `detector_error` for that question only; the others
still run.

Document-level conditions that make a confident "not located" impossible
(OCR not yet confirmed, the text cut at the analyzer's limit, unsupported
language) turn every `not_located` into `unable_to_determine` with that reason:
the scanner never claims it read what it could not.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.analyzer import terms as term_rules
from app.services.analyzer.hypotheses import catalog, detectors
from app.services.analyzer.hypotheses.detectors import NOT_LOCATED, UNABLE, ScanInput

logger = logging.getLogger(__name__)

SCANNER_VERSION = "hypothesis-scanner.1"
SKIPPED_TYPE_UNKNOWN = "document_type_unknown"

#: Conditions under which nothing can honestly be called "not located".
DOCUMENT_UNABLE_REASONS = ("ocr_unconfirmed", "text_limit_reached", "language_unsupported",
                           "page_map_unavailable")


@dataclass
class Result:
    question_id: str
    scope: str
    polarity: str
    status: str
    evidence_groups: list[dict]
    reason_code: str | None
    explain: bool

    def as_dict(self) -> dict:
        return {"question_id": self.question_id, "scope": self.scope, "polarity": self.polarity,
                "status": self.status, "evidence_groups": self.evidence_groups,
                "reason_code": self.reason_code, "explain": self.explain}


def _groups(sentence_ids: list[str], sentences: list[dict]) -> list[dict]:
    order = {s["sentence_id"]: (i, s["clause_id"]) for i, s in enumerate(sentences)}
    known = sorted({sid for sid in sentence_ids if sid in order}, key=lambda sid: order[sid][0])
    groups: dict[str, list[str]] = {}
    for sid in known:
        groups.setdefault(order[sid][1], []).append(sid)
    return [{"clause_id": cid, "sentence_ids": ids} for cid, ids in groups.items()]


def scan(*, text: str, sentences: list[dict], graph_rows: list[dict], document_type: str | None,
         document_unable_reason: str | None = None,
         catalogue: catalog.Catalogue | None = None) -> dict:
    """{catalogue, catalogue_sha256, scanner, document_type, results[], skipped[]}."""
    catalogue = catalogue or catalog.load()
    confirmed = document_type if document_type in catalog.DOCUMENT_TYPES else None
    terms = term_rules.candidates(text, sentences, confirmed) if confirmed in term_rules.TYPES else {}
    inp = ScanInput(text=text, sentences=sentences, graph_rows=graph_rows, document_type=confirmed, terms=terms)
    run, skipped = catalogue.for_document(confirmed)

    results = []
    for q in run:
        try:
            finding = q.detector(inp)
            if finding.status not in detectors.STATUSES:
                raise ValueError("unknown status")
        except Exception:  # noqa: BLE001 - one detector's failure is that question's answer only
            logger.exception("hypothesis detector %s failed", q.detector_name)
            finding = detectors.Finding(UNABLE, reason_code="detector_error")
        status, reason = finding.status, finding.reason_code
        if status == NOT_LOCATED and document_unable_reason:
            status, reason = UNABLE, document_unable_reason
        groups = [] if status in (NOT_LOCATED, UNABLE) else _groups(finding.sentence_ids, sentences)
        if status not in (NOT_LOCATED, UNABLE) and not groups:
            # A finding that points nowhere is not evidence of anything.
            status, reason = UNABLE, "detector_error"
        results.append(Result(question_id=q.id, scope=q.scope, polarity=q.polarity, status=status,
                              evidence_groups=groups, reason_code=reason, explain=q.explain))
    return {
        "catalogue": catalogue.version, "catalogue_sha256": catalogue.sha256, "scanner": SCANNER_VERSION,
        "document_type": confirmed,
        "results": [r.as_dict() for r in results],
        "skipped": [{"question_id": q.id, "scope": q.scope, "reason": SKIPPED_TYPE_UNKNOWN} for q in skipped],
    }
