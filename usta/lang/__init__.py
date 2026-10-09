"""Azerbaijani text helpers (SPEC §12, ADR-031): casefolding and output-language checks."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

MIN_WORDS = 15  # below this, detection is too unreliable to act on (SPEC §12)

_CODES = {
    Language.AZERBAIJANI: "az",
    Language.TURKISH: "tr",
    Language.ENGLISH: "en",
    Language.RUSSIAN: "ru",
}
_UPPER_I = str.maketrans({"İ": "i", "I": "ı"})


def az_casefold(text: str) -> str:
    """Casefold for Azerbaijani: İ→i and I→ı before the generic casefold (F5)."""
    return unicodedata.normalize("NFC", text).translate(_UPPER_I).casefold()


@cache
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*_CODES).build()


def detect(text: str, *, min_words: int = MIN_WORDS) -> str | None:
    """az / tr / en / ru, or None when the text is too short or undecidable."""
    if len(text.split()) < min_words:
        return None
    if "ə" in az_casefold(text):  # ə exists only in Azerbaijani among the four
        return "az"
    lang = _detector().detect_language_of(text)
    return _CODES.get(lang) if lang is not None else None


@dataclass(frozen=True)
class LangResult:
    ok: bool
    detected: str | None
    reason: str | None


def langcheck(
    text: str, expected: str, *, detect_fn: Callable[..., str | None] = detect
) -> LangResult:
    detected = detect_fn(text)
    if detected is None:
        return LangResult(True, None, f"skipped: fewer than {MIN_WORDS} words or undecidable")
    if detected != expected:
        return LangResult(False, detected, f"expected {expected}, detected {detected}")
    if expected == "az" and "ə" not in az_casefold(text):
        return LangResult(False, detected, "Azerbaijani text without ə (possible Turkish drift)")
    return LangResult(True, detected, None)
