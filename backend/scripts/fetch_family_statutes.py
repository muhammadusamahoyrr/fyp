"""
fetch_family_statutes.py — Download Pakistan's family-law statutes from the
official Pakistan Code, with a recorded, verifiable provenance manifest.

Why this file exists
--------------------
family_collection held 21 chunks (Muslim Family Laws Ordinance only), which is
why a question about the grounds for khula retrieved nothing useful: the
governing statute — the Dissolution of Muslim Marriages Act 1939 — was simply
not in the corpus.

It also fixes a second problem. The existing statute corpus had no documented
provenance: no record of where files came from, when, or under what terms. That
is not defensible in a paper. Every entry below carries its source URL, and the
script records the retrieval date and a SHA-256 of each file it writes.

Source
------
pakistancode.gov.pk is the Ministry of Law and Justice's official consolidated
code of federal legislation, and is therefore authoritative. URLs were resolved
from the Family Laws category index and each was verified to return a real,
text-extractable PDF over a valid TLS connection on the date below.

NOTE ON COVERAGE — read this before deciding what to ingest
-----------------------------------------------------------
Pakistani family law is NOT only Muslim personal law. Christians, Hindus, Parsis
and Sikhs are governed by their own statutes, all listed here. A legal assistant
that indexes only the Muslim Family Laws Ordinance silently fails every
non-Muslim user — minority communities who often have the least access to
affordable legal advice. Ingesting only the "muslim" subset would bake that gap
into the system.

The Family Courts Act 1964 is a PROVINCIAL act (West Pakistan Act XXXV of 1964),
so it is not in the federal code; it is fetched from the Ministry of Law instead.

Usage
-----
  python scripts/fetch_family_statutes.py                    # list, verify nothing
  python scripts/fetch_family_statutes.py --check            # HEAD/GET each URL
  python scripts/fetch_family_statutes.py --download --out DIR
Then:
  python scripts/ingest_statutes.py --dir DIR --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import httpx

VERIFIED_ON = "2026-08-06"
PAKCODE = "https://pakistancode.gov.pk/pdffiles/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# (statute, filename to save as, url, tradition)
# `tradition` is documentation, not routing — every one of these is family law.
SOURCES: list[tuple[str, str, str, str]] = [
    # ── Muslim personal law ──────────────────────────────────────────────────
    ("Dissolution of Muslim Marriages Act 1939",
     "dissolution-of-muslim-marriages-act-1939.pdf",
     PAKCODE + "administratorfb32d6015ae887e6d6b85018961842ea.pdf", "muslim"),
    ("Child Marriage Restraint Act 1929",
     "child-marriage-restraint-act-1929.pdf",
     PAKCODE + "administrator0cb12b901d4304d7e5463da076d88639.pdf", "general"),
    ("Dowry and Bridal Gifts (Restriction) Act 1976",
     "dowry-and-bridal-gifts-restriction-act-1976.pdf",
     PAKCODE + "administrator359d2ddc2ad3cb8f4a5bfa3c263e5ba1.pdf", "general"),
    ("Guardians and Wards Act 1890",
     "guardians-and-wards-act-1890.pdf",
     PAKCODE + "administratord265c726d2d564a9377ed7a8e04708ae.pdf", "general"),
    ("Claims for Maintenance (Recovery Abroad) Ordinance 1959",
     "claims-for-maintenance-recovery-abroad-ordinance-1959.pdf",
     PAKCODE + "administratorce8e5467178e4ff59ec8ba8d8b92f939.pdf", "general"),
    ("Married Women's Property Act 1874",
     "married-womens-property-act-1874.pdf",
     PAKCODE + "administrator838fddea2bd84054cde358506b537096.pdf", "general"),
    ("Marriage Functions (Prohibition of Ostentatious Displays) Ordinance 2000",
     "marriage-functions-ordinance-2000.pdf",
     PAKCODE + "administrator15e53c2db484572b555fac3ad9b24893.pdf", "general"),

    # ── Provincial: family courts ────────────────────────────────────────────
    ("West Pakistan Family Courts Act 1964",
     "west-pakistan-family-courts-act-1964.pdf",
     "https://molaw.gov.pk/SiteImage/Misc/files/"
     "THE%20WEST%20PAKISTAN%20FAMILY%20COURTS%20ACT,%201964.pdf", "general"),

    # ── Christian ────────────────────────────────────────────────────────────
    ("Christian Marriage Act 1872",
     "christian-marriage-act-1872.pdf",
     PAKCODE + "administrator3a246ebbf45c2f156b8ad52f83024d36.pdf", "christian"),
    ("Divorce Act 1869",
     "divorce-act-1869.pdf",
     PAKCODE + "administrator5e93fac2df76e6993f8c8e739c827420.pdf", "christian"),

    # ── Parsi ────────────────────────────────────────────────────────────────
    ("Parsi Marriage and Divorce Act 1936",
     "parsi-marriage-and-divorce-act-1936.pdf",
     PAKCODE + "administrator71b03c0461fc9cbbb7b0cad08bdcb03f.pdf", "parsi"),

    # ── Hindu ────────────────────────────────────────────────────────────────
    ("Hindu Disposition of Property Act 1916",
     "hindu-disposition-of-property-act-1916.pdf",
     PAKCODE + "administrator2153575f47e8a97a8776320d8eac6a3c.pdf", "hindu"),
    ("Hindu Inheritance (Removal of Disabilities) Act 1928",
     "hindu-inheritance-removal-of-disabilities-act-1928.pdf",
     PAKCODE + "administratorbffe66c6012e7d43ef73932bb2016971.pdf", "hindu"),
    ("Hindu Marriage Disabilities Removal Act 1946",
     "hindu-marriage-disabilities-removal-act-1946.pdf",
     PAKCODE + "administratorc0d66c29b7f188230277e3d0855796eb.pdf", "hindu"),
    ("Hindu Married Women's Right to Separate Residence and Maintenance Act 1946",
     "hindu-married-womens-right-to-separate-residence-act-1946.pdf",
     PAKCODE + "administrator5a78ff5559911f2b13d17d04c7d27043.pdf", "hindu"),
    ("Hindu Widows' Re-marriage Act 1856",
     "hindu-widows-remarriage-act-1856.pdf",
     PAKCODE + "administrator3a3e64fb58215907d6e4a8cd7b6c1def.pdf", "hindu"),
    ("Hindu Women's Rights to Property Act 1937",
     "hindu-womens-rights-to-property-act-1937.pdf",
     PAKCODE + "administrator9a92dd810983fc449969d872d9ff53f4.pdf", "hindu"),

    # ── Sikh / other ─────────────────────────────────────────────────────────
    ("Anand Marriage Act 1909",
     "anand-marriage-act-1909.pdf",
     PAKCODE + "administrator82bc64463939f911a97e388509155e4a.pdf", "sikh"),
    ("Arya Marriage Validation Act 1937",
     "arya-marriage-validation-act-1937.pdf",
     PAKCODE + "administratora87de87dd0dd5cb80b7fa3c2d4aa7a89.pdf", "other"),
    ("Special Marriage Act 1872",
     "special-marriage-act-1872.pdf",
     PAKCODE + "administratora0bf0b1883050a237d47158b9a5791a2.pdf", "general"),
]


def _client() -> httpx.Client:
    # TLS verification stays enabled: if the authoritative text of the law cannot
    # be fetched over a verified channel, that is a provenance problem.
    return httpx.Client(timeout=120, follow_redirects=True, headers=HEADERS)


def cmd_list() -> None:
    by_tradition: dict[str, list[str]] = {}
    for statute, _fn, _url, trad in SOURCES:
        by_tradition.setdefault(trad, []).append(statute)
    print(f"\n  {len(SOURCES)} family-law statutes  (verified {VERIFIED_ON})\n")
    for trad in ("muslim", "general", "christian", "hindu", "parsi", "sikh", "other"):
        if trad not in by_tradition:
            continue
        print(f"  [{trad}]")
        for s in by_tradition[trad]:
            print(f"      {s}")
        print()


def cmd_check() -> None:
    print(f"\n{'statute':<62} {'HTTP':>5} {'bytes':>9}  pdf?")
    print("-" * 88)
    ok = bad = 0
    with _client() as c:
        for statute, _fn, url, _t in SOURCES:
            try:
                r = c.get(url)
                is_pdf = r.content.startswith(b"%PDF")
                print(f"{statute[:61]:<62} {r.status_code:>5} {len(r.content):>9,}  "
                      f"{'yes' if is_pdf else 'NO'}")
                ok += 1 if (r.status_code == 200 and is_pdf) else 0
                bad += 0 if (r.status_code == 200 and is_pdf) else 1
            except Exception as exc:
                print(f"{statute[:61]:<62} {'ERR':>5} {'-':>9}  {type(exc).__name__}")
                bad += 1
    print(f"\n  {ok} reachable, {bad} failed\n")


def cmd_download(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    with _client() as c:
        for statute, filename, url, trad in SOURCES:
            dest = out / filename
            try:
                r = c.get(url)
                if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                    print(f"  SKIP {statute} — HTTP {r.status_code}, not a PDF")
                    continue
                dest.write_bytes(r.content)
                sha = hashlib.sha256(r.content).hexdigest()
                manifest.append({
                    "statute": statute,
                    "file": filename,
                    "source_url": url,
                    "tradition": trad,
                    "bytes": len(r.content),
                    "sha256": sha,
                    "retrieved": date.today().isoformat(),
                    "source": "pakistancode.gov.pk (Ministry of Law and Justice)"
                              if "pakistancode" in url else "molaw.gov.pk",
                })
                print(f"  saved {filename}  ({len(r.content):,} bytes)")
            except Exception as exc:
                print(f"  FAIL {statute}: {type(exc).__name__}: {exc}")

    mpath = out / "SOURCES.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n  {len(manifest)} files saved to {out}")
    print(f"  provenance manifest -> {mpath}")
    print(f"\n  Next: python scripts/ingest_statutes.py --dir \"{out}\" --apply\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true", help="verify every URL resolves")
    p.add_argument("--download", action="store_true", help="download all statutes")
    p.add_argument("--out", default=str(Path.home() / "Desktop" / "family_law_data"),
                   help="download directory")
    a = p.parse_args()
    if a.check:
        cmd_check()
    elif a.download:
        cmd_download(Path(a.out))
    else:
        cmd_list()
        print("  --check to verify URLs, --download to fetch them\n")
