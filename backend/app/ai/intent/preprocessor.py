"""Text preprocessing for intent classification."""

import re

# Roman Urdu → normalized English keyword
_ROMAN_URDU: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bbas\b',         re.I), 'stop'),
    (re.compile(r'\btheek\s*hai\b', re.I), 'ok'),
    (re.compile(r'\bacha\b',        re.I), 'ok'),
    (re.compile(r'\bji\s+haan\b',   re.I), 'yes'),
    (re.compile(r'\bji\b',          re.I), 'ok'),
    (re.compile(r'\baur\s*batao\b', re.I), 'tell me more'),
    (re.compile(r'\bbatao\s*aur\b', re.I), 'tell me more'),
    (re.compile(r'\bmukhtasar\b',   re.I), 'brief'),
    (re.compile(r'\bshukriy?a\b',   re.I), 'thanks'),
    (re.compile(r'\bshukr\b',       re.I), 'thanks'),
    (re.compile(r'\bnahi[n]?\b',    re.I), 'no'),
    (re.compile(r'\bhaan\b',        re.I), 'yes'),
    (re.compile(r'\bsamajh\s*gaya\b', re.I), 'understood'),
    (re.compile(r'\bkhatam\b',      re.I), 'stop'),
]

# Common abbreviations → expanded form (helps embedding + keyword matching)
_ABBREVS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\btl;?dr\b',  re.I), 'brief'),
    (re.compile(r'\basap\b',    re.I), 'urgent'),
    (re.compile(r'\bbtw\b',     re.I), 'by the way'),
    (re.compile(r'\bidk\b',     re.I), 'i do not know'),
    (re.compile(r'\bimo\b',     re.I), 'in my opinion'),
]

_NOISE = re.compile(r'[^\w\s\?\!\.\,\-\']')
_SPACES = re.compile(r'\s+')


def preprocess(text: str) -> str:
    """
    Returns cleaned, normalized text ready for command_check and embedding.
    Preserves enough structure for cosine similarity to work well.
    """
    text = text.strip().lower()

    for pattern, replacement in _ROMAN_URDU:
        text = pattern.sub(replacement, text)

    for pattern, replacement in _ABBREVS:
        text = pattern.sub(replacement, text)

    text = _NOISE.sub(' ', text)
    text = _SPACES.sub(' ', text).strip()
    return text
