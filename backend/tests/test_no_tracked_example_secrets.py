"""No tracked example, config or documentation file may carry a real credential.

WHY THIS EXISTS

A live Atlas connection string was committed to `backend/.env.example` and sat
in a public repository until GitHub's secret scanner reported it. Redacting the
file did not undo that: the value remains in Git history, in every fork and in
every clone, so it had to be rotated. The only cheap move left is making the
same mistake impossible to commit again.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT

It reads the files people actually paste live values into - `.env.example`,
documentation, runbooks, progress notes, compose and CI config - and fails on
anything shaped like a working credential.

It does NOT scan `.env` itself. That file is gitignored, holds the real values
by design, and is none of this test's business; reading it would mean a test
that opens a secret file for no reason. The policy is an explicit ALLOWLIST of
paths, not "everything except what we remember to exclude".

It does NOT scan the test suite. Tests must be free to construct
credential-shaped strings - refusing, redacting and comparing them is the
behaviour under test - and a rule that forbade that would force the safety
tests to be weakened to satisfy the safety test. Those fixtures instead
assemble their values at run time so no scanner, this one or GitHub's, sees a
static credential.

NOTHING MATCHED IS EVER PRINTED. A failure reports path, line and category.
Echoing the match would copy the secret into CI logs, which is the same
exposure by a different route - and this file would then be the leak.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


# ── The file-scope policy ───────────────────────────────────────────────────
#
# An allowlist by suffix and by directory. A new documentation format is
# covered the moment somebody adds its extension here; nothing is covered by
# accident.
SCANNED_SUFFIXES = {".example", ".md", ".yml", ".yaml", ".toml", ".ini",
                    ".cfg", ".sh", ".ps1"}
SCANNED_NAMES = {".env.example", "env.example", "docker-compose.yml",
                 "docker-compose.yaml", "Dockerfile"}

# Never read: the real secret store, and anything generated.
EXCLUDED_PARTS = {"node_modules", ".next", "venv", ".venv", "__pycache__",
                  "dist", "build", ".pytest_cache"}

# Tests are excluded by policy, for the reason in the module docstring.
EXCLUDED_DIR_PREFIXES = ("backend/tests/", "frontend/tests/")


# ── Detection ───────────────────────────────────────────────────────────────
#
# Deliberately independent of the values any fixture uses: these patterns
# describe the SHAPE of a working credential, and are not derived from, nor
# shared with, the synthetic strings the test suite builds.
DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mongodb_uri_with_credentials",
     re.compile(r"mongodb(?:\+srv)?://[^:/@\s'\"]+:[^@/\s'\"]+@")),
    ("postgres_uri_with_credentials",
     re.compile(r"postgres(?:ql)?://[^:/@\s'\"]+:[^@/\s'\"]+@")),
    ("mysql_uri_with_credentials",
     re.compile(r"mysql://[^:/@\s'\"]+:[^@/\s'\"]+@")),
    ("redis_uri_with_credentials",
     re.compile(r"rediss?://[^:/@\s'\"]*:[^@/\s'\"]+@")),
    ("groq_api_key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack_token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private_key_block",
     re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("assigned_api_key",
     re.compile(r"(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)"
                r"\s*[:=]\s*['\"][A-Za-z0-9_\-/+]{24,}['\"]", re.I)),
    ("bearer_token", re.compile(r"[Bb]earer\s+[A-Za-z0-9._~+/-]{24,}")),
)


# ── What is unmistakably NOT a live credential ──────────────────────────────
#
# Angle-bracket tokens, the reserved domains from RFC 2606 and RFC 6761, and
# loopback. A placeholder has to stay legal: the whole point of `.env.example`
# is to show the SHAPE of the value.
INERT = re.compile(
    r"<[^>\s]{1,40}>"
    r"|example\.(?:com|net|org|invalid)"
    r"|\.invalid\b"
    r"|\blocalhost\b|127\.0\.0\.1|\[::1\]|\b0\.0\.0\.0\b"
    r"|YOUR[_-]|CHANGE[_-]?ME|REPLACE[_-]?ME"
    r"|placeholder|redacted|dummy|\bxxx+\b",
    re.I,
)


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.split("\n") if line]


def _in_scope(rel: str) -> bool:
    path = pathlib.PurePosixPath(rel)
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    if rel.startswith(EXCLUDED_DIR_PREFIXES):
        return False
    if path.name in SCANNED_NAMES:
        return True
    return path.suffix.lower() in SCANNED_SUFFIXES


def scan_line(line: str) -> list[str]:
    """Categories of live-looking credential on one line. Never returns text."""
    found = []
    for category, pattern in DETECTORS:
        for match in pattern.finditer(line):
            window = line[max(0, match.start() - 40):match.end() + 40]
            if INERT.search(match.group(0)) or INERT.search(window):
                continue
            found.append(category)
    return found


def scan_repository() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for rel in _tracked_files():
        if not _in_scope(rel):
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            for category in scan_line(line):
                findings.append((rel, lineno, category))
    return findings


# ── The guard ───────────────────────────────────────────────────────────────

def test_no_tracked_example_or_doc_file_contains_a_credential():
    findings = scan_repository()

    assert findings == [], (
        "credential-shaped values found in tracked example/config/doc files.\n"
        "Nothing matched is shown here on purpose - printing it would copy the\n"
        "secret into CI logs. Open each location and replace the value with a\n"
        "placeholder, then ROTATE it: redaction does not un-publish anything\n"
        "already committed.\n  "
        + "\n  ".join(f"{path}:{line}  [{cat}]" for path, line, cat in findings)
    )


def test_the_env_example_is_in_scope():
    """The file the incident happened in must actually be scanned."""
    assert _in_scope("backend/.env.example")


def test_the_real_env_file_is_never_read():
    """It is gitignored and holds live values; opening it would be the leak."""
    assert not _in_scope("backend/.env")
    assert not _in_scope(".env")
    assert "backend/.env" not in _tracked_files()


def test_the_test_suite_is_out_of_scope_by_policy():
    """Tests must stay free to build credential-shaped strings - refusing and
    redacting them is the behaviour under test."""
    assert not _in_scope("backend/tests/test_mongo_test_isolation.py")
    assert not _in_scope("frontend/tests/booking_time.test.mjs")


# ── The detector itself ─────────────────────────────────────────────────────

@pytest.mark.parametrize("category,sample", [
    ("mongodb_uri_with_credentials",
     "mongodb+srv://" + "dbuser" + ":" + "Pa55wordPa55word" + "@c0.aq7x1.mongodb.net"),
    ("postgres_uri_with_credentials",
     "postgresql://" + "app" + ":" + "Pa55wordPa55word" + "@db.internal:5432/x"),
    ("groq_api_key", "gsk_" + "A1b2C3d4E5f6G7h8J9k0" + "L1m2N3o4P5q6R7s8"),
    ("aws_access_key_id", "AKIA" + "IOSFODNN7EXAMPLQ"),
    ("private_key_block", "-----BEGIN RSA PRIVATE KEY-----"),
])
def test_a_live_looking_credential_is_rejected(category, sample):
    """Built from fragments so this guard's own fixtures are not a credential
    a scanner can read out of the file."""
    assert category in scan_line(sample)


@pytest.mark.parametrize("sample", [
    "MONGODB_URL=mongodb+srv://<username>:<password>@<cluster-host>/<database>",
    "MONGODB_URL=mongodb://localhost:27017",
    "MONGODB_URL=mongodb://127.0.0.1:27019/?directConnection=true",
    "REDIS_URL=rediss://default:<token>@<host>:6379",
    "DATABASE_URL=postgresql://user:password@localhost:5432/app",
    "GROQ_API_KEY=",
    "GROQ_API_KEY=your-key-here",
    "uri = 'mongodb+srv://" + "u" + ":" + "p" + "@cluster0.example.invalid'",
])
def test_a_placeholder_or_local_value_is_accepted(sample):
    """Placeholders must stay legal - showing the SHAPE of a value is what
    `.env.example` is for - and a localhost dev default is not a secret."""
    assert scan_line(sample) == []


def test_failure_output_cannot_contain_the_secret():
    """The one property this test must never get wrong.

    A guard that echoes what it found turns every CI log into a copy of the
    leak. `scan_line` returns CATEGORIES, and there is no path by which the
    matched text reaches the message.
    """
    password = "Pa55word" + "Pa55word"
    sample = "mongodb+srv://" + "dbuser" + ":" + password + "@c0.aq7x1.mongodb.net"

    categories = scan_line(sample)

    assert categories == ["mongodb_uri_with_credentials"]
    rendered = " ".join(categories)
    assert password not in rendered
    assert "dbuser" not in rendered
    assert "aq7x1" not in rendered


def test_the_detectors_do_not_reuse_fixture_values():
    """Detection must describe the SHAPE of a credential, not match the
    particular strings the test suite happens to use - otherwise renaming a
    fixture would silently disable the guard."""
    import inspect

    source = inspect.getsource(scan_line)
    for fixture_fragment in ("someone", "s3cr3t", "throwaway", "abcd"):
        assert fixture_fragment not in source
