"""Fixture inventory: what actually exists on disk, counted rather than claimed.

The plan states required fixture counts. This reports OBSERVED counts, and the two
are deliberately produced by different code so a requirement cannot be mistaken for
an achievement. Every number here comes from reading the filesystem and the
manifest; nothing is assumed present.

TRAIN / HOLDOUT IS ASSIGNED PER DOCUMENT FAMILY

Pages of one document share layout, typeface, scanner and vocabulary. Splitting
below family level puts near-identical pages on both sides, so the holdout measures
material the configuration was tuned on and the score comes back flattering. A
family appearing on both sides is reported as a LEAK and fails the inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ocr_eval.slices import (
    NOT_EVALUATED,
    REQUIRED_SLICES,
    fixture_slice_key,
    threshold_for,
)

#: Extensions the harness can render. Anything else in the fixture tree is noise.
_FIXTURE_SUFFIXES = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"})


@dataclass(frozen=True)
class SliceInventory:
    key: str
    label: str
    documents: int
    pages: int
    holdout_documents: int
    holdout_pages: int
    train_documents: int
    train_pages: int
    critical_tokens: int
    transcripts_present: int
    transcripts_missing: int
    status: str
    shortfalls: tuple[str, ...]

    def as_report_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label,
            "documents": self.documents, "pages": self.pages,
            "train_documents": self.train_documents, "train_pages": self.train_pages,
            "holdout_documents": self.holdout_documents,
            "holdout_pages": self.holdout_pages,
            "critical_tokens": self.critical_tokens,
            "transcripts_present": self.transcripts_present,
            "transcripts_missing": self.transcripts_missing,
            "status": self.status,
            "shortfalls": list(self.shortfalls),
        }


def scan_fixture_tree(root: Path) -> dict:
    """Count renderable files on disk. No manifest required.

    Answers "is there anything here at all", which is the question that has gone
    unasked every time this work has stalled.
    """
    root = Path(root)
    if not root.exists():
        return {"root": str(root), "exists": False, "files": 0, "by_suffix": {}}

    by_suffix: dict[str, int] = {}
    total = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in _FIXTURE_SUFFIXES:
            continue
        by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
        total += 1
    return {"root": str(root), "exists": True, "files": total,
            "by_suffix": dict(sorted(by_suffix.items()))}


def family_assignments(fixtures) -> dict:
    """Document families, their split assignment, and any leak across the split."""
    families: dict[str, dict] = {}
    for fixture in fixtures:
        name = getattr(fixture, "document_family", None) or "<unassigned>"
        split = getattr(fixture, "split", None) or "<unassigned>"
        entry = families.setdefault(
            name, {"family": name, "splits": set(), "fixtures": 0, "pages": 0})
        entry["splits"].add(split)
        entry["fixtures"] += 1
        entry["pages"] += int(getattr(fixture, "expected_page_count", 0) or 0)

    rows, leaks = [], []
    for name, entry in sorted(families.items()):
        splits = sorted(entry["splits"])
        row = {"family": name, "splits": splits,
               "fixtures": entry["fixtures"], "pages": entry["pages"]}
        rows.append(row)
        if len(splits) > 1:
            leaks.append(name)
    return {"families": rows, "family_count": len(rows), "leaks": leaks}


def build_inventory(fixtures) -> dict:
    """Observed inventory per required slice, with shortfalls named.

    A slice with no fixtures is reported at zero rather than omitted: an absent
    row reads as "fine", and the whole point is that it is not.
    """
    buckets: dict[str, list] = {}
    for fixture in fixtures:
        buckets.setdefault(fixture_slice_key(fixture), []).append(fixture)

    slices: list[SliceInventory] = []
    for threshold in REQUIRED_SLICES:
        group = buckets.get(threshold.key, [])
        holdout = [f for f in group if getattr(f, "split", None) == "holdout"]
        train = [f for f in group if getattr(f, "split", None) == "train"]

        def _pages(items):
            return sum(int(getattr(f, "expected_page_count", 0) or 0) for f in items)

        def _docs(items):
            return len({getattr(f, "document_family", None) or getattr(f, "fixture_id", "")
                        for f in items})

        tokens = sum(len(getattr(f, "critical_tokens", ()) or ()) for f in holdout)
        present = sum(
            1 for f in group
            if getattr(f, "transcript_path", None) and Path(f.transcript_path).exists())

        shortfalls = []
        if _docs(holdout) < threshold.min_holdout_documents:
            shortfalls.append(
                f"holdout documents {_docs(holdout)}/{threshold.min_holdout_documents}")
        if _pages(holdout) < threshold.min_holdout_pages:
            shortfalls.append(
                f"holdout pages {_pages(holdout)}/{threshold.min_holdout_pages}")
        if tokens < threshold.min_critical_tokens:
            shortfalls.append(
                f"critical tokens {tokens}/{threshold.min_critical_tokens}")
        if present < len(group):
            shortfalls.append(f"transcripts {present}/{len(group)}")

        slices.append(SliceInventory(
            key=threshold.key, label=threshold.label,
            documents=_docs(group), pages=_pages(group),
            holdout_documents=_docs(holdout), holdout_pages=_pages(holdout),
            train_documents=_docs(train), train_pages=_pages(train),
            critical_tokens=tokens,
            transcripts_present=present,
            transcripts_missing=len(group) - present,
            status="READY" if not shortfalls else NOT_EVALUATED,
            shortfalls=tuple(shortfalls),
        ))

    ready = [s for s in slices if s.status == "READY"]
    return {
        "slices": [s.as_report_dict() for s in slices],
        "slices_ready": len(ready),
        "slices_required": len(REQUIRED_SLICES),
        "total_documents": sum(s.documents for s in slices),
        "total_pages": sum(s.pages for s in slices),
        "total_holdout_pages": sum(s.holdout_pages for s in slices),
        "ready": len(ready) == len(REQUIRED_SLICES),
    }


def render_text(inventory: dict, tree: dict, families: dict) -> str:
    """A plain-text inventory an owner can read without running anything."""
    lines = [
        "FIXTURE INVENTORY (observed, not required)",
        "",
        f"fixture tree      : {tree['root']}",
        f"exists            : {tree['exists']}",
        f"renderable files  : {tree['files']}",
        f"by suffix         : {tree['by_suffix'] or '{}'}",
        "",
        f"document families : {families['family_count']}",
        f"split leaks       : {families['leaks'] or 'none'}",
        "",
        f"{'slice':<18} {'docs':>5} {'pages':>6} {'ho-doc':>7} {'ho-pg':>6} "
        f"{'tokens':>7} {'transcripts':>12}  status",
    ]
    for row in inventory["slices"]:
        lines.append(
            f"{row['key']:<18} {row['documents']:>5} {row['pages']:>6} "
            f"{row['holdout_documents']:>7} {row['holdout_pages']:>6} "
            f"{row['critical_tokens']:>7} "
            f"{str(row['transcripts_present']) + '/' + str(row['transcripts_present'] + row['transcripts_missing']):>12}"
            f"  {row['status']}")
        for shortfall in row["shortfalls"]:
            lines.append(f"{'':<18} - {shortfall}")
    lines += [
        "",
        f"slices ready      : {inventory['slices_ready']}/{inventory['slices_required']}",
        f"overall           : {'READY' if inventory['ready'] else 'NOT READY'}",
    ]
    return "\n".join(lines)
