"""Lenient draft formats the model writes for home game generation."""

from typing import Any

from pydantic import BaseModel, Field


class DetectiveDraft(BaseModel):
    """What the model writes for Error Detective; the app builds the playable challenge."""

    sentence: str = Field(min_length=3, max_length=500)
    wrong_part: str = Field(min_length=1, max_length=200)
    correct_part: str = Field(min_length=1, max_length=200)
    wrong_options: list[str] = Field(min_length=2, max_length=2)
    explanation: str = Field(min_length=10, max_length=1000)
    source_id: str = Field(min_length=1, max_length=100)


class _DraftContent(BaseModel):
    """Lenient model output: items are validated one by one so a bad item is only dropped."""

    challenges: list[dict[str, Any]] = Field(min_length=1, max_length=16)


class DetectiveDraftContent(_DraftContent):
    pass


class SentenceOrderDraftContent(_DraftContent):
    pass


class VocabularyPairsDraftContent(_DraftContent):
    pass
