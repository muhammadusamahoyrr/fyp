"""No user-facing string may claim a security or legal property we cannot back.

WHY THIS EXISTS
---------------
The agreements signing flow told users, in the panel where they draw their
signature:

    "AES-256 encrypted · Timestamped · Compliant with e-signature laws."

Two separate claims, both unsupported. Signatures were -- and until Phase 4
still are -- stored as plaintext base64 by
`agreement_repo.update_party_signature`. The only encryption in the system is
Fernet (AES-128-CBC + HMAC-SHA256) over CNICs, so the cipher was wrong even
where encryption was genuinely applied. And whether an instrument complies with
ETO 2002 is a legal conclusion that no lawyer has reviewed.

The claim had spread to four places before anyone noticed, including a code
comment on `models/user.py` that was the seed the UI strings grew back from.
Deleting four strings is easy; keeping them deleted is what this test is for.

A false claim about persistence is the same class of error, so "Draft saved" is
here too: that string came from an `alert("Draft saved!")` on a button that
saved nothing.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
Scanning is by an EXPLICIT ALLOWLIST of roots and suffixes, not "everything
except what we remember to exclude" -- the same policy as
`test_no_tracked_example_secrets.py`, for the same reason.

It does NOT scan the test suite, and this file is the reason why. A guard that
forbids a string must itself contain that string, so a rule that scanned tests
would force this test to be weakened to satisfy itself.

COMMENT SPANS ARE MASKED, AND THAT IS THE POINT
-----------------------------------------------
The first version scanned every line and immediately failed on the notes
explaining the removals -- including the `models/user.py` comment the plan
specifically asks to keep, because naming the real primitive is what stops the
wrong one coming back.

A claim is dangerous when a USER reads it. A developer reading "this used to say
the wrong cipher, here is why" is the mechanism working, not failing. So the
policy is: a comment may name a claim in order to refuse it; a rendered string
may not make one.

MASKING SPANS, NOT EXEMPTING LINES. The second version exempted any line that
*began* like a comment, which was bypassable in one line:

    /* explanation */ <div>[the claim]</div>

Comment spans are now blanked in place, so code after an inline block close is
still scanned and still reports its true line number. `#` is treated as a
comment only in .py, because JavaScript private fields (`#total`) start with `#`
and blanking them would hide whatever followed. `://` is excluded from the `//`
rule so a URL in a string does not blank the rest of a rendered line.

The honest limit: this is lexical, not semantic. It cannot tell a true comment
from a false one, so an inaccurate comment is a review matter, not a test
failure. Nor does it parse string literals, so a `/*` inside a quoted string
would mask from there. What it does guarantee is that the claims listed below
cannot reach a user's screen unnoticed.

EACH RULE IS PATH-SCOPED
------------------------
The first version also forbade "Draft saved" everywhere and tripped on
`DocAutomationPage.jsx`, where lawyer document drafts really do persist via
`saveDocDraft` -- a TRUE claim. A guard that forbids true statements gets
disabled, so each rule names the paths where the capability is absent.

It does NOT forbid the underlying capability. When signature encryption is
implemented (Phase 4.2) and reviewed wording exists for ETO 2002 (Phase 4.1),
delete the relevant entry here in the SAME commit that makes the claim true --
never add an inline exemption. An exemption would let the claim return without
the capability, which is exactly the failure this guards.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

# ── File-scope policy: an explicit allowlist ────────────────────────────────
SCANNED_ROOTS = ("frontend/src", "backend/app")
SCANNED_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".py"}

EXCLUDED_PARTS = {"node_modules", ".next", "venv", ".venv", "__pycache__",
                  "dist", "build", ".pytest_cache"}

# Tests are excluded by policy -- see the module docstring.
EXCLUDED_DIR_PREFIXES = ("backend/tests/", "frontend/tests/")


def _strip_comments(text: str, suffix: str) -> list[str]:
    """Return each line with its comment SPANS blanked, code preserved.

    WHY SPANS, NOT LINES
    --------------------
    Two earlier versions exempted a whole line whenever it *started* like a
    comment. Both were bypassable:

        /* explanation */ <div>AES-256 encrypted</div>

    starts with `/*`, so the entire line -- including the rendered claim after
    the close -- was exempt. A guard with a one-line bypass is worse than none,
    because it is trusted.

    Masking preserves position, so a claim after a block close is still scanned
    and still reports its real line number.

    `#` IS PYTHON-ONLY
    ------------------
    JavaScript private fields (`#count`, `this.#total`) begin with `#`, so
    treating it as a comment marker in .js/.jsx would blank real code and hide
    anything on those lines.
    """
    is_python = suffix == ".py"
    out: list[str] = []
    in_block = False

    for raw in text.splitlines():
        buf = list(raw)
        i, n = 0, len(raw)
        while i < n:
            if in_block:
                if raw.startswith("*/", i):
                    buf[i] = buf[i + 1] = " "
                    i += 2
                    in_block = False
                else:
                    buf[i] = " "
                    i += 1
                continue
            # Block open. `{/* … */}` needs no special case: the brace sits
            # outside the comment token, so matching `/*` covers JSX too.
            if raw.startswith("/*", i) and not is_python:
                buf[i] = buf[i + 1] = " "
                i += 2
                in_block = True
                continue
            # Line comment: blank to end of line. `://` is excluded so a URL in
            # a string ("https://example") is not read as a comment -- that
            # would blank the rest of a RENDERED line and hide a claim after it,
            # which is a false negative in a guard whose whole job is to have
            # none.
            if (raw.startswith("//", i) and not is_python
                    and not (i and raw[i - 1] == ":")) or (
                    is_python and raw[i] == "#"):
                for j in range(i, n):
                    buf[j] = " "
                break
            i += 1
        out.append("".join(buf))
    return out


# ── The claims ──────────────────────────────────────────────────────────────
#
# (label, pattern, paths the rule applies to, what would have to be true first).
# `paths` is a prefix tuple relative to the repo root: each rule names the
# surfaces where the capability is ABSENT, so a true claim elsewhere is not
# forbidden.
FORBIDDEN: tuple[tuple[str, re.Pattern[str], tuple[str, ...], str], ...] = (
    (
        "aes_cipher_claim",
        re.compile(r"AES-?\s?(?:256|128)", re.IGNORECASE),
        ("frontend/src/", "backend/app/"),
        # NARROWED 2026-09-23, NOT RELAXED. The original rationale read
        # "Signature data is stored as plaintext base64", and that is no longer
        # true: `core/signature_crypto.py` encrypts every stored signature with
        # AES-256-GCM, bound to its agreement and party. A cipher module cannot
        # be forbidden from naming its own algorithm, so that ONE file is
        # exempt -- it is implementation, not a string a user reads.
        #
        # EVERYTHING ELSE STAYS FORBIDDEN, and the frontend is untouched by this
        # change. Encrypting the signature does not encrypt the agreement body,
        # the audit log or anything else, so a blanket "AES-256 encrypted"
        # banner would still overstate what runs. The only wording this earns is
        # a specific one about signatures at rest.
        "Signatures are encrypted (AES-256-GCM, `core/signature_crypto.py`), "
        "but nothing else is: the body, the audit log and the party records are "
        "stored in clear. A user-facing AES claim must therefore say WHAT is "
        "encrypted -- 'Signatures encrypted at rest with AES-256-GCM' -- and "
        "must not imply the agreement as a whole is. Add such wording to the "
        "allowlist below with the string that makes it true.",
    ),
    (
        "invitation_delivery_claim",
        # "sent to <address>", "we emailed", "check your email/inbox" -- any
        # phrasing that tells a user an invitation was DELIVERED.
        re.compile(
            r"(?:link|invitation|invite)[^.\n]{0,40}\bsent\s+to\b"
            r"|\bwe\s+(?:have\s+)?(?:e-?mail|email)ed\b"
            r"|\bcheck\s+(?:your|their)\s+(?:e-?mail|inbox)\b",
            re.IGNORECASE),
        ("frontend/src/components/client/ModAgreements.jsx",
         "frontend/src/app/sign/",
         "backend/app/services/agreement_service.py"),
        # ADDED 2026-09-24, after exactly this shipped. The builder told the
        # sender "One-time link sent to ali@example.pk" on the review step and
        # "we can show the invitation was sent to that address" beside the
        # email field. Neither was true at the time: there was no agreement
        # sender at all. A user read those lines, sent the agreement, and
        # waited for an email that no code path could produce.
        #
        # KEPT AFTER `send_agreement_invitation_email` WAS ADDED, because the
        # reason changed rather than went away. Delivery is BEST EFFORT and
        # deliberately not retried: SMTP may be unconfigured, or one send may
        # fail, and either way the creator still holds the link. A static
        # string cannot know which happened.
        "Invitation email is best effort. Whether one was delivered is a "
        "PER-RECIPIENT RESULT the server reports in `invitation_delivery` "
        "({emailed, reason}); the UI must render that value rather than assert "
        "delivery in fixed text. A hardcoded 'link sent to…' or 'check your "
        "inbox' is a claim about a specific send that the string cannot see, "
        "and it is wrong every time SMTP is down or unconfigured.",
    ),
    (
        "esignature_compliance_claim",
        re.compile(r"compl(?:y|ies|iant|ying)\s+with\s+e-?signature", re.IGNORECASE),
        ("frontend/src/", "backend/app/"),
        "Whether a signature complies with ETO 2002 is a legal conclusion. "
        "It needs counsel-approved wording (Phase 4.1), not a UI string.",
    ),
    (
        "fake_draft_persistence",
        re.compile(r"Draft\s+saved", re.IGNORECASE),
        # Agreements ONLY. Lawyer document drafts genuinely persist through
        # `saveDocDraft`, so the same words are a true claim there.
        ("frontend/src/components/client/ModAgreements.jsx",),
        "Agreements have no draft persistence until Phase 3 (Section 3.4). "
        "Telling a user their draft was saved when it was not is a false "
        "claim about their own work.",
    ),
)


def _scanned_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for root in SCANNED_ROOTS:
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            if EXCLUDED_PARTS & set(path.parts):
                continue
            rel = path.relative_to(REPO).as_posix()
            if rel.startswith(EXCLUDED_DIR_PREFIXES):
                continue
            out.append(path)
    return out


def test_the_allowlist_actually_matches_files():
    """A guard that silently scans nothing passes forever.

    If the roots are renamed, every claim test below would go green without
    reading a line. This asserts the scanner has a corpus before the scanner is
    trusted.
    """
    files = _scanned_files()
    assert len(files) > 200, (
        f"Expected to scan the app and frontend source; found {len(files)} "
        "files. SCANNED_ROOTS is probably stale."
    )


#: Exact wordings a rule permits, because they are TRUE and specific.
#:
#: An allowlist rather than a weaker pattern, and exact substrings rather than a
#: looser regex, so that approving one sentence never approves a family of them.
#: A claim earns its place here by naming WHAT is protected: signatures are
#: encrypted at rest, and the agreement body, the audit log and the party
#: records are not. A banner saying merely "AES-256 encrypted" would still be
#: an overstatement and is still refused.
APPROVED_CLAIMS: dict[str, tuple[str, ...]] = {
    "aes_cipher_claim": (
        "Signature encrypted at rest with AES-256-GCM",
    ),
}


#: Files a rule may not be applied to, because the file IMPLEMENTS the thing the
#: rule guards. Deliberately exact paths, never prefixes: a directory exemption
#: would grow to cover code nobody meant to exempt. Keyed by rule label so an
#: exemption cannot silently widen to the other rules.
IMPLEMENTATION_EXEMPT: dict[str, frozenset[str]] = {
    # The cipher module names its own algorithm in its docstring, its
    # ALGORITHM constant and its "key must be 32 bytes" error. Every one of
    # those is true, and none is a string a user reads.
    "aes_cipher_claim": frozenset({"backend/app/core/signature_crypto.py"}),
}


@pytest.mark.parametrize("label,pattern,paths,rationale",
                         FORBIDDEN, ids=[f[0] for f in FORBIDDEN])
def test_no_unsupported_claim_reaches_a_user(label, pattern, paths, rationale):
    exempt = IMPLEMENTATION_EXEMPT.get(label, frozenset())
    hits: list[str] = []
    for path in _scanned_files():
        rel = path.relative_to(REPO).as_posix()
        if not rel.startswith(paths) or rel in exempt:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Comment SPANS are blanked, not whole lines: a comment may name a claim
        # in order to refuse it, but code sharing that line is still scanned.
        approved = APPROVED_CLAIMS.get(label, ())
        for lineno, line in enumerate(_strip_comments(text, path.suffix), start=1):
            if pattern.search(line) and not any(a in line for a in approved):
                hits.append(f"  {rel}:{lineno}  {line.strip()[:90]}")

    assert not hits, (
        f"\n\nUnsupported claim '{label}' reaches a user in {len(hits)} place(s):\n"
        + "\n".join(hits)
        + f"\n\n{rationale}\n"
    )


def _scan(src: str, suffix: str = ".jsx") -> list[int]:
    """Line numbers where the AES rule still fires after comment masking."""
    return [
        i for i, line in enumerate(_strip_comments(src, suffix), start=1)
        if FORBIDDEN[0][1].search(line)
    ]


def test_multiline_comments_are_masked():
    """A block comment's continuation lines carry no claim.

    This is the shape of every removal note in the files this guards.
    """
    src = (
        'const a = 1;\n'                       # 1
        '// AES-256 was claimed here\n'        # 2  line comment
        '{/* an opener naming AES-256\n'       # 3  block opens
        '   AES-256 again mid-block\n'         # 4  continuation
        '   and closing here */}\n'            # 5  block closes
        'const rendered = "x";\n'              # 6
    )
    assert _scan(src) == []


def test_code_after_an_inline_block_close_is_still_scanned():
    """THE BYPASS THAT MADE SPAN MASKING NECESSARY.

        /* explanation */ <div>AES-256 encrypted</div>

    starts like a comment, so a line-level exemption skipped the rendered claim
    that followed the close. Masking spans keeps it visible.
    """
    src = '/* explanation */ <div>AES-256 encrypted</div>\n'
    assert _scan(src) == [1]


def test_a_rendered_claim_is_still_caught_next_to_comments():
    """A refusing comment directly above replacement copy must keep working."""
    src = (
        '{/* was: AES-256 encrypted -- untrue, see the plan */}\n'
        '<div>AES-256 encrypted</div>\n'
    )
    assert _scan(src) == [2]


def test_hash_is_a_comment_only_in_python():
    """JavaScript private fields start with `#` and are not comments.

    Treating `#` as a comment marker in .jsx would blank real code -- and
    anything after it on the line, including a claim.
    """
    js = 'class A { #total = "AES-256 encrypted"; }\n'
    assert _scan(js, ".jsx") == [1], "JS `#` is a private field, not a comment"

    py = '# AES-256 is not what we use\n'
    assert _scan(py, ".py") == [], "Python `#` is a comment"

    py_code = 'LABEL = "AES-256 encrypted"  # not a comment, the string renders\n'
    assert _scan(py_code, ".py") == [1]


def test_a_url_is_not_read_as_a_comment():
    """`//` inside a URL must not blank the rest of a rendered line."""
    src = '<a href="https://example.test">AES-256 encrypted</a>\n'
    assert _scan(src) == [1]
