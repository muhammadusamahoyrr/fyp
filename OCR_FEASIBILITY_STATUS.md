# OCR Feasibility — Harness Frozen, Measurement Blocked

**Date:** 2026-09-12
**Harness version:** `1.0.0` (frozen)
**Branch:** `spike/ocr-feasibility`
**Headline:** the harness is frozen and green. **The Urdu measurement cannot be run on this machine**, and the reason is not the OCR engine — it is that this machine cannot *render* Urdu, so any Urdu fixture I generated would be malformed and would produce a **false** stop signal.

---

## 1. Harness: FROZEN ✅

`HARNESS_VERSION = "1.0.0"`, stamped into every report so a number can always be
traced to the ruler that produced it.

Four defects were fixed before freezing, because **every one of them moved the
score in the flattering direction** — they had to go before measurement, not
after:

| # | Defect | Now |
|---|---|---|
| 9 | `379` matched inside `1379`; `PPC 302` inside `PPC 302-B` | whole-identifier matching; `302.1`, `124-A`, `12/2020` rejected; repeat occurrences counted |
| 10 | OCR'd `max_pages`, reported the document's **full** total with `ok: True` | `pages_total` / `processed` / `failed` / `skipped` / `partial`; timing is `seconds_per_processed_page` |
| 11 | every page rasterised up front (~1.2 GB for 50 pages @300 dpi) | one page at a time, released immediately; 40 MP per-page cap refuses a page, not the document |
| 12 | `evaluate({})` at both call sites — freezing thresholds would pass **everything** | real metrics mapped in; slices evaluated; a configured-but-unmeasured slice fails loudly |

Each fix was mutation-tested individually (revert → confirm the guard fails →
restore → confirm byte-identical).

**Tests:** 79 harness tests green (35 correctness + 44 readiness).
**Thresholds remain unfrozen and unset** — correctly, because no baseline exists yet.

---

## 2. Fixtures: BLOCKED — and not for the reason I expected

### 2.1 Urdu cannot be rendered on this machine `VERIFIED_FROM_ENVIRONMENT`

```
Pillow raqm (complex-script shaping) : False
font layout_engine                   : 0  (Layout.BASIC)
fonts with full Urdu codepoint coverage : 23 (arial, calibri, cour, DUBAI…)
```

The glyphs exist. **The shaping does not.** Arabic script requires contextual
glyph substitution (initial / medial / final / isolated forms) and right-to-left
reordering. Pillow does that only through libraqm, which is absent, so
`ImageDraw.text` falls back to `Layout.BASIC`: isolated glyphs, drawn
left-to-right.

So anything I rendered as "Urdu" would be **unjoined, mirrored nonsense that no
Urdu reader would accept as text.** Running Tesseract against it would produce a
catastrophic error rate caused by *my renderer*, not by Tesseract — and it would
look exactly like a legitimate STOP signal.

**That is the single most dangerous outcome available here**, so I did not
generate it. A false stop would kill Urdu support on the strength of a bug in the
fixture generator.

### 2.2 English synthetic fixtures ARE possible — and nearly worthless

Latin needs no shaping, so I can render clean English pages correctly. But
Tesseract reading clean printed English well is not in doubt and was never the
question. Measuring it would produce a real number that answers nothing.

### 2.3 Real representative fixtures cannot be obtained by me

Per the agreed contract: no internet files, no generated scans, nothing from the
repository presented as representative accuracy evidence. Real Pakistani legal
documents are client data or court material — obtaining and de-identifying them
is yours, and the transcription is the genuine cost of this project.

**Status: `NOT_RUN_FIXTURES_MISSING`.** Nothing was substituted.

---

## 3. Engine: installable, but it is your decision

```
winget    : present
choco     : present
network   : github.com 200, pypi.org 200
tesseract : absent (not on PATH, not at the default install location)
```

Installation is technically straightforward. I did not do it, for two reasons:

1. It is a system-wide install with PATH changes and probable elevation on your
   personal laptop — hard to reverse, and not something to pick unilaterally.
2. The readiness report flagged **where it runs** as an open decision with
   confidentiality consequences: local install, Docker sidecar (CLI present,
   daemon currently stopped), or a managed service — the last meaning client
   evidence leaves your infrastructure.

Urdu also needs `urd.traineddata` and `osd.traineddata` fetched separately; the
standard Windows installer offers them as optional components that are easy to
miss.

---

## 4. The actual measurement

**`NOT_RUN_ENGINE_UNAVAILABLE`** — the live output of the frozen harness right now:

```json
{
  "harness_version": "1.0.0",
  "status": "NOT_RUN_ENGINE_UNAVAILABLE",
  "measured": false,
  "results": null,
  "aggregates": null,
  "reasons": [
    "tesseract binary not available on PATH",
    "missing language packs: eng, urd, osd"
  ]
}
```

This is the harness behaving correctly. **OCR accuracy remains NOT MEASURED** —
not zero, not estimated.

---

## 5. What unblocks it

| Blocker | Who | Note |
|---|---|---|
| Authorise the engine, and pick where it runs | you | local / Docker / managed — a confidentiality call, not an engineering one |
| Urdu shaping capability | either | a real Nastaliq font **plus** libraqm, or fixtures scanned from real documents so nothing needs rendering |
| 5–10 throwaway Urdu/English pages for the spike | you | scans or photos; no transcripts needed — the spike is stop-signal only |
| 30–50 de-identified pages + hand transcripts | you | only for the real benchmark, after the spike says "not hopeless" |

**Cheapest honest path:** the spike needs no fonts and no transcripts if the pages
are *real scans* — even five photographed pages of any Urdu legal document you
can share. That sidesteps the rendering problem entirely, because nothing is
generated.

---

## 6. Standing caveat on the spike

Whatever the spike returns, it can only ever produce a **stop** signal, never a
go. Five pages can expose an obvious failure; they cannot establish Urdu support.
And the claim that Tesseract's Urdu data is predominantly Naskh-trained while
Pakistani legal documents are typically Nastaliq remains **unverified** — it is
the assumption the spike exists to test, not a finding.

---

## 7. State

- Harness frozen at `1.0.0`, 79 tests green, thresholds still unset.
- No OCR engine installed. No fonts installed. Nothing downloaded.
- No fixtures fabricated.
- Product code untouched: `backend/app/` and `frontend/src/` unchanged since `d737e11`.
