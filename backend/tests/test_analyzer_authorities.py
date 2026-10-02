"""Document Analyzer: the authority library and what an approval binds.

Offline and deterministic: the library is a committed file built from pinned
official sources (scripts/build_analyzer_authorities.py). Re-checking it
against the live publishers is the opt-in `network` test in test_live_tier.py.

The last test is the full lifecycle of the REAL Punjab tenancy pack through
the HTTP API, with an approval that exists only in the test database:
qualification-bound approval, the pack running, the report freezing what it
applied, and each way the approval stops counting. Replica set.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import uuid
from pathlib import Path

import pytest
import yaml

from app.services.analyzer import authorities, playbook_engine as engine, runner
from app.services.analyzer.authorities import AuthorityError
from app.services.analyzer.playbook_dsl import PlaybookError
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_report import to_analysis

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


# ── footnotes are notes, never section text ──────────────────────────────────

def provision(statute, section):
    return authorities.load_library().resolve(statute, section)


def test_a_footnote_never_lands_in_another_section():
    s27, s28 = provision("Contract Act 1872", "27"), provision("Contract Act 1872", "28")
    assert "Partnership Act" not in s28.text            # s.27's footnote, once cut into s.28
    assert [n["text"] for n in s27.notes] == ["Rep. by the Partnership Act, 1932 (IX of 1932), s. 73 "
                                              "and Sch. ll."]
    assert [(n["page"], n["marker"]) for n in s28.notes] == [(23, "1")]
    assert "Specific Relief Act" in s28.notes[0]["text"]


def test_the_extent_footnotes_are_notes_beside_tpa_s1_and_s107():
    s1, s107 = provision("Transfer of Property Act 1882", "1"), provision("Transfer of Property Act 1882", "107")
    assert "Ss. 54, 107 and 123 have been extended" not in s1.text
    assert "Sections 54, paragraphs 2 and 3, 59, 107 and 123" in flat(s1.text)
    extent = next(n for n in s1.notes if (n["page"], n["marker"]) == (8, "1"))
    assert "Municipalities in the Punjab" in extent["text"] and extent["marker_in_text"] is False
    assert any("territorial operation of s. 107" in flat(n["text"]) for n in s107.notes)


def test_a_footnote_with_no_marker_on_its_page_is_shown_flagged_not_dropped():
    notes = provision("Registration Act 1908", "17(1)").notes
    orphan = next(n for n in notes if n["marker"] == "2")
    assert "Registration (Amdt) Act, 2022" in orphan["text"] and orphan["marker_in_text"] is False
    assert all(n["marker_in_text"] for n in notes if n["marker"] != "2")


def test_notes_are_hash_bound_and_part_of_the_authorities_hash(tmp_path):
    data = yaml.safe_load(RAW)
    s28 = next(p for p in data["provisions"] if (p["statute"], p["section"]) == ("Contract Act 1872", "28"))
    s28["notes"][0]["text"] = "Edited."
    path = tmp_path / "authority_library.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AuthorityError, match="notes_sha256"):
        authorities.load_library(path)
    s28["notes_sha256"] = authorities.notes_hash(s28["notes"])
    before = {pk.id: pk.authorities_hash for pk in engine.load_packs()}
    after = {pk.id: pk.authorities_hash for pk in engine.load_packs(
        library=authorities.parse_library(authorities.dump_library(data)))}
    assert after["nda"] != before["nda"] and after["tenancy_punjab"] == before["tenancy_punjab"]


# ── the real tenancy pack, end to end ────────────────────────────────────────

APPROVAL_COLLECTIONS = ("analysis_playbook_approvals", "analysis_reviewer_qualifications",
                        "analysis_approval_audit")


@pytest.fixture
async def lifecycle(http, mongo_transactional):
    db = mongo_transactional
    for name in APPROVAL_COLLECTIONS:
        await db[name].delete_many({})
    await db["analysis_runs"].delete_many({"is_open": True})
    yield http, db
    for name in APPROVAL_COLLECTIONS:
        await db[name].delete_many({})


async def person(db, role="lawyer"):
    uid = f"user-{uuid.uuid4().hex[:8]}"
    await db["users"].insert_one({"_id": uid, "email": f"{uid}@example.com", "role": role,
                                  "lawyer_profile": {"kyc_status": "approved"}})
    return {"_id": uid, "role": role, "is_active": True}


async def as_(actor, who, call):
    owner = dict(actor)
    actor.clear(); actor.update(who)
    try:
        return await call
    finally:
        actor.clear(); actor.update(owner)


async def report_for(client):
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "done"
    return (await client.get(f"/documents/analyses/runs/{created['run_id']}/report")).json()


def tenancy_status(report):
    return {p["pack_id"]: p for p in report["packs"]}["tenancy_punjab"]


async def test_the_real_tenancy_pack_from_approval_to_withdrawal(lifecycle, tmp_path):
    (client, actor), db = lifecycle
    base = "/documents/analyses"
    admin, nda_lawyer, tenancy_lawyer = await person(db, "admin"), await person(db), await person(db)
    for who, qualification in ((nda_lawyer, "pk.contract.nda"), (tenancy_lawyer, "pk.punjab.tenancy")):
        r = await as_(actor, admin, client.post(f"{base}/reviewer-qualifications", json={
            "user_id": who["_id"], "qualification": qualification, "basis": "test grant"}))
        assert r.status_code == 201, r.text
    tenancy_grant = r.json()["grant_id"]

    # The reviewer reads the pack AND the official text it cites.
    review = (await as_(actor, tenancy_lawyer, client.get(f"{base}/playbooks/tenancy_punjab"))).json()
    cited = {(c["statute"], c["section"]) for c in review["cited_provisions"]}
    assert ("Registration Act 1908", "17(1)") in cited and ("Transfer of Property Act 1882", "1") in cited
    assert all(c["source"]["url"].startswith("https://") for c in review["cited_provisions"])
    # ...and is told what each source is, how current, and what is not covered.
    assert {c["source"]["authority_status"] for c in review["cited_provisions"]} == {"official"}
    assert all(c["source"]["currency"]["caveat"] for c in review["cited_provisions"])
    assert "tenancy.stamp_duty" in {g["id"] for g in review["authority"]["coverage"]["tenancy"]["gaps"]}
    body = {"content_hash": review["content_hash"], "authorities_hash": review["authorities_hash"],
            "reviewer_role": "Advocate High Court (test)"}

    assert tenancy_status(await report_for(client))["status"] == "awaiting_approval"

    # Wrong qualification: refused.
    r = await as_(actor, nda_lawyer, client.post(f"{base}/playbooks/tenancy_punjab/approvals", json=body))
    assert r.status_code == 422 and r.json()["error"]["code"] == "reviewer_not_qualified"
    # Right qualification, but quoting cited text that is not what would run: refused.
    r = await as_(actor, tenancy_lawyer, client.post(f"{base}/playbooks/tenancy_punjab/approvals",
                                                     json={**body, "authorities_hash": "0" * 64}))
    assert r.status_code == 409 and r.json()["error"]["code"] == "hash_mismatch"
    r = await as_(actor, tenancy_lawyer, client.post(f"{base}/playbooks/tenancy_punjab/approvals", json=body))
    assert r.status_code == 201, r.text

    # Approved: the correct pack runs, and the report freezes what it applied.
    report = await report_for(client)
    applied = tenancy_status(report)
    assert applied["status"] == "applied"
    assert (applied["content_hash"], applied["authorities_hash"]) == \
           (review["content_hash"], review["authorities_hash"])
    legal = [f for f in report["legal_checks"] if f["pack_id"] == "tenancy_punjab"]
    assert legal and all(f["labels"] == ["Legal playbook applied", "Applicability requires lawyer review"]
                         for f in legal)
    rate = next(f for f in legal if f["check_id"] == "s6_rate_of_rent")
    assert rate["check_result"] == "present"
    [source] = rate["authority"]
    assert source["located"] and source["section"] == "6(1)(d)" and source["pages"] == [5]
    assert source["source"]["publisher"] == "Punjab Code, Government of the Punjab"
    assert (source["source"]["authority_status"], source["source"]["snapshot_date"]) == \
           ("official", "2026-10-01")
    layer = report["authority"]
    assert layer["available"] and len(layer["sources"]) == 4
    assert "employment.no_employment_statute" in {b["id"] for b in layer["release_blockers"]}
    frozen_run = report["id"]
    frozen = (await client.get(f"{base}/runs/{frozen_run}/report")).json()

    # The official text it cites changes: the pack stops running...
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(authorities, "LIBRARY_PATH", edited_library(
            tmp_path, "Punjab Rented Premises Act 2009", "6",
            authorities.load_library().resolve("Punjab Rented Premises Act 2009", "6").text + " (amended)"))
        assert tenancy_status(await report_for(client))["status"] == "awaiting_approval"
        # ...and the earlier report still says exactly what was applied then.
        assert (await client.get(f"{base}/runs/{frozen_run}/report")).json() == frozen

    # The pack itself is edited: it stops running.
    edited = tmp_path / "packs"
    edited.mkdir()
    for name in ("general.yaml", "tenancy_punjab.yaml"):
        (edited / name).write_text((engine.PLAYBOOK_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    with open(edited / "tenancy_punjab.yaml", "a", encoding="utf-8") as f:
        f.write("# edited\n")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine, "PLAYBOOK_DIR", edited)
        assert tenancy_status(await report_for(client))["status"] == "awaiting_approval"
    assert tenancy_status(await report_for(client))["status"] == "applied"

    # The reviewer's qualification is revoked: the approval is withdrawn with it.
    r = await as_(actor, admin, client.post(f"{base}/reviewer-qualifications/{tenancy_grant}/revoke",
                                            json={"reason": "test revocation"}))
    assert r.status_code == 200 and len(r.json()["approvals_deactivated"]) == 1
    assert tenancy_status(await report_for(client))["status"] == "awaiting_approval"

    audit = (await as_(actor, admin, client.get(f"{base}/approval-audit"))).json()
    assert [a["action"] for a in audit][:2] == ["revoke_qualification", "approve_playbook"]


async def test_reapproval_against_new_cited_text_supersedes_the_stale_one(lifecycle, tmp_path, monkeypatch):
    from app.services.analyzer import approvals

    (_, _), db = lifecycle
    admin, lawyer = await person(db, "admin"), await person(db)
    await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                        qualification="pk.punjab.tenancy", basis="test")
    pack = next(p for p in engine.load_packs() if p.id == "tenancy_punjab")
    first = await approvals.record_approval(reviewer=lawyer, pack_id=pack.id, content_hash=pack.content_hash,
                                            authorities_hash=pack.authorities_hash, reviewer_role="r")
    monkeypatch.setattr(authorities, "LIBRARY_PATH", edited_library(
        tmp_path, "Registration Act 1908", "17(1)",
        authorities.load_library().resolve("Registration Act 1908", "17(1)").text + " (amended)"))
    newer = next(p for p in engine.load_packs() if p.id == "tenancy_punjab")
    assert newer.content_hash == pack.content_hash and newer.authorities_hash != pack.authorities_hash
    second = await approvals.record_approval(reviewer=lawyer, pack_id=pack.id, content_hash=newer.content_hash,
                                             authorities_hash=newer.authorities_hash, reviewer_role="r")
    rows = {a["_id"]: a async for a in db["analysis_playbook_approvals"].find({"pack_id": pack.id})}
    assert rows[first["_id"]]["active"] is False
    assert rows[first["_id"]]["revoke_reason"] == "superseded: cited text changed"
    assert rows[second["_id"]]["active"] is True
    [entry] = [a async for a in db["analysis_approval_audit"].find({"approval_id": second["_id"]})]
    assert entry["superseded"] == [first["_id"]]


# ── authority metadata: status, snapshot, currency, coverage, blockers ───────

from datetime import date  # noqa: E402

CHECKED = date(2026, 10, 2)


def library_with(tmp_path: Path, change) -> Path:
    """A copy of the library with `change(data)` applied, written WITHOUT the
    dump-time validation, so invalid shapes can reach the parser."""
    data = yaml.safe_load(RAW)
    change(data)
    path = tmp_path / "authority_library.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def test_every_committed_source_states_its_status_and_snapshot():
    library = authorities.load_library()
    for sid, meta in library.sources.items():
        assert meta["authority_status"] == authorities.OFFICIAL
        assert meta["retrieved"] == "2026-10-01" and meta["amended_up_to"] is None
    for p in library.provisions:
        assert p.source["authority_status"] == authorities.OFFICIAL


def test_only_an_official_publisher_may_claim_official(tmp_path):
    def move(data):
        data["sources"]["contract_act_1872"]["url"] = "https://www.pakistani.org/contract-act.pdf"
    with pytest.raises(AuthorityError, match="not an official publisher"):
        authorities.load_library(library_with(tmp_path, move))


@pytest.mark.parametrize("status", [None, "unofficial", True])
def test_a_source_must_say_official_or_mirror(tmp_path, status):
    def change(data):
        data["sources"]["contract_act_1872"]["authority_status"] = status
    with pytest.raises(AuthorityError, match="official or mirror"):
        authorities.load_library(library_with(tmp_path, change))


def test_a_mirror_copy_is_readable_but_no_legal_pack_may_cite_it(tmp_path):
    def mirror(data):
        meta = data["sources"]["contract_act_1872"]
        meta["authority_status"] = authorities.MIRROR
        meta["url"] = "https://www.pakistani.org/contract-act.pdf"
    library = authorities.load_library(library_with(tmp_path, mirror))
    assert library.resolve("Contract Act 1872", "27").source["authority_status"] == authorities.MIRROR
    with pytest.raises(PlaybookError, match="from a mirror copy"):
        engine.load_packs(library=library)              # nda and employment cite s.27
    assert {"mirror:contract_act_1872"} <= {b["id"] for b in authorities.release_blockers(
        library, {}, CHECKED)}


@pytest.mark.parametrize("change, message", [
    (lambda d: d.pop("coverage"), "coverage must list"),
    (lambda d: d["coverage"]["nda"]["statutes"].append("Specific Relief Act 1877"), "not in the library"),
    (lambda d: d["coverage"]["nda"]["gaps"].append({"id": "x", "text": "y"}), "release_blocker"),
    (lambda d: d["coverage"]["nda"]["gaps"].append(dict(d["coverage"]["tenancy"]["gaps"][0])),
     "duplicate gap id"),
    (lambda d: d["sources"]["contract_act_1872"].update(amended_up_to="soon"), "amended_up_to"),
])
def test_malformed_metadata_fails_closed(tmp_path, change, message):
    with pytest.raises(AuthorityError, match=message):
        authorities.load_library(library_with(tmp_path, change))


def test_coverage_and_currency_are_what_the_build_script_writes():
    spec = importlib.util.spec_from_file_location(
        "build_analyzer_authorities", BACKEND / "scripts" / "build_analyzer_authorities.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    library = authorities.load_library()
    assert library.coverage == script.COVERAGE
    raw = yaml.safe_load(authorities.CURRENCY_PATH.read_text(encoding="utf-8"))
    assert {sid: e["pinned_sha256"] for sid, e in raw["sources"].items()} == \
           {sid: m["sha256"] for sid, m in library.sources.items()}


def test_the_committed_currency_check_and_the_blockers_it_leaves():
    library = authorities.load_library()
    currency = authorities.load_currency(library)
    meta = authorities.metadata(library, currency, CHECKED)
    for source in meta["sources"]:
        assert source["authority_status"] == authorities.OFFICIAL
        assert source["snapshot_date"] == "2026-10-01" and source["amended_up_to"] is None
        assert source["currency"]["status"] == authorities.SOURCE_UNCHANGED
        assert source["currency"]["last_checked"] == "2026-10-02"
        assert "does not confirm that no later amendment exists" in source["currency"]["caveat"]
    # Only the missing employment law is left: the sources were re-checked.
    assert [b["id"] for b in meta["release_blockers"]] == ["employment.no_employment_statute"]


def test_currency_goes_stale_and_is_said_when_never_checked(tmp_path):
    library = authorities.load_library()
    currency = authorities.load_currency(library)
    late = date(2027, 6, 1)
    assert {s["currency"]["status"] for s in authorities.metadata(library, currency, late)["sources"]} \
        == {authorities.STALE}
    assert len([b for b in authorities.release_blockers(library, currency, late)
                if b["kind"] == "currency"]) == 4
    missing = authorities.load_currency(library, tmp_path / "absent.yaml")
    assert missing == {}
    states = authorities.metadata(library, missing, CHECKED)["sources"]
    assert {(s["currency"]["status"], s["currency"]["last_checked"]) for s in states} == \
           {(authorities.NOT_CHECKED, None)}


def test_a_changed_or_unreachable_source_is_a_blocker_and_an_old_pin_says_nothing(tmp_path):
    library = authorities.load_library()
    data = yaml.safe_load(authorities.CURRENCY_PATH.read_text(encoding="utf-8"))
    data["sources"]["registration_act_1908"].update(status=authorities.SOURCE_CHANGED,
                                                    observed_sha256="1" * 64)
    data["sources"]["contract_act_1872"]["status"] = authorities.CHECK_FAILED
    data["sources"]["transfer_of_property_act_1882"]["pinned_sha256"] = "2" * 64   # an older pin
    currency = authorities.parse_currency(yaml.safe_dump(data), library)
    blockers = {b["id"]: b["reason"] for b in authorities.release_blockers(library, currency, CHECKED)}
    assert blockers["currency:registration_act_1908"].endswith("currency source_changed (last checked 2026-10-02)")
    assert "check_failed" in blockers["currency:contract_act_1872"]
    assert "not_checked" in blockers["currency:transfer_of_property_act_1882"]
    assert "currency:punjab_rented_premises_act_2009" not in blockers
    with pytest.raises(AuthorityError, match="unknown source"):
        authorities.parse_currency(yaml.safe_dump({"version": 1, "sources": {"nope": {}}}), library)


def test_a_finding_freezes_the_source_status_and_snapshot_date():
    pack = next(p for p in engine.load_packs() if p.id == "tenancy_punjab")
    for check in pack.checks:
        for source in check.sources:
            assert source["source"]["authority_status"] == authorities.OFFICIAL
            assert source["source"]["snapshot_date"] == "2026-10-01"
            assert source["source"]["amended_up_to"] is None


def test_an_unusable_library_is_reported_as_a_blocker(tmp_path, monkeypatch):
    bad = tmp_path / "authority_library.yaml"
    bad.write_text("version: 2\n", encoding="utf-8")
    monkeypatch.setattr(authorities, "LIBRARY_PATH", bad)
    meta = authorities.current_metadata()
    assert meta["available"] is False and meta["release_blockers"][0]["id"] == "library_unusable"
