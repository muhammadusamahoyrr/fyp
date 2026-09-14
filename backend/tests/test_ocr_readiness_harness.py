"""The OCR benchmark harness must refuse to invent a measurement.

These tests are about the HARNESS, not about OCR. There is no OCR engine on this
machine and no ground-truth dataset, which is exactly the condition the harness
has to behave well in: the dangerous outcome is not "we could not measure", it is
a report that looks measured because a skipped run defaulted its scores to zero.

Everything here runs on tiny synthetic fixtures through a passthrough engine that
never looks at a pixel. That is enough to exercise gating, manifest verification,
metrics, child-process isolation, timeouts and report hygiene — and it is
explicitly NOT accuracy evidence, which is itself one of the things asserted.

No database, no network, no provider calls, no product code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ocr_eval import metrics as M
from ocr_eval import probe as P
from ocr_eval.harness import DEFAULT_CONFIGS, OcrConfig, run_benchmark
from ocr_eval.manifest import load_manifest
from ocr_eval.memory import DEFAULT_SAMPLE_INTERVAL_SECONDS
from ocr_eval.status import (
    HARNESS_TEST_ONLY,
    MEASURED,
    NOT_RUN_ENGINE_UNAVAILABLE,
    NOT_RUN_FIXTURES_MISSING,
    NOT_RUN_MANIFEST_INVALID,
)
from ocr_eval.thresholds import THRESHOLD_SCHEMA, evaluate

# The passthrough engine returns the fixture file's own text, so a "perfect OCR"
# case is one where fixture content == transcript content.
PASSTHROUGH = OcrConfig(name="synthetic", lang="eng", engine="passthrough_synthetic")

FIXTURE_TEXT = "Order of the Civil Court. Section 12 of the Act applies."


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _capability(*, tesseract=True, missing_langs=()) -> dict:
    """A capability report, so gating can be tested without the real machine."""
    return {
        "platform": {"os": "TestOS", "python_version": "3.12.0"},
        "tesseract": {
            "available": tesseract,
            "version": "5.3.4" if tesseract else None,
            "languages_missing": list(missing_langs),
            "languages_present": [] if missing_langs else ["eng", "urd", "osd"],
        },
    }


def _dataset(
    tmp_path: Path,
    *,
    fixture_text: str = FIXTURE_TEXT,
    transcript_text: str | None = None,
    writing: str = "printed",
    handwriting_policy: str | None = None,
    synthetic: bool = True,
    critical_tokens=None,
    break_sha: bool = False,
    omit_transcript: bool = False,
    omit_fixture: bool = False,
    extra_fixture: dict | None = None,
) -> Path:
    """Build a valid-by-default dataset, with one thing broken on request.

    Defaulting to VALID matters: a test that breaks one field proves that field
    is what the loader rejected, rather than tripping over a second problem it
    never meant to create.
    """
    root = tmp_path / "ds"
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)

    fixture_path = root / "pages" / "f1.txt"
    transcript_path = root / "transcripts" / "f1.txt"

    fixture_bytes = fixture_text.encode("utf-8")
    if not omit_fixture:
        fixture_path.write_bytes(fixture_bytes)
    if not omit_transcript:
        transcript_path.write_text(
            fixture_text if transcript_text is None else transcript_text,
            encoding="utf-8")

    digest = _sha256(b"different bytes entirely" if break_sha else fixture_bytes)

    entry = {
        "fixture_id": "f1",
        "path": "pages/f1.txt",
        "sha256": digest,
        "document_type": "court_order",
        "language": "eng",
        "script_style": "latin",
        "capture": "scanned",
        "writing": writing,
        "rotation": "none",
        "expected_page_count": 1,
        "transcript_path": "transcripts/f1.txt",
        # Required since the field-scoring work: the split is assigned per
        # document family, and a critical token carries the slot it fills.
        "document_family": "helper_family",
        "split": "holdout",
        "critical_tokens": critical_tokens if critical_tokens is not None else [
            {"kind": "section", "value": "Section 12",
             "field": "section_number", "occurrence_index": 0},
        ],
        "de_identified": True,
        "consent": True,
        "synthetic": synthetic,
    }
    if handwriting_policy is not None:
        entry["handwriting_policy"] = handwriting_policy

    fixtures = [entry]
    if extra_fixture is not None:
        fixtures.append(extra_fixture)

    manifest = {
        "schema_version": 2,
        "dataset_id": "test-ds",
        "created_utc": "2026-01-01T00:00:00+00:00",
        "de_identified": {
            "confirmed": True, "confirmed_by": "QA",
            "method": "synthetic text authored for tests",
        },
        "consent": {"confirmed": True, "basis": "synthetic test data"},
        "fixtures": fixtures,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


# ── gate 1: the engine ──────────────────────────────────────────────────────

def test_a_missing_engine_produces_not_run_engine_unavailable(tmp_path):
    report = run_benchmark(
        _dataset(tmp_path), configs=(DEFAULT_CONFIGS[0],),
        capability=_capability(tesseract=False, missing_langs=["eng", "urd", "osd"]))

    assert report["status"] == NOT_RUN_ENGINE_UNAVAILABLE
    assert report["measured"] is False
    assert report["results"] is None
    assert report["aggregates"] is None


def test_missing_language_packs_are_named(tmp_path):
    """'Not ready' is unactionable. WHICH pack is missing is the whole message."""
    report = run_benchmark(
        _dataset(tmp_path), configs=(DEFAULT_CONFIGS[0],),
        capability=_capability(tesseract=True, missing_langs=["urd", "osd"]))

    assert report["status"] == NOT_RUN_ENGINE_UNAVAILABLE
    joined = " ".join(report["reasons"])
    assert "urd" in joined and "osd" in joined
    assert "eng" not in joined.replace("packs:", ""), (
        "a pack that is present must not be reported as missing")


def test_the_real_machine_is_reported_honestly():
    """Whatever this machine has, the probe must not overstate it."""
    caps = P.probe()
    ready, reasons = P.engine_ready(caps["tesseract"])

    assert ready == caps["engine_ready_for_benchmark"]
    if not ready:
        assert reasons, "engine reported not-ready with no reason given"


# ── gate 2: the dataset ─────────────────────────────────────────────────────

def test_a_missing_dataset_produces_not_run_fixtures_missing(tmp_path):
    report = run_benchmark(
        tmp_path / "nothing" / "manifest.json", configs=(PASSTHROUGH,),
        capability=_capability())

    assert report["status"] == NOT_RUN_FIXTURES_MISSING
    assert report["measured"] is False
    assert report["aggregates"] is None


def test_a_malformed_manifest_fails_closed(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("{ this is not json", encoding="utf-8")

    loaded = load_manifest(bad)
    assert loaded.ok is False
    assert loaded.status == NOT_RUN_MANIFEST_INVALID

    report = run_benchmark(bad, configs=(PASSTHROUGH,), capability=_capability())
    assert report["status"] == NOT_RUN_MANIFEST_INVALID
    assert report["results"] is None


def test_a_manifest_violating_the_schema_fails_closed(tmp_path):
    """A wrong enum value must be refused, not coerced to a default."""
    path = _dataset(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fixtures"][0]["capture"] = "telepathy"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_manifest(path)
    assert loaded.ok is False
    assert loaded.status == NOT_RUN_MANIFEST_INVALID
    assert any(i.code == "schema_violation" for i in loaded.issues)


def test_a_missing_transcript_fails_closed(tmp_path):
    """Never treated as an empty expected string.

    An absent ground truth silently scores any output as 100% insertion error,
    which looks like catastrophic engine failure rather than a missing file.
    """
    loaded = load_manifest(_dataset(tmp_path, omit_transcript=True))

    assert loaded.ok is False
    assert loaded.status == NOT_RUN_MANIFEST_INVALID
    assert any(i.code == "transcript_missing" for i in loaded.issues)


def test_a_sha256_mismatch_fails_closed(tmp_path):
    loaded = load_manifest(_dataset(tmp_path, break_sha=True))

    assert loaded.ok is False
    assert any(i.code == "checksum_mismatch" for i in loaded.issues)


def test_the_checksum_failure_does_not_print_the_actual_digest(tmp_path):
    """Printing it invites 'fixing' the manifest by pasting the new value."""
    loaded = load_manifest(_dataset(tmp_path, break_sha=True))
    detail = " ".join(i.detail for i in loaded.issues)

    assert not any(len(word) == 64 and all(c in "0123456789abcdef" for c in word)
                   for word in detail.split())


def test_a_fixture_path_escaping_the_dataset_is_refused(tmp_path):
    path = _dataset(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fixtures"][0]["path"] = "../../../etc/passwd"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_manifest(path)
    assert loaded.ok is False
    assert any(i.code == "path_escapes_dataset" for i in loaded.issues)


def test_an_absent_fixture_file_reports_fixtures_missing(tmp_path):
    loaded = load_manifest(_dataset(tmp_path, omit_fixture=True))

    assert loaded.ok is False
    assert loaded.status == NOT_RUN_FIXTURES_MISSING


# ── handwriting is a declared policy, never an inference ────────────────────

def test_handwriting_requires_an_explicit_policy_declaration(tmp_path):
    """Caught by the schema's if/then rule, which is why the code is
    `schema_violation` rather than the code-level one. What matters is that it
    fails closed and that the message names the missing field."""
    loaded = load_manifest(_dataset(tmp_path, writing="handwritten"))

    assert loaded.ok is False
    assert loaded.status == NOT_RUN_MANIFEST_INVALID
    assert "handwriting_policy" in " ".join(i.detail for i in loaded.issues)


def test_handwriting_is_still_refused_without_the_schema_validator(tmp_path, monkeypatch):
    """The second layer, tested on its own.

    `jsonschema` is present transitively rather than declared, so a dependency
    bump can remove it. If that happened, the if/then rule above would stop
    running and this policy would be enforced by nothing — unless the code-level
    check also holds. Here the validator is stubbed out to prove it does.
    """
    from ocr_eval import manifest as manifest_module

    monkeypatch.setattr(manifest_module, "_validate_against_schema", lambda data: [])
    loaded = load_manifest(_dataset(tmp_path, writing="handwritten"))

    assert loaded.ok is False
    assert any(i.code == "handwriting_policy_missing" for i in loaded.issues)


def test_declared_handwriting_is_skipped_by_policy_not_scored(tmp_path):
    loaded = load_manifest(_dataset(
        tmp_path, writing="handwritten", handwriting_policy="unsupported_by_policy"))

    assert loaded.ok is True
    assert len(loaded.runnable) == 0, "a handwritten page must not be attempted"
    assert len(loaded.policy_skipped) == 1

    report = run_benchmark(
        _dataset(tmp_path, writing="handwritten",
                 handwriting_policy="unsupported_by_policy"),
        configs=(PASSTHROUGH,), capability=_capability())
    skipped = report["manifest"]["fixtures_skipped_by_policy"]
    assert skipped and skipped[0]["policy"] == "unsupported_by_policy"
    assert skipped[0]["failure_category"] == "unsupported_by_policy"


# ── synthetic data is labelled, loudly ──────────────────────────────────────

def test_a_synthetic_run_is_labelled_harness_only(tmp_path):
    report = run_benchmark(
        _dataset(tmp_path, synthetic=True), configs=(PASSTHROUGH,),
        capability=_capability())

    assert report["status"] == HARNESS_TEST_ONLY
    assert report["status"].endswith("NOT_ACCURACY_EVIDENCE")
    assert report["measured"] is False


def test_a_non_recognition_engine_is_harness_only_even_with_real_fixtures(tmp_path):
    """The label follows the ENGINE too, not only the fixture flag.

    A passthrough engine never looks at a pixel, so however genuine the corpus
    is, the run says nothing about recognition.
    """
    report = run_benchmark(
        _dataset(tmp_path, synthetic=False), configs=(PASSTHROUGH,),
        capability=_capability())

    assert report["status"] == HARNESS_TEST_ONLY


def test_one_synthetic_fixture_labels_the_whole_run(tmp_path):
    """Per-fixture labelling would leave the AGGREGATE readable as accuracy."""
    report = run_benchmark(
        _dataset(tmp_path, synthetic=True), configs=(PASSTHROUGH,),
        capability=_capability())

    assert report["status"] == HARNESS_TEST_ONLY
    assert report["aggregates"] is None


# ── a skipped or failed run never reads as measured ─────────────────────────

@pytest.mark.parametrize("kwargs,expected", [
    ({"capability": _capability(tesseract=False, missing_langs=["eng"])},
     NOT_RUN_ENGINE_UNAVAILABLE),
])
def test_no_result_is_emitted_as_measured_after_a_skipped_run(
        tmp_path, kwargs, expected):
    report = run_benchmark(
        _dataset(tmp_path), configs=(DEFAULT_CONFIGS[0],), **kwargs)

    assert report["status"] == expected
    assert report["measured"] is False
    assert report["aggregates"] is None
    assert report["results"] is None
    # The specific defect this guards: a zero that reads as a score.
    body = json.dumps(report)
    assert '"character_error_rate": 0' not in body
    assert '"rate": 0.0' not in body


def test_thresholds_refuse_to_return_a_pass_when_unfrozen():
    """An unconfigured gate reporting success is worse than no gate."""
    verdict = evaluate({"character_error_rate": 0.01}, THRESHOLD_SCHEMA)

    assert THRESHOLD_SCHEMA["frozen"] is False
    assert verdict.evaluated is False
    assert verdict.passed is None


def test_a_frozen_threshold_cannot_pass_an_unmeasured_metric():
    frozen = {
        "frozen": True,
        "metrics": {"character_error_rate": {"direction": "lower", "value": 0.15}},
    }
    verdict = evaluate({}, frozen)

    assert verdict.evaluated is True
    assert verdict.passed is False
    assert any("not measured" in f for f in verdict.failures)


# ── metric correctness, against strings worked out by hand ──────────────────

def test_character_error_rate_on_known_strings():
    # kitten -> sitting is the textbook distance-3 pair; reference length 6.
    result = M.character_error_rate("kitten", "sitting")
    assert result.edits == 3
    assert result.reference_units == 6
    assert result.rate == pytest.approx(0.5)


def test_a_perfect_match_scores_zero():
    assert M.character_error_rate("identical", "identical").rate == 0.0
    assert M.word_error_rate("one two three", "one two three").rate == 0.0


def test_word_error_rate_counts_words_not_characters():
    result = M.word_error_rate("the quick brown fox", "the quick brown cat")
    assert result.edits == 1
    assert result.reference_units == 4
    assert result.rate == pytest.approx(0.25)


def test_an_empty_reference_yields_none_not_zero():
    """A rate of 0.0 would mean 'perfect', which is a claim about nothing."""
    assert M.character_error_rate("", "anything").rate is None
    assert M.word_error_rate("", "anything").rate is None
    assert M.output_length_ratio("", "anything") is None


def test_aggregate_is_micro_averaged_over_summed_units():
    """A long page must not be weighted the same as a short one.

    2 edits over 100 chars and 0 over 4 chars is 2/104, not the mean of
    0.02 and 0.0 (= 0.01).
    """
    aggregate = M.aggregate_error_rate([
        M.ErrorRate(0.02, 2, 100),
        M.ErrorRate(0.0, 0, 4),
    ])
    assert aggregate.rate == pytest.approx(2 / 104)


def test_coverage_separates_silence_from_confident_nonsense():
    assert M.output_length_ratio("abcdefghij", "") == 0.0
    assert M.output_length_ratio("abcdefghij", "abcde") == pytest.approx(0.5)
    # Over-production is CER's business; coverage caps so a hallucinating engine
    # cannot score above a correct one.
    assert M.output_length_ratio("abcdefghij", "x" * 40) == 1.0


def test_normalisation_policies_are_explicit_and_distinct():
    assert M.normalise("A  B", "strict") == "A  B"
    assert M.normalise("A  B", "standard") == "A B"
    assert M.normalise("A  B", "aggressive") == "a b"
    with pytest.raises(ValueError):
        M.normalise("x", "whatever-feels-right")


def test_aggressive_normalisation_folds_arabic_indic_digits():
    """۲۰۲۴ and 2024 are different code points and the same year."""
    assert M.normalise("۲۰۲۴", "aggressive") == "2024"
    assert M.normalise("۲۰۲۴", "standard") == "۲۰۲۴"


def test_invisible_marks_do_not_count_as_errors():
    """A zero-width joiner is invisible to whoever wrote the transcript."""
    assert M.character_error_rate("‍text", "text").rate == 0.0


# ── critical tokens are deterministic and exact ─────────────────────────────

def test_critical_token_matching_is_exact_and_deterministic():
    tokens = [{"kind": "section", "value": "PPC 302"},
              {"kind": "date", "value": "12 March 2026"}]
    text = "Charged under PPC 302 on 12 March 2026."

    first = M.critical_token_matches(tokens, text)
    second = M.critical_token_matches(tokens, text)

    assert first == second
    assert first["matched"] == 2
    assert first["rate"] == 1.0


def test_a_near_miss_token_is_not_a_match():
    """'PPC 3O2' (letter O) must never count. No fuzzy matching, no threshold."""
    tokens = [{"kind": "section", "value": "PPC 302"}]
    result = M.critical_token_matches(tokens, "Charged under PPC 3O2.")

    assert result["matched"] == 0
    assert result["rate"] == 0.0


def test_critical_token_output_never_echoes_the_token_value():
    """These values are document content and land in reports."""
    tokens = [{"kind": "name", "value": "Zubaida Bibi"}]
    result = M.critical_token_matches(tokens, "Statement of Zubaida Bibi.")

    assert result["matched"] == 1
    assert "Zubaida" not in json.dumps(result)


# ── language order is two configurations, never one ─────────────────────────

def test_language_orderings_are_separate_configurations():
    urd_first, eng_first = DEFAULT_CONFIGS
    assert urd_first.lang == "urd+eng"
    assert eng_first.lang == "eng+urd"
    assert urd_first.name != eng_first.name


def test_results_for_each_language_order_stay_separate(tmp_path):
    a = OcrConfig(name="urd+eng", lang="urd+eng", engine="passthrough_synthetic")
    b = OcrConfig(name="eng+urd", lang="eng+urd", engine="passthrough_synthetic")

    report = run_benchmark(
        _dataset(tmp_path), configs=(a, b), capability=_capability())

    assert set(report["results"]) == {"urd+eng", "eng+urd"}
    assert report["results"]["urd+eng"]["config"]["lang"] == "urd+eng"
    assert report["results"]["eng+urd"]["config"]["lang"] == "eng+urd"


# ── child process, timeout, termination ─────────────────────────────────────

def test_a_fixture_runs_in_a_child_process_and_reports_metrics(tmp_path):
    report = run_benchmark(
        _dataset(tmp_path), configs=(PASSTHROUGH,), capability=_capability())
    fixtures = report["results"]["synthetic"]["fixtures"]

    assert len(fixtures) == 1
    assert fixtures[0]["ok"] is True
    # Passthrough returns the fixture's own text, and the transcript is that same
    # text, so a correctly wired harness scores this as perfect.
    assert fixtures[0]["character_error_rate"]["rate"] == 0.0
    assert fixtures[0]["wall_clock_seconds"] is not None


def test_a_timeout_terminates_the_child_and_is_categorised(tmp_path):
    slow = OcrConfig(
        name="slow", lang="eng", engine="passthrough_synthetic",
        synthetic_delay_seconds=30.0, fixture_timeout_seconds=1.0)

    report = run_benchmark(
        _dataset(tmp_path), configs=(slow,), capability=_capability())
    fixture = report["results"]["slow"]["fixtures"][0]

    assert fixture["ok"] is False
    assert fixture["failure_category"] == "timeout"
    assert fixture["termination"] in {"terminated", "killed",
                                      "killed_without_psutil", "already_gone"}


def test_failures_are_counted_by_fixed_category(tmp_path):
    slow = OcrConfig(
        name="slow", lang="eng", engine="passthrough_synthetic",
        synthetic_delay_seconds=30.0, fixture_timeout_seconds=1.0)

    report = run_benchmark(
        _dataset(tmp_path), configs=(slow,), capability=_capability())
    by_category = report["results"]["slow"]["aggregates"][
        "processing_failures_by_category"]

    assert by_category["timeout"] == 1
    assert by_category["engine_error"] == 0
    assert report["results"]["slow"]["aggregates"]["processing_failure_rate"] == 1.0


# ── the memory metric carries its method ────────────────────────────────────

def test_the_memory_metric_names_its_method_and_interval(tmp_path):
    report = run_benchmark(
        _dataset(tmp_path), configs=(PASSTHROUGH,), capability=_capability())

    block = report["memory_measurement"]
    assert block["metric"] == "peak_sampled_process_tree_rss_bytes"
    assert block["sample_interval_seconds"] == DEFAULT_SAMPLE_INTERVAL_SECONDS

    memory = report["results"]["synthetic"]["fixtures"][0]["memory"]
    assert memory["metric"] == "peak_sampled_process_tree_rss_bytes"
    assert memory["sample_interval_seconds"] == DEFAULT_SAMPLE_INTERVAL_SECONDS
    assert memory["implementation"]
    assert "not an exact operating-system peak" in memory["caveat"].lower()


def test_an_unobservable_process_tree_reports_unavailable_not_zero():
    from ocr_eval.memory import unavailable

    result = unavailable("psutil is not importable").as_dict()
    assert result["available"] is False
    assert result["peak_sampled_process_tree_rss_bytes"] is None, (
        "0 bytes is a measurement; 'could not look' is not")
    assert result["unavailable_reason"]


def test_tracemalloc_is_not_used_anywhere_in_the_harness():
    """Contracted explicitly: it measures Python allocations, and OCR work is
    native code and child processes."""
    package = Path(__file__).resolve().parent.parent / "ocr_eval"
    offenders = [
        p.name for p in package.glob("*.py")
        if "tracemalloc" in p.read_text(encoding="utf-8")
        and "NOT tracemalloc" not in p.read_text(encoding="utf-8")
        and "WHY NOT tracemalloc" not in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"tracemalloc referenced in {offenders}"


# ── report hygiene ──────────────────────────────────────────────────────────

def test_a_report_contains_no_fixture_text_or_private_paths(tmp_path):
    secret = "Zubaida Bibi of 44 Mall Road holds CNIC 35202-1234567-8"
    manifest = _dataset(
        tmp_path, fixture_text=secret, transcript_text=secret,
        critical_tokens=[{"kind": "name", "value": "Zubaida Bibi"}])

    report = run_benchmark(
        manifest, configs=(PASSTHROUGH,), capability=_capability())
    body = json.dumps(report)

    assert "Zubaida" not in body, "a critical-token value reached the report"
    assert "35202-1234567-8" not in body, "document text reached the report"
    assert "Mall Road" not in body
    assert str(tmp_path) not in body, "an absolute private path reached the report"
    assert "manifest.json" not in body


def test_the_probe_redacts_the_home_directory():
    home = str(Path.home())
    redacted = P.redact_path(str(Path.home() / "secrets" / "tool.exe"))

    assert redacted.startswith("~")
    assert home not in redacted


def test_the_probe_reports_cli_and_daemon_separately():
    """Docker CLI presence says nothing about whether a container can run."""
    docker = P.probe_docker()

    assert "cli_available" in docker
    assert "daemon_available" in docker
    if not docker["cli_available"]:
        assert docker["daemon_available"] is False


def test_the_probe_never_reports_a_language_pack_without_the_binary():
    result = P.probe_tesseract()

    if not result["available"]:
        assert result["languages_present"] == []
        assert set(result["languages_missing"]) == set(P.REQUIRED_LANGS)
