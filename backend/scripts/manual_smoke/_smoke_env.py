"""
Shared safety rails for the manual smoke scripts.

WHY THIS EXISTS
---------------
These scripts seed fixture users directly into MongoDB and then drive a running
server over HTTP. They resolved `settings.db_name` with no override, which in a
developer checkout is the LIVE application database — so every run wrote a
KYC-verified fixture lawyer into production and, via /admin/lawyers/embed-all,
a vector into the production ChromaDB. Nothing removed either afterwards.

That is not a hypothetical. It is where the 24 fixture lawyer accounts and both
ghost vectors came from: `test-lawyer-001` (smoke_lawyer_matching.py) and
`e2e-lawyer-seed-001` (smoke_full_e2e.py) survived in the vector store long
after their MongoDB users were gone, and because matching branched on whether
the vector query returned *any* rows, those two dead rows suppressed the entire
real candidate pool for 45 of 59 real cases.

`tests/conftest.py` has had this guard for the pytest suite all along. The
smoke scripts sat outside it.

THE HTTP COMPLICATION
---------------------
Pointing only the script at the test database is not enough. The script writes
to Mongo directly, but the assertions go through a server that resolves its own
`settings.db_name` at startup. If the two disagree, the script seeds one
database and queries another: every request 404s and the run fails in a way
that looks like a broken feature rather than a misconfiguration.

`assert_server_shares_database` catches exactly that and says what to do.
Start the server against the same database:

    DB_NAME=attorney_ai_test ./venv/Scripts/uvicorn.exe app.main:app --reload
"""
from __future__ import annotations

TEST_DB_SUFFIX = "_test"


def use_test_database(allow_production: bool = False) -> str:
    """Redirect this process's database reads and writes to the test database.

    `get_database()` resolves `settings.db_name` on every call, so overriding it
    here redirects the application code the script imports as well as the
    script's own writes.
    """
    from app.core.config import settings

    if allow_production:
        print("!" * 72)
        print("!! --allow-production: seeding fixtures into "
              f"{settings.db_name!r}.")
        print("!! This is how the production database accumulated 24 fixture "
              "lawyers.")
        print("!" * 72)
        return settings.db_name

    if not settings.db_name.endswith(TEST_DB_SUFFIX):
        settings.db_name = f"{settings.db_name}{TEST_DB_SUFFIX}"
    print(f"[smoke] database: {settings.db_name}")
    return settings.db_name


async def assert_server_shares_database(http, token: str) -> None:
    """Fail fast if the running server is on a different database.

    Probes /users/me with a token minted for a user this script has just
    seeded. A 200 proves the server can see our seed data; anything else means
    it is reading a different database and every later assertion would be
    meaningless.
    """
    from app.core.config import settings

    try:
        r = await http.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"[smoke] cannot reach the server: {exc}\n"
            f"        start it first, against {settings.db_name!r}."
        ) from exc

    if r.status_code == 200:
        print(f"[smoke] server confirmed on {settings.db_name!r}")
        return

    raise SystemExit(
        f"[smoke] the server cannot see the seeded user (HTTP {r.status_code}).\n"
        f"        This script seeded {settings.db_name!r}, but the server is\n"
        f"        reading a different database, so nothing it returns would\n"
        f"        mean anything.\n\n"
        f"        Restart the server against the same database:\n"
        f"          DB_NAME={settings.db_name} "
        f"./venv/Scripts/uvicorn.exe app.main:app --reload\n\n"
        f"        Or, to deliberately smoke-test against the configured "
        f"database, re-run with --allow-production."
    )


async def cleanup(user_ids: list[str], case_ids: list[str] | None = None) -> None:
    """Remove what the script seeded, from Mongo AND from the vector store.

    Run in a `finally` so a failed assertion cannot leave fixtures behind. The
    vector half is the half that was missing before: deleting the user without
    forgetting the vector is precisely what produced the two ghost rows.
    """
    from app.db.mongodb import get_database

    db = get_database()
    if user_ids:
        res = await db["users"].delete_many({"_id": {"$in": user_ids}})
        print(f"[smoke] cleanup: removed {res.deleted_count} user(s)")
    if case_ids:
        res = await db["cases"].delete_many({"_id": {"$in": case_ids}})
        print(f"[smoke] cleanup: removed {res.deleted_count} case(s)")

    try:
        from app.ai.lawyer_embeddings import forget_lawyers

        # forget_lawyers reports ids submitted, not rows found — deleting an id
        # that was never embedded is a no-op, so this is "cleared", not "removed".
        n = forget_lawyers(user_ids)
        print(f"[smoke] cleanup: cleared {n} id(s) from the vector store")
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] cleanup: could not remove vectors ({exc})")
