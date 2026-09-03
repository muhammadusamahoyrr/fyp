"""Which cited provisions can actually be opened, and where.

WHY A LINK IS NOT ALWAYS AVAILABLE
----------------------------------
Every statute chunk carries a `source_file` — the PDF it was extracted from.
That is a filename, not a location, and only some of those files are held in
this repository. Measured on the live index (2026-09-02): 46 distinct
`source_file` values across 24,851 chunks, of which 8 files resolve to a PDF on
disk, covering 12,119 chunks — 49% of the corpus, including the three largest
sources (CrPC 1898, PPC 1860, Qanun-e-Shahadat 1984).

So a link is stamped ONLY when the file is really there. The alternative —
emitting a URL for every citation and letting the browser discover the 404 —
would put a dead "open the source" affordance under half of all answers, on a
surface whose entire purpose is telling a lawyer how far to trust what they are
reading. A missing link is honest; a broken one is not.

The same rule covers a name that is AMBIGUOUS. If two directories in the corpus
hold a file with one basename, `source_file` does not identify a document, and
picking either would mean an answer citing one Act linking to another. There is
no correct choice, so no link is offered — unlinkable, exactly like a document
we do not hold.

WHY THE ALLOWLIST IS THE FILESYSTEM ITSELF
------------------------------------------
`source_file` originates in chunk metadata, and metadata is data. Resolution is
therefore a dict lookup against basenames discovered by scanning the corpus
directory — never a path join against a caller-supplied string. A name that is
not a key does not resolve, so `../../.env`, an absolute path and a symlink
target are all simply absent from the map rather than being defended against.

That lookup is necessary but not sufficient, because the VALUES in the map come
from the filesystem, and a filesystem can point outward:

  * a symlink (or a Windows junction) inside the corpus can name any file the
    server process can read — `.env`, a key, another user's upload. Symlinks
    are skipped at indexing and re-checked at serve time.
  * a symlinked DIRECTORY is followed by `rglob`, so the file it yields can sit
    outside the corpus without being a symlink itself. Every candidate is
    therefore fully resolved and proved to remain under the resolved corpus
    root before it is indexed, and again before it is served.

The second check is not redundant with the first. Indexing happens once and is
cached; the corpus is read-only at runtime, but "should be" is not a security
property, and the gap between indexing and serving is exactly where a swapped
file would land.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

# backend/app/ai/source_links.py -> backend/knowledge_base
_CORPUS_ROOT = Path(__file__).resolve().parents[2] / "knowledge_base"

# Route that serves a resolved document. Kept next to the resolver so the two
# cannot drift: a URL is only ever emitted for a name this module resolved.
_SOURCE_ROUTE = "/api/v1/ai/source"

_SERVABLE_SUFFIXES = frozenset({".pdf"})

# Schemes a citation may link to. An allowlist, because the interesting cases
# are the ones nobody thinks to blacklist: `javascript:` executes in the page,
# `data:text/html` renders attacker markup on our origin's tab, and `file:`
# points at the reader's own disk. A judgment URL is court-published data that
# reaches us through the citator, so it is data like any other.
_SAFE_URL_SCHEMES = frozenset({"http", "https"})


def _resolved_root() -> Path | None:
    """The corpus root, fully resolved. None when it is not a directory.

    Not cached: `refresh()` would have to know to clear it, and one `resolve()`
    per lookup is cheap next to the file read it is guarding.
    """
    try:
        root = _CORPUS_ROOT.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return root if root.is_dir() else None


def _contained(path: Path, root: Path) -> Path | None:
    """`path` fully resolved, if it stays inside `root`. Otherwise None.

    Both sides are resolved before comparing. On Windows that also expands 8.3
    short names, so a root reached as `C:\\Users\\THELAP~1\\...` and a file
    reached as `C:\\Users\\The Laptop Hut\\...` compare equal instead of the
    containment check failing on two spellings of one directory.
    """
    try:
        final = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return final if final.is_relative_to(root) else None


@lru_cache(maxsize=1)
def _catalogue() -> tuple[dict[str, str], frozenset[str]]:
    """(basename -> resolved path, ambiguous basenames).

    Cached: the corpus is read-only at runtime and this walks the tree. Call
    `refresh()` in a test that writes fixture files.

    Traversal is SORTED. `rglob` gives no ordering guarantee, so without this
    two processes indexing the same corpus could disagree about which file a
    duplicated basename means — and the disagreement would be invisible, since
    both would serve a real document from the corpus. Ambiguous names are
    dropped entirely below, but the sort still makes the catalogue itself
    reproducible, which is what makes a corpus change reviewable.
    """
    root = _resolved_root()
    if root is None:
        logger.warning("corpus root %s is not a directory — no source links",
                       _CORPUS_ROOT)
        return {}, frozenset()

    found: dict[str, str] = {}
    ambiguous: set[str] = set()
    try:
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in _SERVABLE_SUFFIXES:
                continue
            # A symlink names a file elsewhere; inside a directory that is
            # served by basename that is an arbitrary-read primitive.
            if path.is_symlink() or not path.is_file():
                continue
            # `rglob` follows symlinked DIRECTORIES, so a file that is not
            # itself a link can still resolve outside the corpus.
            final = _contained(path, root)
            if final is None:
                logger.warning("corpus: %s resolves outside %s — not indexed",
                               path, root)
                continue
            if path.name in found:
                # Two documents, one name. `source_file` no longer identifies a
                # document, and guessing would let an answer citing one Act link
                # to another.
                ambiguous.add(path.name)
                continue
            found[path.name] = str(final)
    except Exception:
        logger.exception("corpus source index could not be built — no source links")
        return {}, frozenset()

    for name in ambiguous:
        found.pop(name, None)
        logger.warning("corpus: %r names more than one document — unlinkable", name)
    return found, frozenset(ambiguous)


def refresh() -> None:
    """Drop the cached catalogue. For tests that add or remove corpus files."""
    _catalogue.cache_clear()


def is_ambiguous(source_file: str) -> bool:
    """True when the corpus holds more than one document under this basename."""
    return (source_file or "").strip() in _catalogue()[1]


def resolve(source_file: str) -> Path | None:
    """The on-disk document for a chunk's `source_file`, or None.

    None is a normal answer, not a failure: most statutes in the corpus have no
    document held here, and an ambiguous name has no single document to mean.

    The containment and symlink checks are repeated here rather than trusted
    from indexing time. The catalogue is cached for the life of the process, and
    a path that was a plain file when it was indexed is not necessarily one when
    it is read.
    """
    name = (source_file or "").strip()
    if not name:
        return None

    files, _ambiguous = _catalogue()
    indexed = files.get(name)
    if indexed is None:
        return None

    root = _resolved_root()
    if root is None:
        return None

    path = Path(indexed)
    if path.is_symlink() or not path.is_file():
        return None
    return _contained(path, root)


def source_url(source_file: str) -> str:
    """Link to the document behind a citation, or "" when there is none."""
    if resolve(source_file) is None:
        return ""
    return f"{_SOURCE_ROUTE}/{quote((source_file or '').strip())}"


def safe_external_url(value: object) -> str:
    """An external URL fit to render as a link, or "".

    Judgment citations carry a court-published PDF URL that reaches us through
    the citator, which makes it data. Only http and https survive: `javascript:`
    executes in the page that renders it, `data:text/html` renders attacker
    markup, and `file:` addresses the reader's own disk. A scheme-relative
    `//host/path` is rejected too — it has no scheme of its own and inherits the
    page's, so it reads as safe while behaving like whatever the page is.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        # urlsplit raises on a malformed IPv6 literal, among others.
        return ""
    if parts.scheme.lower() not in _SAFE_URL_SCHEMES:
        return ""
    # http(s) with no host is not addressable — "http:///x" or "https://".
    return text if parts.netloc else ""


def apply_source_links(citations: list[dict] | None) -> None:
    """Decide what each citation can open, and record it. In place.

    Statutes get `source_url`, and only when the corpus holds exactly one
    document under that name. Judgments keep their own external URL, but it is
    validated first: it arrives from the citator as data, and a link the UI
    renders is the wrong place to discover that.

    Never raises: a citation with no link is the normal case, so a failure here
    must not cost the answer its citations.
    """
    for entry in citations or []:
        try:
            if entry.get("type") == "judgment":
                # `source` doubles as the href fallback on the client, so it is
                # held to the same rule as `url`.
                entry["url"] = safe_external_url(entry.get("url"))
                entry["source"] = safe_external_url(entry.get("source"))
                continue
            entry["source_url"] = source_url(entry.get("source", ""))
        except Exception:
            logger.exception("source link stamp failed for %r", entry.get("statute"))
            entry["source_url"] = ""
