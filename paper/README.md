# FIT paper — build and submission checklist

Target venue: **FIT — International Conference on Frontiers of Information
Technology**, COMSATS University Islamabad. IEEE-indexed.

## ⚠️ Check the deadline before doing anything else

The **FIT 2026** submission deadline was reported as **31 July 2026**, with the
conference on 14–15 December 2026. If that is accurate, it has already passed.
Confirm on <https://fit.edu.pk/> and the EasyChair page before planning around
it — deadlines are extended often enough that this is worth one email to
`fit@comsats.edu.pk`.

If FIT 2026 is closed, the realistic options are FIT 2027, or another venue.
Do not let the paper sit idle waiting for one conference.

## Confirmed FIT requirements

Source: <https://fit.edu.pk/submission-guidelines.aspx>

| Requirement | Value |
|---|---|
| Page limit | **6 pages maximum** (references included) |
| Format | Two-column **IEEE conference** format |
| File type | PDF only |
| Submission | EasyChair — `https://easychair.org/conferences/?conf=fit26` |
| Exclusivity | Must not be under consideration at another venue |

Not stated on that page and worth confirming: font specifics, similarity-index
threshold, and whether review is double-blind. **If it is double-blind, replace
the `\author{...}` block in `main.tex` with an anonymous one** and scrub
identifying details from the text and acknowledgments.

## Build

```bash
cd paper
pdflatex main
bibtex   main
pdflatex main
pdflatex main
```

Or with `latexmk`:

```bash
latexmk -pdf main.tex
```

`IEEEtran.cls` ships with TeX Live and MiKTeX. If it is missing, download the
official template from
<https://www.ieee.org/conferences/publishing/templates.html> — use the IEEE
version, not a third-party copy.

**Check the page count on every build.** Six pages is tight for this much
material; expect to cut.

## Files

| File | Purpose |
|---|---|
| `FIT_paper.docx` | **The paper, IEEE two-column Word format.** Use this — no LaTeX needed |
| `Attorney_AI_Technical_Dossier.docx` | Everything that will not fit in six pages |
| `build_docx.py` | Regenerates both `.docx` files. Edit content here, not in Word |
| `main.tex` | LaTeX version of the same paper (IEEEtran) |
| `references.bib` | Bibliography for the LaTeX build — **every entry needs verifying** |

`main.tex` and `build_docx.py` hold the same prose in two formats. **Pick one as
your source of truth** — with no LaTeX toolchain installed, that is almost
certainly the Word path — or they will drift apart as you edit.

## Drafting status

| Section | State |
|---|---|
| Abstract, Index Terms | Drafted |
| I. Introduction | Drafted (needs one sourced statistic) |
| II. Related Work | Drafted, 21 references cited |
| III. Method | Drafted in full |
| IV. Evaluation Protocol | Drafted (needs final query counts) |
| V. Results | **Empty — blocked on labelled data** |
| VI. Discussion and Limitations | Drafted |
| VII. Conclusion | Drafted (needs one number) |
| Ethical Considerations | Drafted |
| References | 21 entries, all cited — **all need verifying** |

Estimated length ~4.5 pages of the 6 allowed, leaving room for Results.

## Before submitting

- [ ] Delete the `\TODO` macro definition and every use of it
- [ ] Confirm ≤ 6 pages **after** removing TODO markers
- [ ] Open and verify every reference; delete any you did not read
- [ ] Resolve the two `NEEDS-VERIFICATION` dataset entries in `references.bib`
- [ ] Confirm dataset licences permit research use and are cited as required
- [ ] Add the supervisor as co-author, with affiliation and email
- [ ] Check whether review is anonymous; anonymise if so
- [ ] Run the similarity check your department requires before submission
- [ ] Verify no API keys, tokens, or personal user data appear in any figure,
      table, or example query
- [ ] Confirm example queries contain no real user data from the deployment
- [ ] Run the IEEE PDF compliance check (PDF eXpress) if the CFP requires it

## Honesty constraints carried from the implementation

These are not stylistic preferences — the paper is wrong if it violates them.

- **"Selective", not "calibrated" abstention.** The Platt and isotonic
  transforms are identity until fitted on labelled data. The title and abstract
  must not claim calibration that has not been performed.
- **No results before measurement.** The Results section is deliberately empty.
  Do not write narrative around numbers that do not exist yet.
- **Robustness figures require the bypass fixed.** Any adversarial-refusal rate
  measured before the NLU-shortcut bypass was closed is computed only over
  traffic that reached the gatekeeper, and is not reportable.
- **Query-set provenance must be stated.** The evaluation queries were authored
  alongside the system. If that remains true at submission, it belongs in
  Limitations, not hidden.
