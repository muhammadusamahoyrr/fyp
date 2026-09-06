"""Fake Mongo objects for the DOCUMENTS_V2 capture and validation tooling.

One definition, used by the producer tests, the validator tests and the
contract-drift tests -- so a compatibility test can hand the SAME fake database
to both sides and mean it.

Nothing here connects to anything. `find` returns lists, `command` returns a
canned connectionStatus, and the collections are plain Python lists.
"""
from __future__ import annotations


def _matches(doc, query) -> bool:
    """Enough query support to express what the tooling actually asks for.

    Equality and $ne, which covers `{"schema_version": {"$ne": 2}}` -- the
    planner's legacy selection. A fake that ignored the filter made the
    survey's most important property, that V2 rows never enter any count,
    impossible to test: every document came back regardless.
    """
    if not query:
        return True
    for field, condition in query.items():
        value = doc.get(field)
        if isinstance(condition, dict):
            for operator, operand in condition.items():
                if operator == "$ne" and value == operand:
                    return False
                if operator == "$eq" and value != operand:
                    return False
                if operator == "$in" and value not in operand:
                    return False
        elif value != condition:
            return False
    return True


class FakeCollection:
    def __init__(self, docs=None, index_info=None, fail_find_on=None,
                 find_error=None, docs_by_call=None):
        self.docs = list(docs or [])
        self._index_info = dict(index_info or {})
        self._fail_find_on = fail_find_on
        self._find_error = find_error
        # docs_by_call[n] replaces the contents on the nth find() -- how a
        # database changing mid-capture is simulated deterministically.
        self._docs_by_call = dict(docs_by_call or {})
        self.find_calls = 0

    def find(self, filter=None, projection=None):
        self.find_calls += 1
        if self._fail_find_on == self.find_calls:
            raise self._find_error
        if self.find_calls in self._docs_by_call:
            self.docs = list(self._docs_by_call[self.find_calls])
        return [dict(d) for d in self.docs if _matches(d, filter)]

    def count_documents(self, filter=None):
        return sum(1 for d in self.docs if _matches(d, filter))

    def index_information(self):
        return dict(self._index_info)


class FakeDb:
    """Deliberately does NOT create collections on access.

    An auto-creating __getitem__ would let the index check invent collections
    between the before and after fingerprints and fail the stability check for
    reasons that have nothing to do with the code under test.
    """

    def __init__(self, collections, connection_status=None, names_error=None,
                 command_error=None):
        self._collections = dict(collections)
        self._connection_status = connection_status
        self._names_error = names_error
        self._command_error = command_error

    def __getitem__(self, name):
        return self._collections.get(name) or FakeCollection()

    def list_collection_names(self):
        if self._names_error is not None:
            raise self._names_error
        return list(self._collections)

    def command(self, spec, **kwargs):
        if self._command_error is not None:
            raise self._command_error
        if self._connection_status is None:
            raise RuntimeError("connectionStatus unavailable")
        return self._connection_status

    @property
    def documents(self):
        return self["documents"]


class FakeAdmin:
    def __init__(self, ping_error=None):
        self._ping_error = ping_error

    def command(self, *args, **kwargs):
        if self._ping_error is not None:
            raise self._ping_error
        return {"ok": 1}


class FakeClient:
    def __init__(self, db, nodes=(("localhost", 27017),), ping_error=None):
        self.admin = FakeAdmin(ping_error)
        self.nodes = set(nodes)
        self._db = db
        self.closed = False

    def __getitem__(self, name):
        return self._db

    def close(self):
        self.closed = True


READ_ONLY_STATUS = {
    "authInfo": {
        "authenticatedUsers": [{"user": "v2_validator", "db": "admin"}],
        "authenticatedUserRoles": [{"role": "read", "db": "attorney_ai_snapshot"}],
    }
}
READ_WRITE_STATUS = {
    "authInfo": {
        "authenticatedUsers": [{"user": "app", "db": "admin"}],
        "authenticatedUserRoles": [{"role": "readWrite", "db": "attorney_ai_snapshot"}],
    }
}
UNAUTHENTICATED_STATUS = {"authInfo": {"authenticatedUsers": [],
                                       "authenticatedUserRoles": []}}


def row(doc_id, file_path=None, review_status="submitted"):
    entry = {"_id": doc_id, "review_status": review_status, "schema_version": 1}
    if file_path is not None:
        entry["file_path"] = str(file_path)
    return entry


def estate(rows, revisions=None, status=READ_ONLY_STATUS, documents=None, **kw):
    return FakeDb({"documents": documents or FakeCollection(rows),
                   "document_revisions": FakeCollection(revisions or []),
                   "cases": FakeCollection([]),
                   "users": FakeCollection([])},
                  connection_status=status, **kw)
