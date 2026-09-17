"""Minimal name normalization for the import stage.

IMPORTANT: this is the *import-time* normalizer only. The real matching
normalizer (per-language rules, transliteration keys, etc.) lives in
packages/namematch and arrives in milestone M2. Keep this one boring:
its only job is to make identical names from different sources compare equal.

The rules here must be IDEMPOTENT: normalizing twice gives the same result
as normalizing once. There is a property test for this in tests/.
"""

from __future__ import annotations

import unicodedata

# Unicode ranges for the scripts we care about right now.
# We add more as new pilot languages arrive — this is the only place to touch.
_SCRIPT_RANGES: list[tuple[str, int, int]] = [
    ("Deva", 0x0900, 0x097F),  # Devanagari (Hindi, Marathi, ...)
    ("Latn", 0x0041, 0x024F),  # Latin, including accented letters
]


def detect_script(text: str) -> str:
    """Guess the ISO 15924 script code from the characters in the text.

    We count letters per known script and return the most common one.
    Returns 'Zyyy' (Unicode's 'common/unknown') when we can't tell —
    the caller decides what to do with that; we never silently guess.
    """
    counts: dict[str, int] = {}
    for char in text:
        if not char.isalpha():
            continue  # spaces, digits and punctuation say nothing about script
        code = ord(char)
        for script, start, end in _SCRIPT_RANGES:
            if start <= code <= end:
                counts[script] = counts.get(script, 0) + 1
                break
    if not counts:
        return "Zyyy"
    return max(counts, key=lambda s: counts[s])


def normalize_name(raw: str, script: str | None = None) -> str:
    """Normalize a vernacular name so equal names compare equal.

    Steps (each one is deliberate, don't reorder casually):
    1. Unicode NFC — one canonical byte form for accented characters.
    2. Collapse all whitespace runs to single spaces, trim the ends.
    3. For Latin script: casefold (a stronger lowercase that handles ß etc.).
       Non-Latin scripts have no case, so we leave them alone.
    """
    text = unicodedata.normalize("NFC", raw)
    text = " ".join(text.split())
    if script is None:
        script = detect_script(text)
    if script == "Latn":
        text = text.casefold()
    return text
