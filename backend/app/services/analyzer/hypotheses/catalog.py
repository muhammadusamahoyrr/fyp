"""The drafting-question catalogues, loaded strictly (ANALYZER_HYPOTHESES_PLAN.md §3.3).

Four files sit beside this module: `universal.yaml` (every document) and one per
document type (`tenancy.yaml`, `nda.yaml`, `employment.yaml`). They are DATA.
The loader:

  * accepts only the keys below and refuses anything else;
  * resolves `detector` through `detectors.REGISTRY` -- a static whitelist --
    and refuses an unknown name (there is no dynamic import and no eval);
  * refuses duplicate question ids across all files;
  * refuses law-like wording (a citation or a legal conclusion) in any
    question text, with the same rules the AI validator applies;
  * records the catalogue version and a SHA-256 over the four files, which
    every run stores.

Any problem raises `CatalogueError`: a broken catalogue never half-loads.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

from app.services.analyzer import ai_report
from app.services.analyzer.hypotheses import detectors

HERE = Path(__file__).resolve().parent
VERSION = "drafting-hypotheses.v1"
UNIVERSAL = "universal"
DOCUMENT_TYPES = ("tenancy", "nda", "employment")
FILES = (UNIVERSAL,) + DOCUMENT_TYPES

ATTENTION_IF_ABSENT = "attention_if_absent"
ATTENTION_IF_PRESENT = "attention_if_present"
POLARITIES = (ATTENTION_IF_ABSENT, ATTENTION_IF_PRESENT)

_FILE_KEYS = {"catalogue", "scope", "questions"}
_QUESTION_KEYS = {"id", "question", "detector", "polarity", "ambiguous_when", "explain"}
_REQUIRED = {"id", "question", "detector", "polarity", "explain"}


class CatalogueError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    scope: str                       # "universal" or a document type
    question: str
    detector_name: str
    detector: Callable
    polarity: str
    explain: bool
    ambiguous_when: str | None = None


@dataclass(frozen=True)
class Catalogue:
    version: str
    sha256: str
    universal: tuple[Question, ...]
    by_type: dict

    def for_document(self, document_type: str | None) -> tuple[tuple[Question, ...], tuple[Question, ...]]:
        """(questions to run, type-specific questions SKIPPED). Universal
        questions always run; type-specific ones only for a confirmed type."""
        if document_type in self.by_type:
            return self.universal + self.by_type[document_type], ()
        skipped = tuple(q for qs in self.by_type.values() for q in qs)
        return self.universal, skipped


def _law_like(text: str) -> bool:
    return bool(ai_report._cites_law(text) or ai_report._CONCLUSION.search(text))


def parse(raw_by_file: dict[str, bytes]) -> Catalogue:
    """Build a catalogue from the raw YAML of each file. Exposed for tests."""
    digest = hashlib.sha256()
    seen: set[str] = set()
    universal: tuple[Question, ...] = ()
    by_type: dict[str, tuple[Question, ...]] = {}
    for name in FILES:
        if name not in raw_by_file:
            raise CatalogueError(f"{name}: file missing")
        raw = raw_by_file[name]
        digest.update(name.encode() + b"\0" + raw + b"\0")
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise CatalogueError(f"{name}: not valid YAML") from exc
        if not isinstance(data, dict) or set(data) != _FILE_KEYS:
            raise CatalogueError(f"{name}: keys must be exactly {sorted(_FILE_KEYS)}")
        if data["catalogue"] != VERSION:
            raise CatalogueError(f"{name}: catalogue version {data['catalogue']!r} is not {VERSION}")
        if data["scope"] != name:
            raise CatalogueError(f"{name}: scope must be {name!r}")
        if not isinstance(data["questions"], list) or not data["questions"]:
            raise CatalogueError(f"{name}: questions must be a non-empty list")
        questions = []
        for q in data["questions"]:
            if not isinstance(q, dict):
                raise CatalogueError(f"{name}: a question is not a mapping")
            unknown, missing = set(q) - _QUESTION_KEYS, _REQUIRED - set(q)
            if unknown or missing:
                raise CatalogueError(f"{name}/{q.get('id')}: unknown keys {sorted(unknown)}, missing {sorted(missing)}")
            qid = q["id"]
            if not isinstance(qid, str) or not qid.isidentifier() or qid in seen:
                raise CatalogueError(f"{name}/{qid}: id must be a unique identifier")
            seen.add(qid)
            detector = detectors.REGISTRY.get(q["detector"]) if isinstance(q["detector"], str) else None
            if detector is None:
                raise CatalogueError(f"{name}/{qid}: detector {q['detector']!r} is not in the whitelist")
            if q["polarity"] not in POLARITIES:
                raise CatalogueError(f"{name}/{qid}: polarity must be one of {POLARITIES}")
            if not isinstance(q["explain"], bool):
                raise CatalogueError(f"{name}/{qid}: explain must be true or false")
            for text_field in ("question", "ambiguous_when"):
                value = q.get(text_field)
                if value is None and text_field == "ambiguous_when":
                    continue
                if not isinstance(value, str) or not value.strip() or len(value) > 200:
                    raise CatalogueError(f"{name}/{qid}: {text_field} must be 1-200 characters")
                if _law_like(value):
                    raise CatalogueError(f"{name}/{qid}: {text_field} cites law or states a legal conclusion")
            questions.append(Question(id=qid, scope=name, question=q["question"].strip(),
                                      detector_name=q["detector"], detector=detector, polarity=q["polarity"],
                                      explain=q["explain"], ambiguous_when=q.get("ambiguous_when")))
        if name == UNIVERSAL:
            universal = tuple(questions)
        else:
            by_type[name] = tuple(questions)
    return Catalogue(version=VERSION, sha256=digest.hexdigest(), universal=universal, by_type=by_type)


@lru_cache(maxsize=1)
def load() -> Catalogue:
    return parse({name: (HERE / f"{name}.yaml").read_bytes() for name in FILES})
