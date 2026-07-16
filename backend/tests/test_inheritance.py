"""Faraid engine tests — classical cases with known answers.

Run: ./venv/Scripts/python.exe -m pytest tests/test_inheritance.py -q
 (or plain: ./venv/Scripts/python.exe tests/test_inheritance.py)
"""

import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.inheritance import calculate  # noqa: E402

# (heirs, {exact row label prefix: fraction}, label)
CASES = [
    ({"husband": 1, "sons": 1}, {"Husband": Fraction(1, 4), "Son": Fraction(3, 4)}, "husband + son"),
    ({"wives": 1, "sons": 2, "daughters": 1},
     {"Wife": Fraction(1, 8), "Sons": Fraction(7, 10), "Daughter": Fraction(7, 40)},
     "wife + 2 sons + 1 daughter"),
    ({"husband": 1, "mother": 1, "father": 1},
     {"Husband": Fraction(1, 2), "Mother": Fraction(1, 6), "Father": Fraction(1, 3)},
     "umariyyatan"),
    ({"husband": 1, "full_sisters": 2},
     {"Husband": Fraction(3, 7), "Full sisters": Fraction(4, 7)},
     "awl: husband + 2 sisters"),
    ({"mother": 1, "daughters": 1},
     {"Mother": Fraction(1, 4), "Daughter": Fraction(3, 4)},
     "radd: mother + daughter"),
    ({"wives": 1, "daughters": 1},
     {"Wife": Fraction(1, 8), "Daughter": Fraction(7, 8)},
     "radd excludes spouse"),
    ({"father": 1, "mother": 1, "daughters": 2},
     {"Father": Fraction(1, 6), "Mother": Fraction(1, 6), "Daughters": Fraction(2, 3)},
     "father + mother + 2 daughters"),
    ({"wives": 1, "sons": 1, "predeceased_sons": 1},
     {"Wife": Fraction(1, 8), "Son": Fraction(7, 16), "Children of predeceased son": Fraction(7, 16)},
     "MFLO 1961 s.4"),
    ({"daughters": 1, "full_brothers": 1},
     {"Daughter": Fraction(1, 2), "Full brother": Fraction(1, 2)},
     "daughter + full brother"),
    ({"wives": 1, "father": 1},
     {"Wife": Fraction(1, 4), "Father": Fraction(3, 4)},
     "wife + father, no children"),
    ({"daughters": 2, "full_sisters": 1},
     {"Daughters": Fraction(2, 3), "Full sister": Fraction(1, 3)},
     "sisters as asaba ma'a al-ghayr"),
]


def _frac_of(res, prefix):
    for r in res["breakdown"]:
        if r["heir"].startswith(prefix):
            return Fraction(r["fraction"])
    return Fraction(0)


def run_all():
    fails = []
    for heirs, expected, label in CASES:
        res = calculate(1_000_000, heirs)
        total = sum(Fraction(r["fraction"]) for r in res["breakdown"])
        if total != 1:
            fails.append(f"{label}: shares sum to {total}, not 1")
        for prefix, want in expected.items():
            got = _frac_of(res, prefix)
            if got != want:
                fails.append(f"{label}: {prefix} expected {want}, got {got}")
    return fails


def test_classical_cases():
    fails = run_all()
    assert not fails, "\n".join(fails)


if __name__ == "__main__":
    problems = run_all()
    for p in problems:
        print("FAIL:", p)
    print("ALL PASS" if not problems else f"{len(problems)} failures")
    sys.exit(1 if problems else 0)
