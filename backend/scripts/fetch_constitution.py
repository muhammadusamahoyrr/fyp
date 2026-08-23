"""fetch_constitution.py — download the Constitution of Pakistan from the
National Assembly.

Why this exists
---------------
The constitutional collection contained no Constitution. All 924 chunks came
from LEGAL-UQA: 305 article extracts and 619 GPT-4-generated question/answer
pairs, every one tagged `statute: "Constitution of Pakistan 1973"`. The
generated pairs dominated retrieval — 81-100% of returned chunks on ordinary
constitutional queries — so the system was citing model output as the
Constitution, and its grounding verifier was confirming answers against text a
model wrote.

The generated pairs are now excluded from retrieval, which leaves genuine
constitutional coverage at 305 article extracts derived from someone else's OCR.
This fetches the primary source instead.

Provenance
----------
The National Assembly of Pakistan publishes the authenticated text. That is the
body that passed the Constitution on 10 April 1973, which makes it the
authoritative source rather than a convenient one.

TLS verification is left ON. A certificate failure here is a finding — it means
the document cannot be shown to have come from the National Assembly — and the
correct response is to stop, not to pass verify=False.

Usage
-----
  python scripts/fetch_constitution.py --check
  python scripts/fetch_constitution.py --download --out <dir>

Then ingest with the existing pipeline, which already registers this statute
and whose section regex matches article numbering (25., 25A.):

  python scripts/ingest_statutes.py --dir <dir> --only constitution --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SOURCE_NAME = "National Assembly of Pakistan"
URL = "https://na.gov.pk/uploads/documents/1333523681_951.pdf"
FILENAME = "constitution_of_pakistan_1973.pdf"

HEADERS = {"User-Agent": "Mozilla/5.0 (research; attorney-ai corpus build)"}

# Anything much smaller is an error page, not a constitution.
MIN_BYTES = 500_000


def _client() -> httpx.Client:
    return httpx.Client(timeout=180, follow_redirects=True, headers=HEADERS)


def cmd_check() -> int:
    with _client() as c:
        try:
            r = c.get(URL)
        except httpx.HTTPError as exc:
            print(f"  UNREACHABLE  {type(exc).__name__}: {exc}")
            return 1
    ok = (r.status_code == 200
          and r.content[:5] == b"%PDF-"
          and len(r.content) >= MIN_BYTES)
    print(f"  {'OK  ' if ok else 'FAIL'}  {r.status_code}  "
          f"{len(r.content):,} bytes  {r.headers.get('content-type')}")
    print(f"        {URL}")
    if not ok:
        print("        not a usable PDF — do not ingest")
    return 0 if ok else 1


def cmd_download(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    dest = out / FILENAME

    with _client() as c:
        r = c.get(URL)
    if r.status_code != 200 or r.content[:5] != b"%PDF-":
        print(f"  FAILED: status {r.status_code}, "
              f"{len(r.content):,} bytes, magic {r.content[:5]!r}")
        return 1
    if len(r.content) < MIN_BYTES:
        print(f"  FAILED: {len(r.content):,} bytes is below the {MIN_BYTES:,} "
              "floor — almost certainly an error page")
        return 1

    dest.write_bytes(r.content)
    sha = hashlib.sha256(r.content).hexdigest()

    # A statute with no recorded provenance is not citable. The sidecar records
    # where this came from and what exactly was retrieved, so a later reader can
    # tell whether the corpus changed under them.
    (out / f"{FILENAME}.source.json").write_text(json.dumps({
        "statute":       "Constitution of Pakistan 1973",
        "source_name":   SOURCE_NAME,
        "source_url":    URL,
        "retrieved_at":  datetime.now(timezone.utc).isoformat(),
        "bytes":         len(r.content),
        "sha256":        sha,
        "tls_verified":  True,
    }, indent=2), encoding="utf-8")

    print(f"  saved  {dest}")
    print(f"  {len(r.content):,} bytes   sha256 {sha[:16]}…")
    print(f"\n  Next:\n    python scripts/ingest_statutes.py --dir \"{out}\" "
          "--only constitution --apply\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fetch the Constitution of Pakistan.")
    p.add_argument("--check", action="store_true", help="verify the URL resolves")
    p.add_argument("--download", action="store_true", help="download the PDF")
    p.add_argument("--out", default=r"C:\Users\The Laptop Hut\Desktop\specific_case_data",
                   help="directory the ingest script reads")
    a = p.parse_args()
    if a.download:
        raise SystemExit(cmd_download(Path(a.out)))
    raise SystemExit(cmd_check())
