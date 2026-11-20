from app.home.context import HomeLearner, use_learner
from app.home.prompts import child_instruction, child_suffix, instruction_language_rules
from app.services.prompts.lesson import build_lesson_generation_prompt
from app.services.prompts.tutor import build_conversation_system_prompt, build_tutor_system_prompt

CHILD_SV = HomeLearner(is_child=True, native_code="sv")
ADULT_SV = HomeLearner(is_child=False, native_code="sv")


def test_a1_swedish_native_requests_tags() -> None:
    rules = instruction_language_rules("A1", "sv", "en-GB")
    for tag in ("[sv]", "[en]", "[screen]"):
        assert tag in rules
    assert "[es]" not in rules
    assert "[es]" in instruction_language_rules("A2", "sv", "es-ES")


def test_b1_keeps_target_language_only() -> None:
    assert instruction_language_rules("B1", "sv", "en-GB") == ""
    assert instruction_language_rules("C2", "sv", "es-ES") == ""


def test_non_swedish_native_has_no_rules() -> None:
    assert instruction_language_rules("A1", "es", "en-GB") == ""
    assert instruction_language_rules("A1", "", "en-GB") == ""


def test_child_suffix_empty_by_default() -> None:
    assert child_suffix() == ""


def test_child_suffix_for_child() -> None:
    with use_learner(CHILD_SV):
        assert child_suffix() == "\n\n" + child_instruction()


def test_child_instruction_present_when_child() -> None:
    from app.home.game_prompts import (
        detective_prompt,
        sentence_order_prompt,
        vocabulary_pairs_prompt,
    )

    text = child_instruction()
    assert "child" in text and "9-11" in text
    tutor_kwargs = {
        "student_name": "Kid",
        "cefr_level": "A1",
        "native_language": "Swedish",
        "target_code": "en-GB",
        "target_language_name": "British English",
        "user_context": "",
        "memory_context": "",
    }
    chat_kwargs = {
        **tutor_kwargs,
        "total_xp": 0,
        "streak": 0,
        "lessons_today": 0,
        "skills": "none",
    }
    with use_learner(CHILD_SV):
        assert text in build_tutor_system_prompt(**chat_kwargs)
        assert text in build_conversation_system_prompt(**tutor_kwargs)
    with use_learner(ADULT_SV):
        assert text not in build_tutor_system_prompt(**chat_kwargs)
        assert "[screen]" in build_tutor_system_prompt(**chat_kwargs)
        assert text not in build_conversation_system_prompt(**tutor_kwargs)
        # B1 and non-Swedish prompts carry no tag rules.
        assert "[screen]" not in build_conversation_system_prompt(
            **{**tutor_kwargs, "cefr_level": "B1"}
        )
    lesson = dict(
        cefr_level="A1",
        target_language_name="British English",
        lesson_type="vocabulary",
        topic="pets",
        unit_id="u",
        grammar_points="x",
        vocabulary_set_ids="y",
        week=1,
        day=1,
        valid_slugs="z",
    )
    with use_learner(CHILD_SV):
        assert text in build_lesson_generation_prompt(**lesson)
        assert "[screen]" not in build_lesson_generation_prompt(**lesson)
    assert text not in build_lesson_generation_prompt(**lesson)
    for builder in (detective_prompt, sentence_order_prompt, vocabulary_pairs_prompt):
        with use_learner(CHILD_SV):
            assert text in builder("en-GB", "sv", "A1", "review", {})
        assert text not in builder("en-GB", "sv", "A1", "review", {})


def test_prompt_requests_eight() -> None:
    from app.home.game_prompts import (
        detective_prompt,
        sentence_order_prompt,
        vocabulary_pairs_prompt,
    )

    for builder in (detective_prompt, sentence_order_prompt, vocabulary_pairs_prompt):
        text = builder("en-GB", "sv", "A1", "review", {})
        assert "exactly eight" in text and "exactly five" not in text
    detective = detective_prompt("en-GB", "sv", "A1", "review", {})
    for field in ("wrong_part", "correct_part", "wrong_options"):
        assert field in detective
    assert '"fragments"' not in detective
