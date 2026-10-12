"""README language detection with writing systems and stop-word counts (no external model)."""

from __future__ import annotations

import re

_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_INLINE = re.compile(r"`[^`]*`|https?://\S+|\[[^\]]*\]\([^)]*\)")
_WORD = re.compile(r"[a-zà-ÿ]+")

STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and of to is in for with that this you are on it as be use your".split()),
    "es": frozenset("de la que el en y los para con una por las del se es como su al".split()),
    "pt": frozenset("de que para com uma os não você é do da em no na um ao".split()),
    "fr": frozenset("le la les des et est pour une dans que avec vous du au sur".split()),
    "de": frozenset("der die und das ist mit für nicht ein zu den sie auf im eine".split()),
    "it": frozenset("il di che per con una non sono della gli lo nel alla questo".split()),
}

LANGUAGE_NAMES = {
    "en": "inglés",
    "es": "español",
    "pt": "portugués",
    "fr": "francés",
    "de": "alemán",
    "it": "italiano",
    "zh": "chino",
    "ja": "japonés",
    "ko": "coreano",
    "ru": "ruso",
    "und": "sin determinar",
}


def detect(text: str) -> str:
    """ISO 639-1 code of the dominant language, or ``und`` when there is too little text."""
    if not text:
        return "und"
    sample = _INLINE.sub(" ", _CODE_BLOCK.sub(" ", text))[:6000]
    han = sum(1 for c in sample if "一" <= c <= "鿿")
    kana = sum(1 for c in sample if "぀" <= c <= "ヿ")
    hangul = sum(1 for c in sample if "가" <= c <= "힯")
    cyrillic = sum(1 for c in sample if "Ѐ" <= c <= "ӿ")
    letters = sum(1 for c in sample if c.isalpha()) or 1
    if kana >= 10:
        return "ja"
    if hangul >= 10 and hangul / letters > 0.1:
        return "ko"
    if han >= 10 and han / letters > 0.1:
        return "zh"
    if cyrillic >= 20 and cyrillic / letters > 0.3:
        return "ru"
    counts = dict.fromkeys(STOPWORDS, 0)
    for word in _WORD.findall(sample.lower()):
        for lang, words in STOPWORDS.items():
            if word in words:
                counts[lang] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    best, hits = ranked[0]
    runner_up = ranked[1][1]
    if hits < 3 or hits < runner_up + 2:
        return "und"
    return best
