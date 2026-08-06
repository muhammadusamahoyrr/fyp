"""
fetch_punjab_statutes.py — Download Punjab provincial statutes with provenance.

Why
---
Every chunk in the corpus was province="federal", so the retriever's province
filter excluded nothing and no provincial law existed. Whole subjects that are
provincial in Pakistan were therefore missing entirely: rent, tenancy, land
revenue, pre-emption, consumer protection, family courts, and policing.

That is not abstract. The seed query "Can a tenant be evicted without notice in
Punjab?" scored 0.21 relevance because the Punjab Rented Premises Act 2009 —
the statute that answers it — was not in the corpus.

A correctness warning
---------------------
POLICE ORDER 2002 supersedes the Police Act 1861 in Punjab. The corpus holds 549
chunks of the 1861 Act. Once the Order is ingested, a Punjab policing query can
retrieve both, and the older text is largely superseded. Consider marking the
1861 Act as federal-residual, or down-ranking it for Punjab queries. Citing
repealed law confidently is worse than citing nothing.

Source
------
punjablaws.punjab.gov.pk — the Punjab Code, maintained by the Government of the
Punjab. Every URL below was resolved from the alphabetical index and verified to
return a text-extractable PDF over a valid TLS connection on the date shown.

Usage
-----
  python scripts/fetch_punjab_statutes.py                 # list
  python scripts/fetch_punjab_statutes.py --check
  python scripts/fetch_punjab_statutes.py --download --out DIR
Then:
  python scripts/ingest_statutes.py --dir DIR --province punjab --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import httpx

VERIFIED_ON = "2026-08-06"
U = "https://punjablaws.punjab.gov.pk/uploads/articles/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# (canonical statute, save-as filename, url)
SOURCES: list[tuple[str, str, str]] = [
    ("Punjab Rented Premises Act 2009",
     "punjab-rented-premises-act-2009.pdf",
     U + "THE_PUNJAB_RENTED_PREMISES_ACT_2009.doc.pdf"),
    ("Punjab Tenancy Act 1887",
     "punjab-tenancy-act-1887.pdf",
     U + "THE_PUNJAB_TENANCY_ACT%2C_18871.pdf"),
    ("Punjab Protection and Restoration of Tenancy Rights Act 1950",
     "punjab-protection-restoration-tenancy-rights-act-1950.pdf",
     U + "3-punjab-protection-and-restoration-of-tenancy-rights-act-1950-xiii-of-1950-pdf.pdf"),
    ("Punjab Land Revenue Act 1967",
     "punjab-land-revenue-act-1967.pdf",
     U + "punjab-land-revenue-act-1967-pdf.pdf"),
    ("Punjab Land Revenue (Abolition) Act 1998",
     "punjab-land-revenue-abolition-act-1998.pdf",
     U + "THE_PUNJAB_LAND_REVENUE_%28ABOLITION%29_ACT_1998.doc.pdf"),
    ("Punjab Pre-emption Act 1991",
     "punjab-pre-emption-act-1991.pdf",
     U + "THE_PUNJAB_PRE-EMPTION_ACT%2C_1991.doc.pdf"),
    ("Punjab Pre-emption (Removal of Doubts) Ordinance 1972",
     "punjab-pre-emption-removal-of-doubts-ordinance-1972.pdf",
     U + "THE_PUNJAB_PRE-EMPTION_%28REMOVAL_OF_DOUBTS%29_ORDINANCE%2C_1972.doc.pdf"),
    ("Punjab Partition of Immovable Property Act 2012",
     "punjab-partition-of-immovable-property-act-2012.pdf",
     U + "PUNJAB_PARTITION_OF_IMMOVABLE_PROPERTY_ACT%2C_2012.doc.pdf"),
    ("Punjab Consumer Protection Act 2005",
     "punjab-consumer-protection-act-2005.pdf",
     U + "the_punjab_consumer_protection_act_2005-pdf.pdf"),
    ("Punjab Protection of Women against Violence Act 2016",
     "punjab-protection-of-women-against-violence-act-2016.pdf",
     U + "punjab-protection-of-women-against-violence-act-2016-pdf2.pdf"),
    ("Punjab Letters of Administration and Succession Certificates Act 2021",
     "punjab-letters-of-administration-succession-certificates-act-2021.pdf",
     U + "punjab-letters-of-administration-and-succession-certificates-act-2021-docx-pdf.pdf"),
    ("Family Courts Act 1964",
     "punjab-family-courts-act-1964.pdf",
     U + "family-courts-act-1964-xxxv-of-1964-pdf.pdf"),
    ("Police Order 2002",
     "police-order-2002.pdf",
     U + "police_order-_2002-doc-doc-pdf.pdf"),
    ("Punjab Tenancy (Validation and Extension of Period for Payment of "
     "Compensation) Ordinance 1969",
     "punjab-tenancy-validation-ordinance-1969.pdf",
     U + "THE_PUNJAB_TENANCY_%28VALIDATION_AND_EXTENSION_OF_PERIOD_FOR_PAYMENT_"
         "OF_COMPENSATION%29_ORDINANCE%2C_1969.doc.pdf"),
]


def _client() -> httpx.Client:
    # TLS verification stays on: a statute fetched over an unverified channel is
    # a provenance problem, not a convenience issue.
    return httpx.Client(timeout=120, follow_redirects=True, headers=HEADERS)


def cmd_list() -> None:
    print(f"\n  {len(SOURCES)} Punjab statutes  (verified {VERIFIED_ON})\n")
    for statute, _fn, _url in SOURCES:
        print(f"    {statute}")
    print()


def cmd_check() -> None:
    print(f"\n{'statute':<64} {'HTTP':>5} {'bytes':>9}  pdf?")
    print("-" * 90)
    ok = 0
    with _client() as c:
        for statute, _fn, url in SOURCES:
            try:
                r = c.get(url)
                is_pdf = r.content.startswith(b"%PDF")
                ok += 1 if (r.status_code == 200 and is_pdf) else 0
                print(f"{statute[:63]:<64} {r.status_code:>5} {len(r.content):>9,}  "
                      f"{'yes' if is_pdf else 'NO'}")
            except Exception as exc:
                print(f"{statute[:63]:<64} {'ERR':>5} {'-':>9}  {type(exc).__name__}")
    print(f"\n  {ok}/{len(SOURCES)} reachable\n")


def cmd_download(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    with _client() as c:
        for statute, filename, url in SOURCES:
            try:
                r = c.get(url)
                if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                    print(f"  SKIP {statute} — HTTP {r.status_code}")
                    continue
                (out / filename).write_bytes(r.content)
                manifest.append({
                    "statute": statute,
                    "file": filename,
                    "source_url": url,
                    "province": "punjab",
                    "bytes": len(r.content),
                    "sha256": hashlib.sha256(r.content).hexdigest(),
                    "retrieved": date.today().isoformat(),
                    "source": "punjablaws.punjab.gov.pk (Government of the Punjab)",
                })
                print(f"  saved {filename}  ({len(r.content):,} bytes)")
            except Exception as exc:
                print(f"  FAIL {statute}: {type(exc).__name__}")

    (out / "SOURCES.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n  {len(manifest)} files -> {out}")
    print(f"  provenance manifest -> {out / 'SOURCES.json'}")
    print(f"\n  Next: python scripts/ingest_statutes.py --dir \"{out}\" "
          f"--province punjab --apply\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true")
    p.add_argument("--download", action="store_true")
    p.add_argument("--out", default=str(Path.home() / "Desktop" / "punjab_law_data"))
    a = p.parse_args()
    if a.check:
        cmd_check()
    elif a.download:
        cmd_download(Path(a.out))
    else:
        cmd_list()
        print("  --check to verify URLs, --download to fetch them\n")
