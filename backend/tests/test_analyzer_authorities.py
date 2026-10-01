"""Document Analyzer: the authority library and what an approval binds.

Offline and deterministic: the library is a committed file built from pinned
official sources (scripts/build_analyzer_authorities.py). Re-checking it
against the live publishers is the opt-in `network` test in test_live_tier.py.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from app.services.analyzer import authorities, playbook_engine as engine
from app.services.analyzer.authorities import AuthorityError
from app.services.analyzer.playbook_dsl import PlaybookError

BACKEND = Path(__file__).resolve().parents[1]
RAW = authorities.LIBRARY_PATH.read_text(encoding="utf-8")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def edited_library(tmp_path: Path, statute: str, section: str, new_text: str) -> Path:
    """A copy of the library with one provision's text changed AND re-hashed."""
    data = yaml.safe_load(RAW)
    for p in data["provisions"]:
        if (p["statute"], p["section"]) == (statute, section):
            p["text"] = new_text
            p["text_sha256"] = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
    path = tmp_path / "authority_library.yaml"
    path.write_text(authorities.dump_library(data), encoding="utf-8")
    return path


# ── the library ──────────────────────────────────────────────────────────────

def test_the_library_loads_from_official_sources_only():
    library = authorities.load_library()
    assert len(library.provisions) == 8
    for p in library.provisions:
        assert hashlib.sha256(p.text.encode("utf-8")).hexdigest() == p.text_sha256
        assert p.source["url"].startswith(("https://punjabcode.punjab.gov.pk/",
                                           "https://pakistancode.gov.pk/"))
        assert re.fullmatch(r"[0-9a-f]{64}", p.source["sha256"]) and p.pages


def test_the_committed_library_is_exactly_what_the_build_script_writes():
    """Same pins as the script, and a deterministic, byte-stable rendering:
    nobody edited the generated file by hand."""
    spec = importlib.util.spec_from_file_location(
        "build_analyzer_authorities", BACKEND / "scripts" / "build_analyzer_authorities.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    data = yaml.safe_load(RAW)
    assert {k: v["sha256"] for k, v in data["sources"].items()} == \
           {k: v["sha256"] for k, v in script.SOURCES.items()}
    assert [(p["statute"], p["section"]) for p in data["provisions"]] == \
           [(script.SOURCES[s]["statute"], sec) for s, sec, *_ in script.PROVISIONS]
    assert authorities.dump_library(data) == RAW.replace("\r\n", "\n")


def test_the_official_text_corrects_the_secondary_copy():
    """The first draft quoted a secondary site that read 'mode of payment or
    rent'. The official Punjab Code text reads 'of rent'."""
    s6 = flat(authorities.load_library().resolve("Punjab Rented Premises Act 2009", "6(1)(d)").text)
    assert "rate of rent, rate of enhancement, due date and mode of payment of rent;" in s6
    assert "payment or rent" not in s6
    assert "the purpose for which the premises is let out; and" in s6


@pytest.mark.parametrize("statute, section, expected", [
    ("Registration Act 1908", "17(1)(d)", "17(1)"),        # longest prefix, (d) in text
    ("Registration Act 1908", "17(1)", "17(1)"),
    ("Registration Act 1908", "17", None),                 # only 17(1) is held
    ("Registration Act 1908", "17(1)(z)", None),           # no clause (z)
    ("Punjab Rented Premises Act 2009", "6(1)(g)", "6"),
    ("Punjab Rented Premises Act 2009", "5(7)", None),     # s.5 has six sub-sections
    ("Punjab Rented Premises Act 2009", "9", None),        # not in the library
    ("Contract Act 1872", "27", "27"),
    ("Contract Act 1872", "27)", None),                    # malformed
    ("Contract Act, 1872", "27", None),                    # statute names are exact
])
def test_how_a_citation_resolves(statute, section, expected):
    found = authorities.load_library().resolve(statute, section)
    assert (found.section if found else None) == expected


def test_a_hand_edited_text_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "authority_library.yaml"
    path.write_text(RAW.replace("not later than tenth day", "not later than fifteenth day"),
                    encoding="utf-8")
    with pytest.raises(AuthorityError, match="text_sha256"):
        authorities.load_library(path)
    monkeypatch.setattr(authorities, "LIBRARY_PATH", path)
    with pytest.raises(PlaybookError, match="authority library unusable"):
        engine.load_packs()              # the analysis run then fails as playbook_invalid


def test_a_pack_citing_text_not_in_the_library_does_not_load(tmp_path, monkeypatch):
    raw = (engine.PLAYBOOK_DIR / "nda.yaml").read_text(encoding="utf-8")
    (tmp_path / "nda.yaml").write_text(
        raw.replace("section: \"28\"", "section: \"29\"", 1), encoding="utf-8")
    assert (tmp_path / "nda.yaml").read_text(encoding="utf-8") != raw
    monkeypatch.setattr(engine, "PLAYBOOK_DIR", tmp_path)
    with pytest.raises(PlaybookError, match="s.29, which is not in the authority library"):
        engine.load_packs()


def test_the_authorities_hash_follows_only_the_cited_text(tmp_path):
    before = {p.id: p.authorities_hash for p in engine.load_packs()}
    changed = authorities.load_library(edited_library(
        tmp_path, "Punjab Rented Premises Act 2009", "7", "7. Payment of rent.– (1) changed (2) (3)"))
    after = {p.id: p.authorities_hash for p in engine.load_packs(library=changed)}
    assert after["tenancy_punjab"] != before["tenancy_punjab"]          # cites s.7(2), 7(3)
    assert after["nda"] == before["nda"] and after["employment"] == before["employment"]

