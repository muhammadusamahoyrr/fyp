"""The ONE path from confirmed text to the exact AI request (`ai_report` engine).

Production (`ai_stage`), the lawyer's preview (`pii_confirmation`) and the
rules-only evaluation (`pii_evaluation`, pipeline `production-rules-only`)
all call `compose`, so what is evaluated is what the app runs: the same
sentence selection, masking with the lawyer's decisions, message building
and final leak check. No locator: production masking is rules-only.

Pure: no database, no network, no logging. Offsets, codes and hashes only
leave it; the masked messages are returned to the caller, never stored here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.analyzer import ai_client, ai_report, pii_mask, receipts

#: The name the evaluation records for this pipeline.
PIPELINE = "production-rules-only"


@dataclass
class Composed:
    send_ids: set[str]
    masking: pii_mask.Masking
    #: The exact messages, or None when masking is uncertain or they could not be built.
    messages: list[dict] | None = None
    #: Final leak-check codes on `messages` ([] = clean).
    guard: list[str] = field(default_factory=list)
    digest: str | None = None
    #: `ai_client.AIError` code when the messages could not be built.
    error: str | None = None

    @property
    def sendable(self) -> bool:
        """Masking certain, messages built, final check clean. (Lawyer-confirm
        mode additionally needs an approval of exactly `digest`.)"""
        return self.messages is not None and not self.guard and not self.masking.uncertain


def send_ids(sentences: list[dict], scan_ids) -> set[str]:
    """The sentences the AI report sends: not an empty form field, not withheld by the injection scan."""
    return {s["sentence_id"] for s in sentences if not s.get("empty_value") and s["sentence_id"] not in scan_ids}


def compose(text: str, sentences: list[dict], scan_ids, decisions: list[dict] | None) -> Composed:
    ids = send_ids(sentences, scan_ids)
    masking = pii_mask.prepare(text, sentences, ids, decisions)
    out = Composed(send_ids=ids, masking=masking)
    if masking.uncertain:
        return out
    try:
        out.messages = ai_report.build_messages(text, sentences, scan_ids, masking.bodies)
    except ai_client.AIError as exc:
        out.error = exc.code
        return out
    out.guard = pii_mask.leak_check(out.messages)
    out.digest = receipts.request_digest(out.messages)
    return out
