# Input format for PII gate sets scored on the PDF path (pii-eval-8 on)

This file states how a gate set's documents are turned into the input the
application actually reads. It adds to `PII_DETECTION_RUBRIC_3.md`, the approved
rubric, which still governs what to mark and how to mark it. It changes nothing
in the rubric.

## How each document is processed

1. The document's text, with the marks removed, is drawn into a PDF:
   - in a fixed-width Latin font, 8 pt;
   - each line of the YAML text becomes one line of the page;
   - a line longer than about 110 characters wraps at a word;
   - a new page starts every 40 lines.
2. The PDF goes through the application's own text extraction and
   segmentation.
3. Each mark is placed on the extracted text by finding the same words, in
   the same order of occurrence. Spaces and line breaks may differ; the
   words may not.

## What this means for authors

- **Latin text uses plain ASCII punctuation:** straight quotes `"` and `'`,
  the hyphen `-`, and three dots `...`. Avoid typographic quotes, dashes,
  ellipses, symbols such as `✓` or `→`, and emoji. The font cannot draw
  them, so a mark containing them cannot be placed.
- **Urdu/Arabic script is allowed**, as the rubric requires. Those documents
  cannot be drawn by the Latin font and are processed from their text. The
  application blocks Urdu script by policy in any case.
- **Every marked span must reappear word for word.** If a marked value
  appears several times in a document, every occurrence must be written
  identically, character for character (apart from spaces and line breaks).
  A mark is placed by its order of occurrence.
- **Layout is welcome:**
  - column gaps (three or more spaces) between two values on one line;
  - tables with `|` separators;
  - signature rows;
  - names broken across a line;
  - documents long enough to run onto a second page (over 40 lines).
- **Other features:** OCR-style damage ("Kash1f", "lqbal") is allowed
  inside Latin text. It is drawn exactly as written.

A document whose marks cannot be placed after extraction is reported as
unmapped. It makes the set's gate result "not applicable"; it is never
scored on guessed positions.
