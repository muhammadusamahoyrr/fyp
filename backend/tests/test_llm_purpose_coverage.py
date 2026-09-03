"""Every LLM call site must declare an explicit purpose.

Purpose is what makes provenance trustworthy: `answer_llm` is chosen by purpose,
not by call order, because the last successful call in a turn is almost always
the fast grounding judge rather than the model that wrote the answer. An
untagged call defaults to "unknown" and is therefore invisible to attribution —
it still spends tokens, it just cannot be explained afterwards.

A grep cannot enforce this: the real call sites wrap across lines, so a
line-oriented search reports false positives for calls that are correctly
tagged on their continuation line. This walks the AST instead, so it sees the
call as the parser does.
"""
import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
FACTORIES = {"get_llm", "get_fast_llm", "get_structured_llm"}

# The factory module defines them; it does not call them.
EXEMPT = {APP / "ai" / "llm.py"}


def _call_sites():
    """(file, lineno, func_name, has_purpose) for every factory call in app/."""
    out = []
    for path in sorted(APP.rglob("*.py")):
        if path in EXEMPT:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover
            pytest.fail(f"{path} does not parse: {exc}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name not in FACTORIES:
                continue
            has_purpose = any(kw.arg == "purpose" for kw in node.keywords)
            out.append((path.relative_to(APP.parent), node.lineno, name, has_purpose))
    return out


def test_there_are_call_sites_to_check():
    """Guard the guard: a broken walker that finds nothing would pass silently."""
    sites = _call_sites()
    assert len(sites) >= 15, f"expected many call sites, found {len(sites)}"


def test_every_llm_call_site_declares_a_purpose():
    missing = [(str(f), ln, fn) for f, ln, fn, ok in _call_sites() if not ok]
    assert not missing, (
        "LLM calls without an explicit purpose= (they default to 'unknown' and "
        "vanish from provenance attribution):\n  "
        + "\n  ".join(f"{f}:{ln} {fn}(...)" for f, ln, fn in missing)
    )


def test_declared_purposes_are_registered_constants():
    """A typo'd purpose string is worse than none — it looks tagged and is not."""
    from app.ai import provider_health as ph

    bad = []
    for path in sorted(APP.rglob("*.py")):
        if path in EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in FACTORIES:
                continue
            for kw in node.keywords:
                if kw.arg != "purpose":
                    continue
                # A literal must be a known value; a Name must resolve to one.
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    if kw.value.value not in ph.ALL_PURPOSES:
                        bad.append(f"{path.name}:{node.lineno} literal {kw.value.value!r}")
                elif isinstance(kw.value, ast.Name):
                    if not hasattr(ph, kw.value.id):
                        bad.append(f"{path.name}:{node.lineno} unknown name {kw.value.id}")
    assert not bad, "purpose values not registered in provider_health:\n  " + "\n  ".join(bad)


def test_author_purposes_exist_and_are_distinct():
    """answer_llm selection depends on these two being real, ordered purposes."""
    from app.ai import provider_health as ph

    assert ph._AUTHOR_PURPOSES == (ph.PURPOSE_ANSWER_REFORMAT, ph.PURPOSE_ANSWER_GENERATION)
    for p in ph._AUTHOR_PURPOSES:
        assert p in ph.ALL_PURPOSES


def test_generation_and_judge_are_tagged_differently():
    """The bug this whole scheme prevents: judge attributed as the author."""
    from app.ai import provider_health as ph
    assert ph.PURPOSE_ANSWER_GENERATION != ph.PURPOSE_GROUNDING_JUDGE
    assert ph.PURPOSE_GROUNDING_JUDGE not in ph._AUTHOR_PURPOSES
