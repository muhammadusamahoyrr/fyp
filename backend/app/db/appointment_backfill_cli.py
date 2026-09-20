"""Operator CLI for the appointment `occupied_slots` backfill.

WHY THIS EXISTS

`backfill_occupied_slots` was importable and had no command line, so steps 5
and 6 of the activation sequence needed an interactive Python shell pointed at
production. That is the single worst place to type `dry_run=False` by accident:
a REPL has no confirmation, no echo of what it is about to touch, and no record
of what was run. This gives those two steps a command with a name, a target it
prints back, and refusals that fire before anything is written.

IT REUSES THE BACKFILL, IT DOES NOT REIMPLEMENT IT. No slot arithmetic lives
here. `occupied_slots`, `classify_slots` and the "unfixable row" judgement all
stay in `appointment_slot_preflight`, so the command and the preflight cannot
drift into disagreeing about which rows need repair — which is exactly the
divergence a second implementation would produce, silently.

USAGE

    export AAI_BACKFILL_MONGO_URL='mongodb+srv://...'

    # Step 5 — dry run. The default, and it writes nothing.
    python -m app.db.appointment_backfill_cli --database attorney_ai

    # Step 6 — apply. Every acknowledgement is required.
    python -m app.db.appointment_backfill_cli --database attorney_ai --apply \\
        --confirm-database attorney_ai --booking-writes-frozen

THE URI COMES FROM A NAMED ENVIRONMENT VARIABLE, NEVER AN ARGUMENT. A
connection string carries the password, and an argument is echoed into shell
history, `ps` output, CI logs and screen shares. There is deliberately no
`--uri` flag to fall back to.

WHAT IT WILL NOT DO

  * It never creates or drops an index. Those are separate, reviewed steps with
    their own capacity cost, and bundling them into a data-repair command is
    how an index build starts without anyone deciding to start one.
  * It never applies without a clean dry run. A row the backfill cannot fix is
    a row the preflight has already reported, and repairing everything around
    it produces a collection that looks finished and is not.
  * It never prints a credential or an appointment detail. The output goes into
    tickets and change records.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# The one name this command reads a connection string from. Stated as a
# constant so the error message, the help text and the lookup cannot disagree.
URI_ENV_VAR = "AAI_BACKFILL_MONGO_URL"

EXIT_OK = 0
EXIT_USAGE = 2          # the command was not usable as given
EXIT_REFUSED = 3        # it was understood, and declined
EXIT_PARTIAL = 4        # it wrote, and cannot say the result is complete


class UnparseableTarget(ValueError):
    """The connection string does not name an endpoint this command can confirm."""


# The two URI forms this project uses. `mongodb+srv` is the hosted cluster
# (Atlas/Upstash-style); plain `mongodb` is everything else, including local.
_SCHEME_MONGODB = "mongodb"
_SCHEME_SRV = "mongodb+srv"
_DEFAULT_PORT = 27017


def parsed_endpoints(uri: str) -> list[str]:
    """Every endpoint a connection string points at, as `scheme://host:port`.

    AN ENDPOINT IS SCHEME + HOST + PORT, NOT A HOST.

    The first version of this dropped the port on the grounds that it
    "distinguishes nothing an operator gets wrong". That was wrong in the one
    case that matters: two Mongo instances on the SAME host, differing only by
    port, is exactly how a staging and a production database end up side by
    side on one box — and with the port discarded, confirming one confirmed the
    other. The scheme matters for the same reason: `mongodb+srv://c.example.net`
    and `mongodb://c.example.net` resolve differently and can be different
    clusters entirely.

    Ports are normalised so an operator may confirm the endpoint either as it
    appears in the URI or with the default spelled out — `mongodb://h` and
    `mongodb://h:27017` are the same endpoint and both confirm it. A
    `mongodb+srv` URI carries no port (the SRV record supplies it), so one is
    rejected rather than defaulted; a URI that names a port under `+srv` is
    malformed, and guessing what was meant is how a wrong target slips through.

    Raises rather than returning a placeholder. A target this cannot parse is a
    target the operator cannot confirm, and guessing would let an --apply
    proceed against a server nobody named.
    """
    if not uri or "://" not in uri:
        raise UnparseableTarget("no scheme")
    scheme, _, rest = uri.partition("://")
    scheme = scheme.strip().lower()
    if scheme not in (_SCHEME_MONGODB, _SCHEME_SRV):
        raise UnparseableTarget(f"unsupported scheme {scheme!r}")

    # The authority ends at the first path, query or fragment.
    authority = rest.split("/")[0].split("?")[0].split("#")[0]
    # Credentials are everything before the LAST '@' — a password may contain
    # one, and splitting on the first would treat part of it as a host.
    if "@" in authority:
        authority = authority.rsplit("@", 1)[1]
    if not authority.strip():
        raise UnparseableTarget("no host")

    endpoints: set[str] = set()
    for entry in authority.split(","):
        entry = entry.strip()
        if not entry:
            continue
        host, port = _split_host_port(entry)
        host = host.strip().lower()
        if not host:
            raise UnparseableTarget("empty host")
        if scheme == _SCHEME_SRV:
            if port is not None:
                raise UnparseableTarget("mongodb+srv must not carry a port")
            endpoints.add(f"{_SCHEME_SRV}://{host}")
        else:
            endpoints.add(f"{_SCHEME_MONGODB}://{host}:{port or _DEFAULT_PORT}")

    if not endpoints:
        raise UnparseableTarget("no host")
    if scheme == _SCHEME_SRV and len(endpoints) != 1:
        # An SRV URI names exactly one hostname; several means it is not the
        # URI it claims to be.
        raise UnparseableTarget("mongodb+srv names more than one host")
    return sorted(endpoints)


def _split_host_port(entry: str) -> tuple[str, int | None]:
    """`host[:port]`, with IPv6 literals in brackets."""
    if entry.startswith("["):
        host, sep, tail = entry.partition("]")
        if not sep:
            raise UnparseableTarget("unterminated IPv6 literal")
        host = host.lstrip("[")
        if tail.startswith(":"):
            return host, _port(tail[1:])
        return host, None
    if ":" in entry:
        host, _, raw = entry.rpartition(":")
        return host, _port(raw)
    return entry, None


def _port(raw: str) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise UnparseableTarget(f"non-numeric port {raw!r}") from None
    if not 1 <= port <= 65535:
        raise UnparseableTarget(f"port out of range: {port}")
    return port


def normalise_endpoint(value: str) -> str:
    """One operator-supplied `--confirm-endpoint`, in the same shape.

    Parsed through exactly the same function the URI goes through, so the
    comparison cannot drift: a form the URI parser accepts and the
    confirmation parser does not would refuse a correct target, and the
    reverse would accept a wrong one.
    """
    endpoints = parsed_endpoints(value)
    if len(endpoints) != 1:
        raise UnparseableTarget("give one --confirm-endpoint per host")
    return endpoints[0]


def redact(uri: str) -> str:
    """A connection string with the credentials removed.

    Shows scheme, host and port so an operator can confirm WHICH server they
    are about to touch — the whole point of echoing the target — while keeping
    the password out of a log that will be pasted into a ticket.

    An unparseable URI degrades to a fixed string rather than falling back to
    the raw value: a malformed URI is exactly when a naive redactor leaks.
    """
    try:
        return ",".join(parsed_endpoints(uri))
    except Exception:  # noqa: BLE001
        return "<unparseable connection string>"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.db.appointment_backfill_cli",
        description=("Backfill occupied_slots on active appointments. "
                     "Dry run unless --apply is given."),
    )
    p.add_argument(
        "--database", required=True,
        help="EXACT database name to act on. Named explicitly rather than "
             "taken from application settings, so this command cannot inherit "
             "whichever database a stray environment happens to point at.")
    p.add_argument(
        "--apply", action="store_true",
        help="Actually write. Without it this is a dry run.")
    p.add_argument(
        "--confirm-database", default=None,
        help="Repeat the database name exactly. Required with --apply.")
    p.add_argument(
        "--confirm-endpoint", action="append", default=None,
        metavar="scheme://host[:port]",
        help="Repeat each endpoint the connection string points at, e.g. "
             "mongodb://db.example.net:27017 or mongodb+srv://c0.example.net. "
             "Required with --apply, once per host for a replica set. SCHEME, "
             "HOST AND PORT ALL COUNT: two instances on one host differing "
             "only by port is how staging and production end up side by side. "
             "The database name alone is not a target either — environments "
             "routinely share one, so confirming it proves only that you know "
             "the name. A dry run prints the endpoints to copy.")
    p.add_argument(
        "--booking-writes-frozen", action="store_true",
        help="Acknowledge that booking writes are frozen. Required with "
             "--apply. THIS IS AN ACKNOWLEDGEMENT, NOT A CHECK: nothing here "
             "can verify a freeze, and a booking written during the backfill "
             "carries no slots and escapes the indexes permanently.")
    return p


def _authorise(args, uri, out) -> int | None:
    """Every reason to refuse an --apply, checked before connecting.

    Returns an exit code to stop on, or None to continue. Ordered so the
    operator is told the first thing wrong rather than the last.
    """
    if not args.apply:
        return None

    if args.confirm_database is None:
        out("REFUSED: --apply requires --confirm-database with the exact "
            "database name.")
        return EXIT_REFUSED

    if args.confirm_database != args.database:
        # Compared exactly. This is the check that catches the wrong
        # environment: typing the name twice is easy when it is the database
        # you meant and jarring when it is not.
        out("REFUSED: --confirm-database does not match --database. "
            "Nothing was written.")
        return EXIT_REFUSED

    try:
        actual = parsed_endpoints(uri)
    except UnparseableTarget:
        # Refused BEFORE connecting. A target this cannot parse is one the
        # operator cannot confirm, and letting the driver sort it out would
        # mean applying to a server nobody named.
        out(f"REFUSED: the {URI_ENV_VAR} connection string does not name a "
            "host that can be confirmed. Nothing was written.")
        return EXIT_REFUSED

    if not args.confirm_endpoint:
        out("REFUSED: --apply requires --confirm-endpoint for each endpoint "
            f"the connection string points at ({len(actual)} expected). "
            "Scheme, host AND port all count; the database name alone is not "
            "a target. Run without --apply to see the endpoints to confirm.")
        return EXIT_REFUSED

    try:
        claimed = sorted({normalise_endpoint(e) for e in args.confirm_endpoint
                          if e.strip()})
    except UnparseableTarget as exc:
        out(f"REFUSED: --confirm-endpoint is not a usable endpoint ({exc}). "
            "Expected scheme://host[:port]. Nothing was written.")
        return EXIT_REFUSED

    if claimed != actual:
        # The real endpoints are NOT echoed back here. Naming them in the
        # refusal would turn a wrong guess into a way to read the target out of
        # the error message.
        out("REFUSED: --confirm-endpoint does not match the endpoints in "
            f"{URI_ENV_VAR}. Check which environment that variable points at, "
            "and remember that the port is part of the endpoint. Nothing was "
            "written.")
        return EXIT_REFUSED

    if not args.booking_writes_frozen:
        out("REFUSED: --apply requires --booking-writes-frozen. A booking "
            "created during the backfill carries no occupied_slots, so it is "
            "invisible to the indexes and escapes overlap protection "
            "permanently.")
        return EXIT_REFUSED

    return None


def _partial(out, what: str, detail: str) -> int:
    """Report an apply that cannot be called complete.

    NEVER prints APPLIED. A partial backfill leaves some rows carrying new
    slots and some not, which no single count describes — so the operator is
    told to hold the freeze and look, rather than given a summary that reads
    like success.
    """
    out(f"PARTIAL/UNKNOWN: {what}.")
    out(f"  {detail}")
    out("  KEEP BOOKING WRITES FROZEN. Do not create indexes and do not "
        "deploy.")
    out("  Inspect with `python -m app.db.appointment_slot_preflight`, or "
        "restore from the backup taken before this step.")
    return EXIT_PARTIAL


async def _default_connect(uri: str, database: str):
    """(client, db) for the named database. Replaced in tests."""
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(
        uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    return client, client[database]


async def run(argv, env, connect=_default_connect, out=print) -> int:
    """The command, as a function, so it can be tested without a subprocess."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:      # argparse already printed the reason
        return int(exc.code or EXIT_USAGE)

    uri = (env or {}).get(URI_ENV_VAR)
    if not uri:
        out(f"REFUSED: {URI_ENV_VAR} is not set. The connection string is read "
            "from that variable and is deliberately not accepted as an "
            "argument, because arguments reach shell history and process "
            "listings.")
        return EXIT_USAGE

    refusal = _authorise(args, uri, out)
    if refusal is not None:
        return refusal

    mode = "APPLY" if args.apply else "DRY RUN"
    out(f"target   : {args.database} on {redact(uri)}")
    out(f"mode     : {mode}")

    client, db = await connect(uri, args.database)
    try:
        from app.db.appointment_slot_preflight import backfill_occupied_slots

        # THE DRY RUN ALWAYS HAPPENS, even when applying.
        #
        # It is what decides whether applying is allowed at all, and it costs
        # one pass over the active rows. Skipping it for --apply would mean the
        # refusal below could only be discovered after writing.
        plan = await backfill_occupied_slots(db, dry_run=True)
        out(f"planned  : {plan['planned']}")
        out(f"unfixable: {plan['skipped_unfixable']}")

        if plan["skipped_unfixable"]:
            # Rows with no usable time or a part-slot duration. The preflight
            # lists them; repairing everything around them yields a collection
            # that looks finished and is not.
            out("REFUSED: rows exist that the backfill cannot fix. Resolve "
                "them first — run `python -m app.db.appointment_slot_preflight` "
                "for the list. Nothing was written.")
            return EXIT_REFUSED

        if not args.apply:
            out("written  : 0")
            out("DRY RUN — nothing was written. Re-run with --apply, "
                "--confirm-database, --booking-writes-frozen and "
                "--confirm-endpoint for each of:")
            try:
                for endpoint in parsed_endpoints(uri):
                    out(f"    --confirm-endpoint {endpoint}")
            except UnparseableTarget:
                # A dry run against an unconfirmable target is still useful —
                # it reports the data. It simply cannot be applied.
                out("    (this connection string names no endpoint that can "
                    "be confirmed, so --apply is not available against it)")
            return EXIT_OK

        if plan["planned"] == 0:
            out("written  : 0")
            out("Nothing to do — every active appointment already carries the "
                "slots its own time implies.")
            return EXIT_OK

        # ── the write ────────────────────────────────────────────────────────
        #
        # Everything below distinguishes "it worked" from "it might have". A
        # partial backfill is not a failure to retry blindly: some rows carry
        # new slots and some do not, and the collection is in a state no single
        # count describes. The operator is told to hold the freeze and look,
        # never that it is APPLIED.
        try:
            result = await backfill_occupied_slots(db, dry_run=False)
        except Exception as exc:  # noqa: BLE001
            # The class only. A driver error's message carries the URI and
            # sometimes the credentials, and this output goes into tickets.
            out(f"error    : {type(exc).__name__}")
            return _partial(
                out, "the apply stopped part-way through",
                "An unknown number of rows were updated before it stopped.")

        out(f"written  : {result['written']}")
        out(f"vanished : {result['vanished']}")

        if result["vanished"]:
            return _partial(
                out, "rows the plan counted were gone when the update reached them",
                "That can be a legitimate cancellation mid-run, or a second "
                "writer — which would mean the freeze was not in force.")

        if result["written"] != plan["planned"]:
            return _partial(
                out,
                f"the apply wrote {result['written']} rows but the plan had "
                f"{plan['planned']}",
                "The collection changed between the plan and the write.")

        # A fresh pass must find nothing left to do. This is the only check
        # that reads the collection AFTER the write rather than trusting the
        # counters the write returned.
        try:
            verify = await backfill_occupied_slots(db, dry_run=True)
        except Exception as exc:  # noqa: BLE001
            # THE WRITES ALREADY HAPPENED. A verification that cannot run does
            # not mean they were fine — it means nobody knows, which is the
            # same position as a failed apply and gets the same answer. The
            # class only: a driver error's message carries the URI.
            out(f"error    : {type(exc).__name__}")
            return _partial(
                out, "the post-apply verification could not be read",
                "The rows were written and nothing has confirmed the result.")

        if verify["planned"] or verify["skipped_unfixable"]:
            out(f"remaining: {verify['planned']}")
            return _partial(
                out, "rows still need slots after the apply",
                "The write reported success and the collection disagrees.")

        out("APPLIED. Indexes were NOT created or dropped — those are separate "
            "steps. Re-run the preflight to confirm safe_to_activate.")
        return EXIT_OK
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe


def main(argv=None) -> int:
    return asyncio.run(run(argv if argv is not None else sys.argv[1:], os.environ))


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(main())
