"""Parser tests against a real LHC cause-list response (captured 2026-07-05).

Run directly (`python tests/test_causelist_parser.py`) or via `pytest` — both
work without setting PYTHONPATH.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.causelist_service import extract_case_nos, normalize_case_no, parse_lhc  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "lhc_causelist_sample.html"


def test_parse_real_lhc_response():
    entries = parse_lhc(FIXTURE.read_text(encoding="utf-8"))
    assert len(entries) == 2

    main = entries[0]
    assert main["case_no"] == "39043/26"
    assert main["hearing_date"] == "2026-07-06"
    assert main["bench"] == "Single Bench"
    assert main["judge"] == "The Chief Justice"
    assert main["court_room"] == "Chief Justice Block - Court 1"
    assert main["seq"] == "1"
    assert main["connected"] is False
    assert "Vs" in main["title"]
    assert main["list_type"] == "Regular Cause List"

    connected = entries[1]
    assert connected["connected"] is True
    assert "39043/26" in extract_case_nos(connected["case_no_raw"])


def test_normalize_case_no():
    assert normalize_case_no("39043/26") == "39043/26"
    assert normalize_case_no("39043/2026") == "39043/26"
    assert normalize_case_no(" W.P. 1234/25 ") == "1234/25"
    assert normalize_case_no("CM/1/39043/26") == "39043/26"
    assert normalize_case_no("39043 / 26") == "39043/26"


def test_extract_case_nos_composite():
    assert extract_case_nos("CM/1/39043/26") == {"39043/26"}
    assert "555/24" in extract_case_nos("W.P. 555/2024 with C.M. 12/26")


if __name__ == "__main__":
    test_parse_real_lhc_response()
    test_normalize_case_no()
    test_extract_case_nos_composite()
    print("test_causelist_parser: 3 passed")
