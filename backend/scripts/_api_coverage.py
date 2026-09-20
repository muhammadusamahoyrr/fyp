"""Which backend endpoints does the frontend actually call?

Backend side is read from the source: every APIRouter prefix and every
@router.<method>("<path>") under it. Frontend side is every URL string reaching
apiFetch/fetch/axios, including template literals.

Both sides are normalised to a shape comparison -- `{doc_id}` and `${docId}`
both become `*` -- because the question is whether a route is REACHABLE from the
UI, not whether the strings match character for character.

Read-only. Touches no database and no network.
"""
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUTES = BACKEND / "app" / "api" / "v1" / "routes"
FRONTEND = BACKEND.parent / "frontend" / "src"

METHODS = ("get", "post", "put", "patch", "delete", "websocket")


def normalise(path: str) -> str:
    """`/documents/v2/{doc_id}/revisions` -> `/documents/v2/*/revisions`."""
    # ${...} FIRST. Stripping bare {...} first turns `/cases/${id}` into
    # `/cases/$*`, which matches no backend route -- and every dynamic frontend
    # URL then reads as an uncalled endpoint. That mistake reported 104 of 184
    # routes as dead.
    path = re.sub(r"\$\{[^}]*\}", "*", path)        # JS template literal
    path = re.sub(r"\{[^}]*\}", "*", path)          # FastAPI param
    path = re.sub(r"'\s*\+\s*[^+]+\+\s*'", "*", path)
    path = path.split("?")[0].rstrip("/")
    path = re.sub(r"/+", "/", path)
    return path or "/"


def backend_routes() -> dict:
    """(METHOD, path) -> source file."""
    found = {}
    for file in sorted(ROUTES.glob("*.py")):
        if file.name == "__init__.py":
            continue
        source = file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Router prefixes, by variable name.
        prefixes = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            call = node.value
            if not (isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "APIRouter"):
                continue
            prefix = ""
            for kw in call.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefix = kw.value.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                attr = dec.func
                if not isinstance(attr, ast.Attribute) or attr.attr not in METHODS:
                    continue
                router_name = getattr(attr.value, "id", "")
                prefix = prefixes.get(router_name, "")
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                full = normalise(prefix + dec.args[0].value)
                found[(attr.attr.upper(), full)] = f"{file.name}:{node.lineno}"
    return found


def frontend_calls() -> dict:
    """normalised path -> files that call it."""
    calls = defaultdict(set)
    # Anything quoted that starts with "/", up to the closing quote. An
    # allow-list of characters here is a trap: it silently excluded
    # `/documents/v2/${encodeURIComponent(docId)}` for want of parentheses, and
    # every route reached that way then read as uncalled.
    pattern = re.compile(r"""['"`](/[^'"`\n]*)['"`]""")
    for file in FRONTEND.rglob("*"):
        if file.suffix not in (".js", ".jsx", ".ts", ".tsx") or not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        for raw in pattern.findall(text):
            if raw.startswith("//") or len(raw) < 2:
                continue
            calls[normalise(raw)].add(str(file.relative_to(FRONTEND)))
    return calls


def main() -> int:
    routes = backend_routes()
    calls = frontend_calls()
    called = set(calls)

    # A frontend path may carry the API prefix or not; compare on the tail.
    def reachable(path: str) -> bool:
        if path in called:
            return True
        for c in called:
            if c.endswith(path) or path.endswith(c):
                if len(c) > 3 and len(path) > 3:
                    return True
        return False

    by_file = defaultdict(list)
    for (method, path), where in sorted(routes.items(), key=lambda kv: kv[0][1]):
        by_file[where.split(":")[0]].append((method, path, reachable(path)))

    total = len(routes)
    wired = sum(1 for v in by_file.values() for _, _, ok in v if ok)
    print(f"backend routes: {total}   reachable from the frontend: {wired}   "
          f"unreferenced: {total - wired}\n")

    for file in sorted(by_file):
        rows = by_file[file]
        miss = [r for r in rows if not r[2]]
        flag = "" if not miss else f"   <-- {len(miss)} unreferenced"
        print(f"  {file:24} {len(rows):>3} routes{flag}")
        for method, path, ok in rows:
            if not ok:
                print(f"        [ ] {method:9} {path}")
    print()
    print("[ ] = no frontend string matches this path. Verify each by hand: it "
          "may be built dynamically, be admin-only, or be genuinely unused.")
    Path("/tmp/api_coverage.json").write_text(json.dumps(
        {f"{m} {p}": ok for (m, p), _ in routes.items()
         for ok in [reachable(p)]}, indent=2), encoding="utf-8")
    return 0


raise SystemExit(main())
