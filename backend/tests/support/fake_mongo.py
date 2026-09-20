"""A dict-backed stand-in for one Motor collection.

WHY FAKE THE COLLECTION AND NOT THE REPOSITORY

Faking the repository would mean the repository's own code -- the idempotency
key, the duplicate-key branch, the owner-scoped filters -- is never executed,
and those are precisely the things under test. Faking one layer lower means the
real repository runs against something that behaves like Mongo.

WHAT THIS DOES NOT PROVE

The uniqueness here is enforced by this file, not by a Mongo index. So these
tests prove the repository REACTS correctly to a duplicate key; they cannot
prove the index exists. A separate Mongo-gated test covers that, and skips
where no throwaway instance is available.
"""
from __future__ import annotations

import re

from pymongo.errors import DuplicateKeyError


def _matches(doc: dict, query: dict) -> bool:
    for key, want in (query or {}).items():
        have = doc.get(key)
        if isinstance(want, dict):
            for op, operand in want.items():
                if op == "$ne" and have == operand:
                    return False
                if op == "$in" and have not in operand:
                    return False
                if op == "$nin" and have in operand:
                    return False
                if op == "$exists" and (have is not None) != bool(operand):
                    return False
                if op == "$regex" and not re.search(operand, str(have or "")):
                    return False
        elif have != want:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, spec):
        for field, direction in reversed(list(spec or [])):
            self._docs.sort(key=lambda d: (d.get(field) is None, d.get(field)),
                            reverse=direction < 0)
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        return [dict(d) for d in (self._docs[:length] if length else self._docs)]


class FakeCollection:
    """Enough of a Motor collection for the OCR repository."""

    def __init__(self, unique_keys=(("owner_id", "idempotency_key"),)):
        self.docs: list[dict] = []
        self._unique = [tuple(k) for k in unique_keys]
        #: Every write is recorded so a test can assert an UPDATE never happened
        #: to an immutable row.
        self.updates: list[tuple] = []

    @property
    def name(self):
        return "ocr_revisions"

    async def insert_one(self, document):
        for keys in self._unique:
            signature = tuple(document.get(k) for k in keys)
            for existing in self.docs:
                if tuple(existing.get(k) for k in keys) == signature:
                    raise DuplicateKeyError(
                        f"E11000 duplicate key on {'+'.join(keys)}")
        self.docs.append(dict(document))

        class _Result:
            inserted_id = document.get("_id")
        return _Result()

    async def find_one(self, query):
        for doc in self.docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    def find(self, query):
        return _Cursor(d for d in self.docs if _matches(d, query))

    async def update_one(self, query, update):
        self.updates.append((query, update))

        class _Result:
            modified_count = 0
        return _Result()

    async def find_one_and_update(self, query, update, **kwargs):
        self.updates.append((query, update))
        for i, doc in enumerate(self.docs):
            if not _matches(doc, query):
                continue
            changed = dict(doc)
            for key, value in (update.get("$set") or {}).items():
                changed[key] = value
            for key in (update.get("$unset") or {}):
                changed.pop(key, None)
            self.docs[i] = changed
            return dict(changed)
        return None

    async def delete_one(self, query):
        for i, doc in enumerate(self.docs):
            if _matches(doc, query):
                del self.docs[i]

                class _Result:
                    deleted_count = 1
                return _Result()

        class _Result:
            deleted_count = 0
        return _Result()

    async def delete_many(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]

        class _Result:
            deleted_count = before - len(self.docs)
        return _Result()

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    async def create_indexes(self, models):
        return [getattr(m, "document", {}).get("name", "") for m in models]
