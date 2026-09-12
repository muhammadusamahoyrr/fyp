"""The benchmark harness must not flatter the engine it is measuring.

Four defects made it do exactly that, and every one of them moved the number in
the same direction — towards looking better:

  * `379` was scored as found inside `1379`, and `PPC 302` inside `PPC 302-B`.
    A wrong provision earned a perfect critical-token score.
  * The worker recognised `max_pages` and then reported the PDF's FULL page
    count with `ok: True`. A capped run looked complete, and seconds-per-page
    was divided by pages that were never processed.
  * Every selected page was rasterised into memory before any recognition
    began — ~1.2 GB for 50 letter pages at 300 dpi — so the memory figure
    described the rendering strategy rather than the engine.
  * The threshold evaluator was handed `{}` at both call sites, so freezing
    thresholds would have produced a gate that passed everything.

These tests run without an OCR engine: the recognition call is stubbed, which is
enough to exercise accounting, timing and reporting, and is honest about
measuring the harness rather than any engine.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ocr_eval import metrics as M
from ocr_eval import worker as W
from ocr_eval.thresholds import (
    THRESHOLD_SCHEMA,
    evaluate,
    evaluate_slices,
    metrics_from_aggregates,
)

pytest.importorskip("reportlab")
pytest.importorskip("pypdfium2")


def _pdf(path: Path, pages: int) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    for i in range(pages):
        c.drawString(72, 720, f"Typed page {i}")
        c.showPage()
    c.save()
    return path


# ── defect 9: a token is a whole identifier, not a substring ────────────────

@pytest.mark.parametrize("token,text,expected", [
    ("379", "registered under section 1379", False),
    ("379", "registered under section 379", True),
    ("PPC 302", "charged under PPC 302-B", False),
    ("PPC 302", "charged under PPC 302.", True),
    ("PPC 302", "PPC 302, read with PPC 302-B", True),
    ("302", "section 302.1 applies", False),
    ("302", "the amount was 302.", True),
    ("12", "Section 124-A of the Code", False),
    ("12", "Section 12 of the Act", True),
    ("12", "clause 12/2020", False),
])
def test_a_token_matches_only_as_a_whole_identifier(token, text, expected):
    result = M.critical_token_matches([{"kind": "section", "value": token}], text)

    assert result["tokens"][0]["matched"] is expected


def test_a_near_miss_is_still_never_a_match():
    """The boundary fix must not have loosened anything: `PPC 3O2` with a letter
    O is a misread, and no amount of boundary logic makes it a hit."""
    result = M.critical_token_matches(
        [{"kind": "section", "value": "PPC 302"}], "charged under PPC 3O2")

    assert result["matched"] == 0


def test_repeated_occurrences_are_counted_not_collapsed():
    result = M.critical_token_matches(
        [{"kind": "section", "value": "PPC 302"}],
        "PPC 302 in the heading, and PPC 302 again in the order")

    assert result["tokens"][0]["occurrences"] == 2
    assert result["tokens"][0]["matched"] is True


def test_a_token_can_require_more_than_one_occurrence():
    """A judgment citing a section in its heading AND its order is not correctly
    read when only the heading survives."""
    token = {"kind": "section", "value": "PPC 302", "min_occurrences": 2}

    once = M.critical_token_matches([token], "PPC 302 appears once")
    twice = M.critical_token_matches([token], "PPC 302 and again PPC 302")

    assert once["tokens"][0]["matched"] is False
    assert twice["tokens"][0]["matched"] is True


def test_a_malformed_min_occurrences_falls_back_to_one():
    token = {"kind": "section", "value": "302", "min_occurrences": "lots"}

    assert M.critical_token_matches([token], "section 302")["matched"] == 1


# ── defect 10: page accounting ─────────────────────────────────────────────

def test_page_accounting_marks_a_capped_run_partial():
    capped = W._page_accounting(total=5, processed=3, skipped=2)
    whole = W._page_accounting(total=2, processed=2)

    assert capped["partial"] is True
    assert whole["partial"] is False


def test_page_accounting_marks_a_failed_page_partial():
    assert W._page_accounting(total=3, processed=2, failed=1)["partial"] is True


def test_an_unknown_page_total_does_not_claim_completeness():
    """`pages_total: None` means we could not count them. That is not a licence
    to call the run whole."""
    unknown = W._page_accounting(total=None, processed=3)

    assert unknown["pages_total"] is None
    assert unknown["partial"] is False, (
        "with no total there is nothing to be short of; the run reports what it "
        "processed and the manifest's expected_page_count is what catches a gap")


def test_the_worker_reports_processed_pages_not_the_documents_total(tmp_path,
                                                                    monkeypatch):
    """The defect: OCR three pages, report five, say ok."""
    monkeypatch.setattr(W, "_tesseract_image_to_text",
                        lambda *a, **kw: "recognised text")

    result = W._run_tesseract(_pdf(tmp_path / "five.pdf", 5),
                              {"lang": "eng", "dpi": 72, "max_pages": 3})

    assert result["pages_total"] == 5
    assert result["pages_processed"] == 3
    assert result["pages_skipped"] == 2
    assert result["partial"] is True


def test_a_page_that_fails_recognition_is_counted_not_hidden(tmp_path,
                                                             monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("engine blew up on this page")
        return "text"

    monkeypatch.setattr(W, "_tesseract_image_to_text", flaky)

    result = W._run_tesseract(_pdf(tmp_path / "three.pdf", 3),
                              {"lang": "eng", "dpi": 72})

    assert result["pages_processed"] == 2
    assert result["pages_failed"] == 1
    assert result["partial"] is True


def test_one_page_timing_out_does_not_discard_the_whole_document(tmp_path,
                                                                 monkeypatch):
    """Abandoning the run would throw away pages already read AND report
    nothing about the rest."""
    import subprocess

    calls = {"n": 0}

    def slow_once(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1)
        return "later page text"

    monkeypatch.setattr(W, "_tesseract_image_to_text", slow_once)

    result = W._run_tesseract(_pdf(tmp_path / "t.pdf", 3),
                              {"lang": "eng", "dpi": 72})

    assert result["pages_failed"] == 1
    assert result["pages_processed"] == 2
    assert "later page text" in result["text"]


def test_render_and_recognition_time_are_reported_separately(tmp_path,
                                                             monkeypatch):
    """Different costs with different fixes. One number cannot tell an operator
    whether the dpi or the engine is the problem."""
    monkeypatch.setattr(W, "_tesseract_image_to_text", lambda *a, **kw: "x")

    result = W._run_tesseract(_pdf(tmp_path / "r.pdf", 2),
                              {"lang": "eng", "dpi": 72})

    assert "render_seconds" in result and "ocr_seconds" in result
    assert result["render_seconds"] >= 0.0
    assert result["ocr_seconds"] >= 0.0


def test_skipped_counts_only_pages_beyond_the_cap():
    assert W._skipped(5, 3) == 2
    assert W._skipped(2, 3) == 0
    assert W._skipped(None, 3) == 0


# ── defect 11: one page in memory at a time ────────────────────────────────

def test_pages_are_rendered_lazily_and_released(tmp_path):
    """The old code built a list of every page before recognising any of them.

    Asserted by holding a reference to each image as it arrives: once the
    consumer moves on, the generator closes it, so every image except the one
    in hand is unusable. That is only true if they are produced — and released —
    one at a time.
    """
    from PIL import Image

    handed_out = []
    for item in W._iter_pdf_pages(_pdf(tmp_path / "many.pdf", 4), dpi=72,
                                  max_pages=4):
        if isinstance(item, int):
            continue                      # the page count, yielded first
        _index, image, _render = item
        assert isinstance(image, Image.Image)
        handed_out.append(image)

    closed = 0
    for image in handed_out:
        try:
            image.load()
        except Exception:
            closed += 1

    assert closed == len(handed_out), (
        f"only {closed} of {len(handed_out)} page bitmaps were released")


def test_the_page_count_is_known_before_any_page_is_rendered(tmp_path):
    pages = W._iter_pdf_pages(_pdf(tmp_path / "c.pdf", 7), dpi=72, max_pages=2)

    assert next(pages) == 7
    pages.close()


def test_an_enormous_page_is_refused_rather_than_rendered(tmp_path, monkeypatch):
    """A PDF declares its own page size, so a small file can demand a huge
    bitmap. The page is refused and counted; the document is not abandoned."""
    monkeypatch.setattr(W, "MAX_PAGE_PIXELS", 1_000)
    monkeypatch.setattr(W, "_tesseract_image_to_text", lambda *a, **kw: "x")

    result = W._run_tesseract(_pdf(tmp_path / "big.pdf", 2),
                              {"lang": "eng", "dpi": 72})

    assert result["pages_failed"] == 2
    assert result["pages_processed"] == 0
    assert result["partial"] is True


# ── defect 12: the gate is actually connected ──────────────────────────────

def _aggregates(cer=0.05, wer=0.10, tokens=0.9, length=0.95,
                failures=0.0, p95=3.0) -> dict:
    return {
        "character_error_rate": {"rate": cer, "edits": 5, "reference_units": 100},
        "word_error_rate": {"rate": wer, "edits": 2, "reference_units": 20},
        "critical_token_exact_match": {"total": 10, "matched": 9, "rate": tokens},
        "output_length_ratio_mean": length,
        "processing_failure_rate": failures,
        "seconds_per_processed_page_p95": p95,
    }


def test_aggregates_are_translated_into_the_gated_metric_names():
    metrics = metrics_from_aggregates(_aggregates())

    assert metrics["character_error_rate"] == 0.05
    assert metrics["critical_token_exact_match_rate"] == 0.9
    assert metrics["output_length_ratio"] == 0.95
    assert metrics["p95_seconds_per_page"] == 3.0
    assert set(metrics) == set(THRESHOLD_SCHEMA["metrics"]), (
        "a gated metric has no mapping, so the gate can never see it")


def test_a_frozen_threshold_now_actually_compares_a_measured_run():
    """The defect: `evaluate({})` at every call site meant freezing thresholds
    produced a gate that passed everything."""
    frozen = {
        "frozen": True,
        "metrics": {"character_error_rate": {"direction": "lower", "value": 0.10}},
    }

    good = evaluate(metrics_from_aggregates(_aggregates(cer=0.05)), frozen)
    bad = evaluate(metrics_from_aggregates(_aggregates(cer=0.25)), frozen)

    assert good.evaluated is True and good.passed is True
    assert bad.evaluated is True and bad.passed is False
    assert any("character_error_rate" in f for f in bad.failures)


def test_a_higher_is_better_metric_is_compared_in_the_right_direction():
    frozen = {
        "frozen": True,
        "metrics": {
            "critical_token_exact_match_rate": {"direction": "higher", "value": 0.95},
        },
    }

    assert evaluate(metrics_from_aggregates(_aggregates(tokens=0.99)),
                    frozen).passed is True
    assert evaluate(metrics_from_aggregates(_aggregates(tokens=0.80)),
                    frozen).passed is False


def test_slices_are_evaluated_when_configured():
    config = {
        "frozen": True,
        "metrics": {"character_error_rate": {"direction": "lower", "value": 0.10}},
        "slices": {
            "urd/photograph": {
                "metrics": {"character_error_rate": {"direction": "lower",
                                                     "value": 0.30}},
            },
        },
    }
    by_slice = {"urd/photograph": _aggregates(cer=0.20)}

    verdicts = evaluate_slices(by_slice, config)

    assert verdicts["urd/photograph"]["passed"] is True, (
        "the slice threshold, not the global one, decides a slice")


def test_a_configured_slice_that_was_not_measured_fails_loudly():
    """A benchmark that quietly stopped covering Urdu would otherwise keep
    passing."""
    config = {
        "frozen": True,
        "metrics": {"character_error_rate": {"direction": "lower", "value": 0.1}},
        "slices": {"urd/photograph": {"metrics": {}}},
    }

    verdicts = evaluate_slices({"eng/scanned": _aggregates()}, config)

    assert verdicts["urd/photograph"]["evaluated"] is False
    assert verdicts["urd/photograph"]["passed"] is None
    assert "not measured" in verdicts["urd/photograph"]["reason"]


def test_no_slice_verdicts_when_no_slice_is_configured():
    assert evaluate_slices({"eng/scanned": _aggregates()}, THRESHOLD_SCHEMA) == {}


def test_the_shipped_schema_is_still_unfrozen():
    """Nothing in this change may accidentally set a release threshold."""
    assert THRESHOLD_SCHEMA["frozen"] is False
    assert all(spec["value"] is None
               for spec in THRESHOLD_SCHEMA["metrics"].values())
    assert all(v is None for v in THRESHOLD_SCHEMA["slices"].values())


# ── English, Urdu and mixed are reported separately ────────────────────────

def _two_language_dataset(tmp_path: Path) -> Path:
    """A manifest with one English and one Urdu fixture, via the passthrough
    engine so no OCR engine is needed."""
    import hashlib
    import json

    root = tmp_path / "ds"
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)

    fixtures = []
    for fid, language, body in [
        ("eng-1", "eng", "Order of the Civil Court."),
        ("urd-1", "urd", "دیوانی عدالت کا حکم۔"),
    ]:
        page = root / "pages" / f"{fid}.txt"
        page.write_text(body, encoding="utf-8")
        (root / "transcripts" / f"{fid}.txt").write_text(body, encoding="utf-8")
        fixtures.append({
            "fixture_id": fid,
            "path": f"pages/{fid}.txt",
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "document_type": "court_order",
            "language": language,
            "script_style": "latin" if language == "eng" else "nastaliq",
            "capture": "scanned",
            "writing": "printed",
            "rotation": "none",
            "expected_page_count": 1,
            "transcript_path": f"transcripts/{fid}.txt",
            "critical_tokens": [],
            "de_identified": True,
            "consent": True,
            "synthetic": True,
        })

    manifest = {
        "schema_version": 1,
        "dataset_id": "two-lang",
        "created_utc": "2026-01-01T00:00:00+00:00",
        "de_identified": {"confirmed": True, "confirmed_by": "QA",
                          "method": "synthetic text authored for tests"},
        "consent": {"confirmed": True, "basis": "synthetic test data"},
        "fixtures": fixtures,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_english_and_urdu_are_reported_separately(tmp_path):
    """An English number and an Urdu number describe different capabilities.

    The mean of the two describes neither, and it is the Urdu figure this
    product actually depends on.
    """
    from ocr_eval.harness import OcrConfig, run_benchmark

    passthrough = OcrConfig(name="synthetic", lang="eng",
                            engine="passthrough_synthetic")
    capability = {
        "platform": {"os": "TestOS", "python_version": "3.12.0"},
        "tesseract": {"available": True, "version": "5.3.4",
                      "languages_missing": [], "languages_present": ["eng", "urd"]},
    }

    report = run_benchmark(_two_language_dataset(tmp_path),
                           configs=(passthrough,), capability=capability)
    block = report["results"]["synthetic"]

    assert set(block["by_language"]) == {"eng", "urd"}
    assert set(block["by_slice"]) == {"eng/scanned", "urd/scanned"}
    for language in ("eng", "urd"):
        assert block["by_language"][language]["fixtures_attempted"] == 1


def test_a_slice_is_keyed_on_the_manifest_not_on_the_output(tmp_path):
    """Slicing on anything the engine produced would move whenever the engine
    did, and could not be compared across runs."""
    from ocr_eval.harness import OcrConfig, run_benchmark

    passthrough = OcrConfig(name="synthetic", lang="eng",
                            engine="passthrough_synthetic")
    capability = {
        "platform": {}, "tesseract": {"available": True, "languages_missing": []},
    }

    report = run_benchmark(_two_language_dataset(tmp_path),
                           configs=(passthrough,), capability=capability)
    fixtures = report["results"]["synthetic"]["fixtures"]

    by_id = {f["fixture_id"]: f for f in fixtures}
    assert by_id["urd-1"]["language"] == "urd"
    assert by_id["urd-1"]["capture"] == "scanned"
    assert by_id["eng-1"]["language"] == "eng"


def test_a_synthetic_run_still_carries_no_headline_aggregate(tmp_path):
    """Per-language blocks must not become a back door for accuracy claims from
    a run that never looked at a pixel."""
    from ocr_eval.harness import HARNESS_TEST_ONLY, OcrConfig, run_benchmark

    passthrough = OcrConfig(name="synthetic", lang="eng",
                            engine="passthrough_synthetic")
    report = run_benchmark(
        _two_language_dataset(tmp_path), configs=(passthrough,),
        capability={"platform": {},
                    "tesseract": {"available": True, "languages_missing": []}})

    assert report["status"] == HARNESS_TEST_ONLY
    assert report["measured"] is False
    assert report["aggregates"] is None
