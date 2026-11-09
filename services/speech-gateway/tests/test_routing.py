import pytest

from gateway.routing import decide_language


@pytest.mark.parametrize("text", ["", "...", "   "])
def test_empty_transcript_is_target(text):
    assert decide_language(text, "en") == "en"


def test_swedish_sentence():
    assert decide_language("Jag vet inte vad det heter", "en") == "sv"


@pytest.mark.parametrize("text", ["He have two cats", "My dog are big"])
def test_learner_english_stays_target(text):
    assert decide_language(text, "en") == "en"


def test_swedish_question_with_english_word():
    assert decide_language("Vad heter hund på engelska", "en") == "sv"
