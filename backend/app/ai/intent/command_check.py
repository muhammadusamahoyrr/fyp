"""
Explicit command pattern matching — runs before the embedding pipeline.
Word count is a confidence hint, not a hard gate: a 10-word message that
contains "please make it brief" is still a format_brief command.
"""

import re
from dataclasses import dataclass
from typing import Optional

# ── Patterns ──────────────────────────────────────────────────────────────────

_PATTERNS: dict[str, list[str]] = {
    "format_brief": [
        r'\bbrief(?:ly)?\b',
        r'\bshort(?:er)?\b',
        r'\bsummar(?:y|ize|ise)\b',
        r'\btldr\b',
        r'\bconcise(?:ly)?\b',
        r'\bsimpl(?:e|er|ify|ified)\b',
        r'\bmukhtasar\b',
        r'\bin\s+(?:short|brief)\b',
        r'\bshorten\b',
        r'\bless\s+words?\b',
        r'\bto\s+the\s+point\b',
    ],
    "format_detail": [
        r'\belaborat(?:e|ion|ing)\b',
        r'\bmore\s+detail(?:s|ed)?\b',
        r'\bmore\s+info(?:rmation)?\b',
        r'\btell\s+me\s+more\b',
        r'\bexplain\s+(?:more|further|again)\b',
        r'\baur\s+batao\b',
        r'\bin\s+detail\b',
        r'\bexpand\b',
        r'\bdeepen?\b',
        r'\bfurther\b',
        r'\bmore\s+about\b',
        r'\bgo\s+(?:deeper|further)\b',
    ],
    "affirm": [
        r'\b(?:ok|okay)\b',
        r'\bthanks?\b',
        r'\bthank\s+you\b',
        r'\bshukriy?a\b',
        r'\btheek\s*hai\b',
        r'\bgot\s+it\b',
        r'\bunderstood\b',
        r'\b(?:yes|yep|yup)\b',
        r'\bacha\b',
        r'\balright\b',
        r'\bi\s+see\b',
        r'\bnoted\b',
        r'\bperfect\b',
        r'\bgreat\b',
        r'\bsamajh\s*gaya\b',
    ],
    "stop": [
        r'\bstop\b',
        r'\bbas\b',
        r'\bquit\b',
        r'\bexit\b',
        r'\bend\s+(?:chat|session|this)\b',
        r'\bi.?m\s+done\b',
        r'\benough\b',
        r'\bno\s+more\b',
        r'\bfinish(?:ed)?\b',
        r'\bkhatam\b',
    ],
}

# Compiled once at import time
_COMPILED: dict[str, list[re.Pattern]] = {
    intent: [re.compile(p, re.IGNORECASE) for p in patterns]
    for intent, patterns in _PATTERNS.items()
}


@dataclass
class CommandResult:
    intent: str
    confidence: float
    pattern_hit: str


def check_command(text: str) -> Optional[CommandResult]:
    """
    Scan text for explicit command patterns.
    Returns CommandResult immediately on first match; caller skips the embedding pipeline.

    Confidence is adjusted by word count as a hint:
      ≤ 3 words  → 0.97  (almost certainly a pure command)
      4–8 words  → 0.88  (command phrase embedded in short sentence)
      > 8 words  → 0.78  (command in a longer message — slightly less certain)
    """
    word_count = len(text.split())

    if word_count <= 3:
        base_conf = 0.97
    elif word_count <= 8:
        base_conf = 0.88
    else:
        base_conf = 0.78

    for intent, patterns in _COMPILED.items():
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                return CommandResult(
                    intent=intent,
                    confidence=base_conf,
                    pattern_hit=m.group(0),
                )
    return None
