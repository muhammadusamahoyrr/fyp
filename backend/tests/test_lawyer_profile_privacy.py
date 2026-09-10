"""A lawyer's profile vector must not carry their clients' words.

`build_profile_text` used to embed the client's own case description verbatim:

    parts.append("Past cases handled: " + " | ".join(summaries))   # 150 chars each

Those are clients writing about their legal problems — a divorce, a criminal
charge, a debt — and Chroma stores the profile text in PLAINTEXT in the
`documents` field beside the vector. So one person's account of the worst thing
happening to them became part of a different person's searchable profile,
readable by anyone holding the database file, with no consent and no way to
withdraw it.

The fix is a whitelist, not a redaction pass. Every token that can reach a
profile is either a constant from `_DOMAIN_TERMS` / `_STATUTE_ALIASES` or a
section number matched by a digit-bounded pattern anchored to a known statute.
Stripping names, CNICs and phone numbers instead would have been the obvious
approach and would leak forever — there is always another identifier. A
whitelist cannot leak, because there is no path from arbitrary text to output.

These are pure unit tests: no database, no ChromaDB, no model.
"""
from app.ai.lawyer_embeddings import build_profile_text, case_domain_terms

# One realistic, hostile case description. Every element here is something a
# distressed client genuinely types into an intake form.
_SENSITIVE = {
    "case_type": "criminal",
    "title": "FIR quashment for my brother Imran",
    "description": (
        "My name is Ayesha Bibi, CNIC 35202-1234567-8, mobile 0300-1234567, "
        "living at House 12 Model Town Lahore. My husband beat me and the "
        "police registered a false FIR under PPC 380 against my brother "
        "Imran Shah. We paid 50000 rupees to the SHO. We need pre-arrest bail."
    ),
}

_IDENTIFIERS = [
    "ayesha", "bibi", "imran", "shah",          # names
    "35202", "1234567",                          # CNIC
    "0300",                                      # phone
    "house 12", "model town",                    # address
    "50000",                                     # amount
    "my name", "my husband", "my brother",       # first-person narrative
    "sho", "beat me", "rupees",
]


def test_no_identifier_from_a_case_reaches_the_profile():
    """The whole point. Nothing that identifies the client, their family, their
    address, their money or their story may appear in a lawyer's profile."""
    lawyer = {
        "province": "punjab",
        "lawyer_profile": {"specializations": ["criminal"],
                           "experience_years": 8,
                           "bio": "Advocate, Lahore High Court."},
    }
    text = build_profile_text(lawyer, [_SENSITIVE]).lower()

    leaked = [w for w in _IDENTIFIERS if w in text]
    assert not leaked, f"client data reached the profile vector: {leaked}"


def test_the_verbatim_description_block_is_gone():
    """Pin the exact shape of the defect so it cannot come back by name."""
    lawyer = {"province": "punjab", "lawyer_profile": {"specializations": ["criminal"]}}
    text = build_profile_text(lawyer, [_SENSITIVE])

    assert "Past cases handled" not in text
    assert _SENSITIVE["description"][:40] not in text


def test_the_domain_signal_survives():
    """Privacy must not be bought by making the vector useless. This is the
    EF_in_Legal_CQA property the design note claims: a lawyer is described by
    the work they have done, not only the labels they chose."""
    terms = case_domain_terms([_SENSITIVE])

    for expected in ("criminal", "fir", "bail", "pre-arrest bail", "quashment"):
        assert expected in terms, f"lost domain signal: {expected}"


def test_a_statute_reference_survives_as_a_citation():
    terms = case_domain_terms([_SENSITIVE])
    assert "PPC 380" in terms


def test_a_statute_year_is_not_read_as_a_section():
    """"PPC 1860" is the statute's year. Emitting it as a section would put a
    fabricated authority into a lawyer's profile — the citation checker excludes
    years for the same reason."""
    terms = case_domain_terms([{
        "case_type": "criminal",
        "description": "Matters under PPC 1860 and the CrPC 1898.",
    }])
    assert "PPC 1860" not in terms
    assert "CrPC 1898" not in terms


def test_a_bare_number_in_prose_does_not_become_a_citation():
    """The section pattern is anchored to a known statute precisely so that a
    number the client happened to write cannot be promoted into a legal
    reference."""
    terms = case_domain_terms([{
        "case_type": "civil",
        "description": "He owes me 302 thousand rupees and I paid 420 in fees.",
    }])
    assert not [t for t in terms if any(ch.isdigit() for ch in t)]


def test_a_lettered_section_is_canonicalised():
    terms = case_domain_terms([{
        "case_type": "criminal",
        "description": "Dishonoured cheque case under PPC 489-F.",
    }])
    assert "PPC 489-F" in terms


def test_extraction_is_deterministic():
    """The embedding is only stable if its input is. Two calls on the same
    cases must produce the same string, in the same order."""
    cases = [_SENSITIVE, {"case_type": "family", "description": "khula and dower"}]
    assert case_domain_terms(cases) == case_domain_terms(cases)


def test_terms_are_deduplicated_across_cases():
    same = {"case_type": "criminal", "description": "bail after FIR"}
    terms = case_domain_terms([same, same, same])
    assert terms.count("bail") == 1
    assert terms.count("fir") == 1


def test_a_case_with_no_usable_text_contributes_nothing_but_its_type():
    terms = case_domain_terms([{"case_type": "civil", "title": "", "description": ""}])
    assert terms == ["civil"]


def test_no_cases_produces_no_clause():
    lawyer = {"province": "punjab", "lawyer_profile": {"specializations": ["civil"]}}
    text = build_profile_text(lawyer, [])
    assert "Experienced in matters involving" not in text


def test_only_the_five_most_recent_cases_are_read():
    """Bounded work per embed, and bounded exposure surface."""
    cases = [{"case_type": "criminal", "description": "bail"} for _ in range(3)]
    cases.append({"case_type": "family", "description": "khula"})
    cases.append({"case_type": "civil", "description": "ejectment"})
    cases.append({"case_type": "constitutional", "description": "writ mandamus"})

    terms = case_domain_terms(cases)
    assert "writ" not in terms, "read past the fifth case"
    assert "ejectment" in terms


def test_the_lawyers_own_bio_is_still_embedded():
    """Only the CLIENT's words are excluded. A lawyer's bio is their own text,
    written for a profile meant to be read."""
    lawyer = {
        "province": "sindh",
        "lawyer_profile": {"specializations": ["family"],
                           "bio": "Twenty years before the Sindh High Court."},
    }
    text = build_profile_text(lawyer, [])
    assert "Twenty years before the Sindh High Court." in text
