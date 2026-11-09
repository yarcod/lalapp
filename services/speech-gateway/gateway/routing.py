"""Decide which language a transcript should be spoken in."""

from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

_TARGETS = {"en": Language.ENGLISH, "es": Language.SPANISH}


@lru_cache(maxsize=None)
def _detector(target: str):
    return LanguageDetectorBuilder.from_languages(Language.SWEDISH, _TARGETS[target]).build()


def decide_language(transcript: str, target: str) -> str:
    """Return "sv" for Swedish speech, otherwise the target language code."""
    if not any(c.isalpha() for c in transcript):
        return target
    detected = _detector(target.split("-")[0].lower()).detect_language_of(transcript)
    return "sv" if detected == Language.SWEDISH else target
