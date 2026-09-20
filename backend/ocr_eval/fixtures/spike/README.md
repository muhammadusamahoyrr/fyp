# Drop your 5-10 Urdu/English spike pages here

Nothing in this folder is committed — the parent `.gitignore` allow-list keeps
document bytes out of version control.

## What to put here

Photos or scans of any Urdu (and ideally some mixed Urdu/English) legal
document. FIR, court order, notice, agreement — whatever you can share.

    spike/
      page-01.jpg      <- phone photo is fine, and is the realistic case
      page-02.pdf
      ...

**No transcripts needed.** This is the feasibility spike: it can only produce a
STOP signal, never a go. Five pages can expose an obvious failure; they cannot
establish Urdu support.

## Before you add anything

These are real legal documents. De-identify them: names, CNICs, phone numbers
and addresses replaced or blacked out. If a page cannot be de-identified, leave
it out — a smaller honest spike beats a larger one you cannot keep.

## What happens next

The spike runs `urd`, `urd+eng` and `eng+urd` over each page and reports what
came back, side by side, with no transcript scoring. A human reads the output and
decides whether Urdu is worth pursuing. If it is, the real benchmark needs 30-50
de-identified pages WITH hand-verified transcripts, and that is the expensive
step this spike exists to de-risk.
