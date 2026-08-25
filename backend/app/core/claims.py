"""What this system claims about a document it generates — and what it does not.

One string, one place. The scope was adopted formally and is reproduced in full
in docs/CITATION_VERIFICATION_SESSION_REPORT.md §0; this module carries the short
form that travels with every generated document to the people who read it.

It lives here rather than in each UI because two copies drift. The client panel
and the lawyer review panel must not be able to disagree about what was promised.

THE CLAIMS, IN FULL

  1. Every citation in the document is checked against the corpus — confirmed to
     exist, and where checked, confirmed to still be in force.
  2. Where a statute enumerates the required contents, the whole instrument is
     drafted from that statute.
  3. Where contents are delegated to rules or an authority we do not hold, only
     the grounded portion is generated and the gap is disclosed. Nothing is
     invented, and nothing is copy-filled from an external source.
  4. A lawyer reviews before filing. That review, not the generator, is the
     safety net.

WHY THE WORDING IS NEGATIVE FIRST

"We do not claim this document is correct or complete" leads, because a reader
skims. A disclaimer that opens with what the tool DID do invites the reader to
stop there, and the sentence that matters is the one about what it did not.
"""
from __future__ import annotations

# Short form — shown wherever a document is generated or reviewed.
GENERATION_SCOPE = (
    "This document is not claimed to be correct or complete. Its citations have "
    "been checked against the corpus for existence and, where checked, for "
    "currency. Content that statute does not prescribe is not invented — where "
    "a form's contents come from court rules or an authority we do not hold, "
    "that gap is stated rather than filled. A lawyer must review this before it "
    "is filed."
)

# Used where a document is only partly grounded — claim 3 made concrete.
PARTIAL_GROUNDING_NOTICE = (
    "Only the part of this document that a statute actually prescribes has been "
    "generated. The rest of the form is prescribed by rules or by an authority "
    "this system does not hold, and has been left out rather than guessed at."
)
