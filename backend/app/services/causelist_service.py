"""Cause-list watcher — the munshi's evening job, automated.

v1 source: Lahore High Court (data.lhc.gov.pk), which serves its regular
cause list from a plain GET endpoint (verified 2026-07-05) covering the
Principal Seat plus the Bahawalpur, Multan and Rawalpindi benches. The
endpoint filters server-side by case number, so each watch costs one small
request. A paste-to-match fallback covers courts we don't scrape yet —
cause lists circulate as text/PDF in chamber WhatsApp groups.
"""
import asyncio
import logging
import re
import secrets
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.core.constants import NotificationType
from app.core.exceptions import AppValidationError, NotFoundError, ServiceUnavailableError
from app.repositories.causelist_repo import CauselistEntryRepository, CauselistWatchRepository

logger = logging.getLogger(__name__)

watch_repo = CauselistWatchRepository()
entry_repo = CauselistEntryRepository()

LHC_ENDPOINT = "https://data.lhc.gov.pk/dynamic/cause_list_regular_result.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://data.lhc.gov.pk/case_management/regular_cause_list",
}

# "39043/26", "39043/2026", optionally prefixed ("W.P. 1234/25", "CM/1/39043/26").
# Year must be exactly 2 or 4 digits and not run into more digits, so the
# number/year pair inside composite refs is picked out correctly.
_CASE_NO_RE = re.compile(r"(\d{1,6})\s*/\s*(\d{4}|\d{2})(?!\d)")


def _canon(num: str, year: str) -> str:
    return f"{num}/{year[2:] if len(year) == 4 else year}"


def normalize_case_no(raw: str) -> str:
    """Canonical form: '<number>/<2-digit year>' — how the LHC list prints it.
    Uses the last number/year pair, which is the main case reference in
    composite strings like 'CM/1/39043/26'."""
    matches = _CASE_NO_RE.findall(raw or "")
    if not matches:
        return (raw or "").strip()
    return _canon(*matches[-1])


def extract_case_nos(raw: str) -> set[str]:
    """All canonical case refs present in a string."""
    return {_canon(num, year) for num, year in _CASE_NO_RE.findall(raw or "")}


# ── Fetch ─────────────────────────────────────────────────────────────────────

async def fetch_lhc(
    case_number: str = "",
    lawyer_name: str = "",
    party_name: str = "",
    week_day: str = "",
    location: str = "All",
) -> str:
    params = {
        "weekDay": week_day,
        "courtName": "All Courts",
        "color": "All",
        "location": location,
        "bench": "",
        "caseNumber": case_number,
        "lawyerCode": "",
        "lawyerName": lawyer_name,
        "partyName": party_name,
        "lawyer_cnic": "",
        "lawyer_mobile": "",
    }
    try:
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(LHC_ENDPOINT, params=params)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError as e:
        logger.warning("LHC cause list fetch failed: %r", e)
        raise ServiceUnavailableError("Could not reach the LHC cause list right now — try again shortly")


# ── Parse ─────────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")
_COURT_ROOM_RE = re.compile(r"\[\s*(.+?)\s*\]")
_COLOR_MEANING = {
    "#ff0000": "Old Cause List",
    "#ffff00": "Regular Cause List",
    "#90ee90": "Stay Matters",
    "#ffb6c1": "Part-heard",
    "#ffdab9": "Judgment Reserved",
}


def parse_lhc(html: str) -> list[dict]:
    """Walk the LHC result markup in document order.

    The page alternates single-cell bench-header tables
    ("06-07-2026 / Single Bench / The Chief Justice / [ Court 1 ]")
    with six-column case-row tables; continuation rows for connected
    matters print ' and ' in the seq column.
    """
    soup = BeautifulSoup(html, "html.parser")
    entries: list[dict] = []
    ctx = {"hearing_date": None, "bench": None, "judge": None, "court_room": None}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Bench header: one row, one th, contains a dd-mm-yyyy date
        ths = rows[0].find_all("th")
        if len(rows) == 1 and len(ths) == 1:
            text = ths[0].get_text("\n", strip=True)
            dm = _DATE_RE.search(text)
            if dm:
                ctx["hearing_date"] = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"  # ISO
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                # lines: [date, bench type, judge(, judge2...), [ court room ]]
                ctx["bench"] = lines[1] if len(lines) > 1 else None
                judges = [l for l in lines[2:] if not l.startswith("[")]
                ctx["judge"] = ", ".join(judges) or None
                rm = _COURT_ROOM_RE.search(text)
                ctx["court_room"] = rm.group(1) if rm else None
            continue

        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) != 6:
                continue
            seq = tds[0].get_text(strip=True)
            case_no = tds[2].get_text(strip=True)
            if not case_no or not _CASE_NO_RE.search(case_no):
                continue
            bg = (tr.get("bgcolor") or "").lower()
            entries.append({
                "hearing_date": ctx["hearing_date"],
                "bench": ctx["bench"],
                "judge": ctx["judge"],
                "court_room": ctx["court_room"],
                "seq": seq if seq.lower() != "and" else None,
                "connected": seq.lower() == "and",
                "category": tds[1].get_text(strip=True),
                "case_no": normalize_case_no(case_no),
                "case_no_raw": case_no,
                "title": tds[3].get_text(strip=True),
                "lawyer": tds[4].get_text(strip=True),
                "remarks": tds[5].get_text(strip=True),
                "list_type": _COLOR_MEANING.get(bg, None),
                "source": "lhc_regular",
            })
    return entries


# ── Watches ───────────────────────────────────────────────────────────────────

async def create_watch(
    lawyer_id: str,
    case_no: str,
    title_hint: str | None = None,
    case_id: str | None = None,
    court: str = "lhc",
) -> dict:
    norm = normalize_case_no(case_no)
    if not _CASE_NO_RE.search(norm):
        raise AppValidationError("Enter the court case number like 39043/26 (number/year)")
    existing = await watch_repo.find_one({"lawyer_id": lawyer_id, "case_no": norm, "court": court})
    if existing:
        raise AppValidationError(f"You are already watching {norm}")

    # Soft gating: free tier is capped at one cause-list watch (the anchor of the
    # Professional plan). Paid tiers are unlimited.
    from app.services import subscription_service
    if not await subscription_service.is_paid(lawyer_id):
        current = await watch_repo.count({"lawyer_id": lawyer_id})
        if current >= 1:
            raise AppValidationError(
                "The free plan includes 1 cause-list watch. "
                "Upgrade to Professional for unlimited watches."
            )

    watch = {
        "_id": secrets.token_urlsafe(16),
        "lawyer_id": lawyer_id,
        "court": court,
        "case_no": norm,
        "title_hint": (title_hint or "").strip() or None,
        "case_id": case_id,
        "active": True,
        "last_checked_at": None,
        "last_listed_date": None,
        "created_at": datetime.now(timezone.utc),
    }
    await watch_repo.insert(watch)
    return watch


async def list_watches(lawyer_id: str) -> list[dict]:
    return await watch_repo.find_for_lawyer(lawyer_id)


async def delete_watch(watch_id: str, lawyer_id: str) -> dict:
    watch = await watch_repo.find_by_id(watch_id)
    if not watch:
        raise NotFoundError("Watch")
    if watch["lawyer_id"] != lawyer_id:
        raise NotFoundError("Watch")
    await watch_repo.delete_one({"_id": watch_id})
    await entry_repo.col.delete_many({"watch_id": watch_id})
    return {"success": True}


# ── Checking ──────────────────────────────────────────────────────────────────

async def _notify(lawyer_id: str, entry: dict) -> None:
    try:
        from app.services.notification_service import create_notification
        when = entry.get("hearing_date") or "an upcoming date"
        where = " · ".join(x for x in [entry.get("judge"), entry.get("court_room")] if x)
        await create_notification(
            lawyer_id,
            NotificationType.CAUSELIST_LISTED,
            f"Case {entry['case_no']} is on the cause list",
            f"{entry.get('title') or entry['case_no']} — listed for {when}"
            + (f" · {where}" if where else "")
            + (f" · Seq #{entry['seq']}" if entry.get("seq") else ""),
            payload={"case_no": entry["case_no"], "hearing_date": entry.get("hearing_date"),
                     "watch_id": entry.get("watch_id")},
        )
    except Exception:
        logger.exception("Cause-list notification failed for lawyer %s", lawyer_id)


async def check_watch(watch: dict) -> list[dict]:
    """One LHC query (full upcoming list, filtered server-side by case number);
    stores and notifies entries not seen before."""
    html = await fetch_lhc(case_number=watch["case_no"])
    # Match on any case ref in the raw cell — catches connected matters
    # printed as composite refs like "CM/1/39043/26".
    parsed = [e for e in parse_lhc(html)
              if watch["case_no"] in extract_case_nos(e["case_no_raw"])]

    new_entries = []
    for e in parsed:
        if not e.get("hearing_date"):
            continue
        if await entry_repo.exists(watch["lawyer_id"], e["case_no"], e["hearing_date"], e["source"]):
            continue
        doc = {
            "_id": secrets.token_urlsafe(16),
            "watch_id": watch["_id"],
            "lawyer_id": watch["lawyer_id"],
            "case_id": watch.get("case_id"),
            **e,
            "found_at": datetime.now(timezone.utc),
        }
        await entry_repo.insert(doc)
        await _notify(watch["lawyer_id"], doc)
        new_entries.append(doc)

    await watch_repo.update_one(
        {"_id": watch["_id"]},
        {"$set": {
            "last_checked_at": datetime.now(timezone.utc),
            **({"last_listed_date": max(e["hearing_date"] for e in parsed if e.get("hearing_date"))}
               if any(e.get("hearing_date") for e in parsed) else {}),
        }},
    )
    return new_entries


async def check_lawyer_watches(lawyer_id: str) -> dict:
    watches = [w for w in await watch_repo.find_for_lawyer(lawyer_id) if w.get("active")]
    new_entries: list[dict] = []
    errors = 0
    for w in watches:
        try:
            new_entries.extend(await check_watch(w))
        except ServiceUnavailableError:
            errors += 1
        await asyncio.sleep(0.5)  # be polite to the court server
    return {"checked": len(watches), "new_entries": new_entries, "source_errors": errors}


async def check_all_watches() -> dict:
    """Scheduler entry point — every active watch across all lawyers."""
    watches = await watch_repo.find_all_active()
    new_count = 0
    errors = 0
    for w in watches:
        try:
            new_count += len(await check_watch(w))
        except Exception:
            errors += 1
            logger.exception("Cause-list check failed for watch %s", w["_id"])
        await asyncio.sleep(1.0)
    logger.info("Cause-list sweep: %d watches, %d new listings, %d errors",
                len(watches), new_count, errors)
    return {"watches": len(watches), "new": new_count, "errors": errors}


async def list_entries(lawyer_id: str, upcoming_only: bool = True) -> list[dict]:
    out = []
    for e in await entry_repo.find_for_lawyer(lawyer_id, upcoming_only):
        e = dict(e)
        e["id"] = e.pop("_id")
        out.append(e)
    return out


# ── Paste fallback ────────────────────────────────────────────────────────────

async def match_pasted_list(lawyer_id: str, text: str) -> list[dict]:
    """Match a pasted cause-list (any court) against the lawyer's watches.
    Returns each watched case number found, with its surrounding line."""
    if not text or not text.strip():
        raise AppValidationError("Paste the cause-list text first")
    watches = await watch_repo.find_for_lawyer(lawyer_id)
    by_case = {w["case_no"]: w for w in watches}
    if not by_case:
        return []

    hits = []
    for line in text.splitlines():
        for m in _CASE_NO_RE.finditer(line):
            norm = normalize_case_no(m.group(0))
            if norm in by_case:
                hits.append({
                    "case_no": norm,
                    "watch_id": by_case[norm]["_id"],
                    "line": line.strip()[:300],
                })
    # de-dupe on (case_no, line)
    seen = set()
    unique = []
    for h in hits:
        key = (h["case_no"], h["line"])
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique
