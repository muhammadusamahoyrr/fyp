"""The playbook condition language: declarative, typed, three-valued. No eval.

A condition is a one-key mapping `{op: args}`. Operands are TYPED -- never a
bare string whose meaning is guessed (DOC_ANALYZER_PLAN.md §4.5):

    {field: terms.term_months}      a value from the confirmed context
    {value: 12}                     a literal

Operators:  eq ne gt lt gte lte (2 operands) · in (operand, {value: [list]})
            exists ({field}) · not (1 condition) · all / any (>= 1 conditions)

THREE-VALUED. A field the person marked "not stated" (null) or that is
absent is UNKNOWN, and UNKNOWN propagates (Kleene logic): `all` is false if
any part is false, else unknown if any part is unknown; `any` is true if any
part is true, else unknown if any is unknown; `not unknown` is unknown. The
engine turns an unknown applicability into `unable_to_determine` -- a rule is
never applied, or skipped, on a guess.

Everything is checked when the playbook is LOADED: unknown operator, wrong
arity, a field not in the context schema, a literal of the wrong type
(`gt` on a string). A bad playbook fails to load; it never half-runs.
"""
from __future__ import annotations

UNKNOWN = None

#: Every field a condition may read, and its type.
CONTEXT_SCHEMA: dict[str, type] = {
    "document_type": str,
    "jurisdiction": str,
    "terms.term_months": int,
    "terms.rent_period": str,
    "terms.tenancy_year_to_year": bool,
    "terms.rent_amount": int,
    "terms.security_deposit": int,
    "terms.landlord_notice_days": int,
    "terms.nda_mutual": bool,
    "terms.confidentiality_years": int,
    "terms.non_compete": bool,
    "terms.non_compete_months": int,
    "terms.probation_months": int,
    "terms.notice_days": int,
    "terms.salary_amount": int,
}

_COMPARE = {"eq", "ne", "gt", "lt", "gte", "lte"}
_ORDERED = {"gt", "lt", "gte", "lte"}


class PlaybookError(ValueError):
    """The playbook is malformed; it must not load."""


def _operand_type(node, where: str):
    if not isinstance(node, dict) or len(node) != 1:
        raise PlaybookError(f"{where}: an operand must be {{field: ...}} or {{value: ...}}")
    (kind, payload), = node.items()
    if kind == "field":
        if payload not in CONTEXT_SCHEMA:
            raise PlaybookError(f"{where}: unknown field {payload!r}")
        return CONTEXT_SCHEMA[payload]
    if kind == "value":
        if isinstance(payload, bool):
            return bool
        if isinstance(payload, int):
            return int
        if isinstance(payload, str):
            return str
        if isinstance(payload, list):
            return list
        raise PlaybookError(f"{where}: unsupported literal {payload!r}")
    raise PlaybookError(f"{where}: an operand must be {{field: ...}} or {{value: ...}}")


def validate(expr, where: str = "condition") -> None:
    """Raise PlaybookError unless `expr` is a well-formed, well-typed condition."""
    if not isinstance(expr, dict) or len(expr) != 1:
        raise PlaybookError(f"{where}: a condition is a mapping with exactly one operator")
    (op, args), = expr.items()
    if op in _COMPARE:
        if not isinstance(args, list) or len(args) != 2:
            raise PlaybookError(f"{where}: {op} takes exactly 2 operands")
        left, right = (_operand_type(a, f"{where}.{op}") for a in args)
        if list in (left, right):
            raise PlaybookError(f"{where}: {op} cannot compare a list")
        if left is not right:
            raise PlaybookError(f"{where}: {op} compares {left.__name__} with {right.__name__}")
        if op in _ORDERED and left is not int:
            raise PlaybookError(f"{where}: {op} needs whole numbers, not {left.__name__}")
    elif op == "in":
        if not isinstance(args, list) or len(args) != 2:
            raise PlaybookError(f"{where}: in takes (operand, {{value: [list]}})")
        item = _operand_type(args[0], f"{where}.in")
        if _operand_type(args[1], f"{where}.in") is not list or not args[1]["value"]:
            raise PlaybookError(f"{where}: in needs a non-empty literal list")
        if any(type(v) is not item for v in args[1]["value"]):
            raise PlaybookError(f"{where}: in mixes types")
    elif op == "exists":
        if not isinstance(args, list) or len(args) != 1 or "field" not in (args[0] or {}):
            raise PlaybookError(f"{where}: exists takes exactly one {{field: ...}}")
        _operand_type(args[0], f"{where}.exists")
    elif op == "not":
        inner = args[0] if isinstance(args, list) and len(args) == 1 else args
        validate(inner, f"{where}.not")
    elif op in ("all", "any"):
        if not isinstance(args, list) or not args:
            raise PlaybookError(f"{where}: {op} takes at least one condition")
        for i, part in enumerate(args):
            validate(part, f"{where}.{op}[{i}]")
    else:
        raise PlaybookError(f"{where}: unknown operator {op!r}")


def _read(operand: dict, context: dict):
    if "value" in operand:
        return operand["value"]
    node = context
    for part in operand["field"].split("."):
        if not isinstance(node, dict) or part not in node:
            return UNKNOWN
        node = node[part]
    return node            # may be None: "not stated" is UNKNOWN


def evaluate(expr: dict, context: dict):
    """True, False, or UNKNOWN (None). `expr` must have passed `validate`."""
    (op, args), = expr.items()
    if op in _COMPARE:
        left, right = (_read(a, context) for a in args)
        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN
        return {"eq": left == right, "ne": left != right, "gt": left > right,
                "lt": left < right, "gte": left >= right, "lte": left <= right}[op]
    if op == "in":
        item = _read(args[0], context)
        return UNKNOWN if item is UNKNOWN else item in args[1]["value"]
    if op == "exists":
        return _read(args[0], context) is not UNKNOWN
    if op == "not":
        inner = evaluate(args[0] if isinstance(args, list) else args, context)
        return UNKNOWN if inner is UNKNOWN else not inner
    parts = [evaluate(p, context) for p in args]
    if op == "all":
        if any(p is False for p in parts):
            return False
        return UNKNOWN if any(p is UNKNOWN for p in parts) else True
    if any(p is True for p in parts):          # any
        return True
    return UNKNOWN if any(p is UNKNOWN for p in parts) else False
