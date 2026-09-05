"""Faraid engine — the classical cases, one named test per doctrine.

Run: ./venv/Scripts/python.exe -m pytest tests/test_inheritance.py -q
 (or plain: ./venv/Scripts/python.exe tests/test_inheritance.py)

WHY ONE TEST PER CASE

These eleven cases are eleven separate doctrines — `awl`, `radd`, the
`umariyyatan`, representation under MFLO 1961 s.4, sisters taking as `asaba
ma'a al-ghayr`. They used to run inside a single `test_classical_cases()` that
accumulated failures into a list and asserted once at the end, so a regression
in `radd` reported as "1 failed" and you had to read the assertion text to learn
which doctrine had broken, and pytest could tell you nothing about how many were
affected.

That matters more here than in most modules: this engine is the most reused in
the app — `wasiyyat` delegates its entire step 4 to it — so a change made for
one caller can quietly move a share for every other. Parametrising means the
failing doctrine is in the test NAME, and eleven broken doctrines look different
from one.

WHY THE HEIR ROSTER IS CHECKED SEPARATELY FROM THE SHARES

A missing heir and a wrong fraction are different bugs with different causes,
and the old helper could not tell them apart: it scanned the breakdown for a row
whose label started with the expected prefix and returned `Fraction(0)` when it
found none. An heir dropped from the distribution entirely was therefore
reported as "expected 1/4, got 0" — the same message a share-calculation bug
produces.

Prefix matching was also too loose to trust. `startswith("Daughter")` matches a
row labelled "Daughters", so an engine that pluralised a sole daughter — giving
her the two-daughters share of 2/3 rather than 1/2 — would still have satisfied
a test looking for "Daughter". Labels are compared exactly now, including the
statutory citation on the MFLO row: that citation names the authority the share
rests on, so changing it SHOULD require changing this file.
"""

import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.inheritance import calculate  # noqa: E402

ESTATE = 1_000_000


@dataclass(frozen=True)
class Case:
    """One classical distribution with a known, citable answer.

    `shares` maps the EXACT breakdown label to the share that heir takes.
    `doctrine` says why — so a reader who does not know Faraid can tell whether
    a failure means the engine is wrong or the expectation was.
    """

    label: str
    heirs: dict
    shares: dict
    doctrine: str


CASES = [
    Case(
        label="husband + son",
        heirs={"husband": 1, "sons": 1},
        shares={"Husband": Fraction(1, 4), "Son": Fraction(3, 4)},
        doctrine="Husband takes 1/4 because a child survives (1/2 if none). "
                 "The son is `asaba` and takes the residue.",
    ),
    Case(
        label="wife + 2 sons + 1 daughter",
        heirs={"wives": 1, "sons": 2, "daughters": 1},
        shares={"Wife": Fraction(1, 8), "Sons": Fraction(7, 10),
                "Daughter": Fraction(7, 40)},
        doctrine="Wife takes 1/8 with children. The remaining 7/8 splits among "
                 "the children 2:1 male:female — five shares, so each son takes "
                 "2/5 of 7/8 and the daughter 1/5 of 7/8.",
    ),
    Case(
        label="umariyyatan",
        heirs={"husband": 1, "mother": 1, "father": 1},
        shares={"Husband": Fraction(1, 2), "Mother": Fraction(1, 6),
                "Father": Fraction(1, 3)},
        doctrine="The 'Umar case': with a spouse and both parents and no "
                 "children, the mother takes a third OF THE RESIDUE after the "
                 "spouse, not a third of the estate — 1/3 of 1/2 = 1/6.",
    ),
    Case(
        label="awl: husband + 2 sisters",
        heirs={"husband": 1, "full_sisters": 2},
        shares={"Husband": Fraction(3, 7), "Full sisters": Fraction(4, 7)},
        doctrine="Fixed shares over-subscribe: 1/2 + 2/3 = 7/6. Under `awl` the "
                 "denominator rises to 7 and every share is scaled down "
                 "proportionally rather than anyone being cut.",
    ),
    Case(
        label="radd: mother + daughter",
        heirs={"mother": 1, "daughters": 1},
        shares={"Mother": Fraction(1, 4), "Daughter": Fraction(3, 4)},
        doctrine="Fixed shares under-subscribe: 1/6 + 1/2 = 2/3, and there is no "
                 "`asaba`. Under `radd` the surplus returns to the sharers in "
                 "proportion — 1:3.",
    ),
    Case(
        label="radd excludes spouse",
        heirs={"wives": 1, "daughters": 1},
        shares={"Wife": Fraction(1, 8), "Daughter": Fraction(7, 8)},
        doctrine="A spouse never takes by `radd`. The wife keeps exactly her "
                 "1/8 and the whole surplus returns to the daughter.",
    ),
    Case(
        label="father + mother + 2 daughters",
        heirs={"father": 1, "mother": 1, "daughters": 2},
        shares={"Mother": Fraction(1, 6), "Father": Fraction(1, 6),
                "Daughters": Fraction(2, 3)},
        doctrine="Two or more daughters share 2/3. Each parent takes 1/6 with "
                 "children, which exactly exhausts the estate.",
    ),
    Case(
        label="MFLO 1961 s.4",
        heirs={"wives": 1, "sons": 1, "predeceased_sons": 1},
        shares={"Wife": Fraction(1, 8), "Son": Fraction(7, 16),
                "Children of predeceased son (MFLO 1961 s.4)": Fraction(7, 16)},
        doctrine="Muslim Family Laws Ordinance 1961 s.4: the children of a "
                 "predeceased son take by representation the share he would "
                 "have taken. A Pakistani statutory departure from classical "
                 "Faraid, which excludes them entirely.",
    ),
    Case(
        label="daughter + full brother",
        heirs={"daughters": 1, "full_brothers": 1},
        shares={"Daughter": Fraction(1, 2), "Full brother": Fraction(1, 2)},
        doctrine="A sole daughter takes 1/2 as a fixed share. The brother is "
                 "`asaba` and takes what is left.",
    ),
    Case(
        label="wife + father, no children",
        heirs={"wives": 1, "father": 1},
        shares={"Wife": Fraction(1, 4), "Father": Fraction(3, 4)},
        doctrine="No children, so the wife takes 1/4 rather than 1/8. The "
                 "father takes the residue as `asaba`.",
    ),
    Case(
        label="sisters as asaba ma'a al-ghayr",
        heirs={"daughters": 2, "full_sisters": 1},
        shares={"Daughters": Fraction(2, 3), "Full sister": Fraction(1, 3)},
        doctrine="With daughters present, a full sister stops being a sharer "
                 "and becomes `asaba ma'a al-ghayr` — residuary alongside them "
                 "— taking what remains after their 2/3.",
    ),
]

IDS = [c.label for c in CASES]


def _breakdown(case: Case) -> dict:
    """The engine's answer, as {exact heir label: Fraction}."""
    result = calculate(ESTATE, case.heirs)
    return {row["heir"]: Fraction(row["fraction"]) for row in result["breakdown"]}


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_every_heir_is_present_exactly_once(case: Case):
    """The roster, before the arithmetic.

    Checked separately because an heir dropped from the distribution is a
    different bug from an heir given the wrong share, and the old helper
    reported both as "expected 1/4, got 0".
    """
    result = calculate(ESTATE, case.heirs)
    labels = [row["heir"] for row in result["breakdown"]]

    assert sorted(labels) == sorted(case.shares), (
        f"{case.label}: heirs differ.\n"
        f"  missing: {sorted(set(case.shares) - set(labels))}\n"
        f"  extra  : {sorted(set(labels) - set(case.shares))}\n"
        f"  {case.doctrine}")
    assert len(labels) == len(set(labels)), \
        f"{case.label}: an heir appears twice in the breakdown — {labels}"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_each_share_is_the_classical_fraction(case: Case):
    """The numbers themselves, exactly — no float comparison anywhere."""
    got = _breakdown(case)
    wrong = {label: (want, got.get(label))
             for label, want in case.shares.items() if got.get(label) != want}

    assert not wrong, (
        f"{case.label}: "
        + "; ".join(f"{label} expected {want}, got {actual}"
                    for label, (want, actual) in sorted(wrong.items()))
        + f"\n  {case.doctrine}")


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_shares_exhaust_the_estate(case: Case):
    """Sum to exactly 1 — the invariant `awl` and `radd` exist to preserve.

    Its own test because a total that is not 1 means the normalisation itself
    is wrong, which is a different fault from any individual share being
    miscalculated, and it is the one that silently creates or destroys estate.
    """
    total = sum(_breakdown(case).values())
    assert total == Fraction(1), (
        f"{case.label}: shares sum to {total}, not 1 — the estate is "
        f"{'over' if total > 1 else 'under'}-distributed.\n  {case.doctrine}")


def test_every_case_carries_its_doctrine():
    """No case may be added without saying why its answer is what it is.

    An expectation table nobody can check is a table that gets 'fixed' to match
    whatever the engine currently returns.
    """
    for case in CASES:
        assert case.doctrine.strip(), f"{case.label} has no doctrine note"
        assert case.shares, f"{case.label} expects no shares"


def run_all():
    """Every failure across every case — for the __main__ runner below."""
    fails = []
    for case in CASES:
        got = _breakdown(case)
        if sorted(got) != sorted(case.shares):
            fails.append(f"{case.label}: heirs differ — got {sorted(got)}, "
                         f"expected {sorted(case.shares)}")
        for label, want in case.shares.items():
            actual = got.get(label)
            if actual != want:
                fails.append(f"{case.label}: {label} expected {want}, got {actual}")
        total = sum(got.values())
        if total != Fraction(1):
            fails.append(f"{case.label}: shares sum to {total}, not 1")
    return fails


if __name__ == "__main__":
    problems = run_all()
    for p in problems:
        print("FAIL:", p)
    print("ALL PASS" if not problems else f"{len(problems)} failures")
    sys.exit(1 if problems else 0)
