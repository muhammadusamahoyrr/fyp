"""reportlab's named-colour table is built once, at import (pdf_generator).

reportlab fills its table lazily by iterating `reportlab.lib.colors.__dict__`.
If that module gains a global mid-iteration (another thread rendering a PDF),
the loop raises and the half-filled table is cached for the whole process:
every later PDF fails on "Invalid color value 'black'". A full test run hit
it -- one RuntimeError, then 147 PDF tests failing.
"""
from __future__ import annotations

import pytest
from reportlab.lib import colors

import app.services.pdf_generator  # noqa: F401 -- the import builds the table

_RealColor = colors.Color


class _Meddling(type):
    """isinstance() against this adds a module global, as a concurrent thread would."""

    def __instancecheck__(cls, obj):
        vars(colors).setdefault("_added_mid_iteration", True)
        return isinstance(obj, _RealColor)


class _MeddlingColor(metaclass=_Meddling):
    pass


def test_importing_pdf_generator_builds_the_full_table():
    table = colors._namedColors
    assert table is not None and table["black"] is colors.black
    assert len(table) == sum(isinstance(v, _RealColor) for v in vars(colors).values())


def test_the_failure_this_prevents_is_real(monkeypatch):
    """A cold table whose build is interrupted stays broken -- reportlab's bug."""
    monkeypatch.setattr(colors, "_namedColors", None)
    monkeypatch.setattr(colors, "Color", _MeddlingColor)
    monkeypatch.delitem(vars(colors), "_added_mid_iteration", raising=False)
    with pytest.raises(RuntimeError, match="changed size during iteration"):
        colors.getAllNamedColors()
    assert colors._namedColors is not None and "black" not in colors._namedColors
    monkeypatch.delitem(vars(colors), "_added_mid_iteration", raising=False)


def test_with_the_table_built_a_mid_render_change_cannot_break_colours(monkeypatch):
    monkeypatch.setattr(colors, "Color", _MeddlingColor)
    assert colors.toColor("black") is colors.black        # the loop never runs again
    monkeypatch.delitem(vars(colors), "_added_mid_iteration", raising=False)
