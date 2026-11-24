"""Home game generation: draft formats, salvage and the child prompt suffix."""

import random
from unittest.mock import AsyncMock

import pytest

from app.home import games
from app.home.context import HomeLearner, use_learner
from app.home.game_schemas import (
    DetectiveDraft,
    DetectiveDraftContent,
    SentenceOrderDraftContent,
    VocabularyPairsDraftContent,
)
from app.home.prompts import child_instruction
from app.schemas.games import DetectiveChallenge, DetectiveReview
from tests.test_sentence_order import order_content
from tests.test_vocabulary_pairs import pairs_content


def draft_dict(i=0, source="grammar:present-simple", **override):
    return {
        "sentence": f"She go to school on day {i}.",
        "wrong_part": "go",
        "correct_part": "goes",
        "wrong_options": ["going", "gone"],
        "explanation": "Con she, el presente simple lleva -s.",
        "source_id": source,
        **override,
    }


def draft_content(source="grammar:present-simple", count=8):
    return DetectiveDraftContent(challenges=[draft_dict(i, source) for i in range(count)])


def order_draft(source="grammar:present-simple", count=8, broken=()):
    items = [c.model_dump() for c in order_content(source).challenges]
    items += [
        {
            **items[0],
            "sentence": f"I often walk to town {i}.",
            "fragments": ["often", "I", "walk", f"to town {i}."],
        }
        for i in range(count - 5)
    ]
    for i in broken:
        items[i] = {**items[i], "accepted_orders": [[0, 0, 0, 0]]}
    return SentenceOrderDraftContent(challenges=items[:count])


def pairs_draft(source="vocabulary:test"):
    items = [c.model_dump() for c in pairs_content(source).challenges]
    items.insert(1, {**items[0], "term": "bird"})  # duplicate meaning: dropped
    items.append({"term": "x"})  # malformed: dropped
    items.append({**items[0], "term": "fish", "meaning": "pez"})
    return VocabularyPairsDraftContent(challenges=items)


def generation_request(game_type="detective", source="grammar:present-simple"):
    return games.GenerationRequest(
        game_type=game_type,
        mode="free",
        target_language="en-GB",
        native_language="es",
        level="A1",
        context={"sources": [{"source_id": source}], "recent_sentences": []},
    )


def test_build_challenge_splits_and_shuffles():
    draft = DetectiveDraft(**draft_dict(3))
    seen = set()
    for seed in range(20):
        random.seed(seed)
        challenge = games.build_challenge(draft)
        assert DetectiveChallenge.model_validate(challenge.model_dump())
        assert "".join(challenge.fragments) == draft.sentence
        assert challenge.fragments[challenge.error_index] == "go"
        assert challenge.options[challenge.correct_index] == "goes"
        assert sorted(challenge.options) == ["goes", "going", "gone"]
        assert challenge.corrected_sentence == "She goes to school on day 3."
        seen.add(challenge.correct_index)
    assert len(seen) > 1


def test_wrong_part_not_in_sentence_is_dropped():
    for override in (
        {"wrong_part": "walks"},
        {"sentence": "She go and go.", "wrong_part": "go"},
        {"correct_part": "go"},
        {"wrong_options": ["going", "going"]},
        {"wrong_options": ["goes", "gone"]},
    ):
        with pytest.raises(ValueError):
            games.build_challenge(DetectiveDraft(**draft_dict(0, **override)))
    kept = games.salvage_challenges(
        [{**draft_dict(0), "wrong_part": "walks"}] + [draft_dict(i) for i in range(1, 7)]
    )
    assert len(kept) == 5
    assert all(c.sentence != "She go to school on day 0." for c in kept)


def test_salvage_keeps_valid_when_some_fail():
    drafts = [draft_dict(i) for i in range(8)]
    drafts[1] = {"sentence": "broken"}
    drafts[4]["wrong_part"] = "absent"
    kept = games.salvage_challenges(drafts)
    assert [c.sentence for c in kept] == [f"She go to school on day {i}." for i in (0, 2, 3, 5, 6)]


def test_too_few_valid_raises():
    drafts = [draft_dict(i) for i in range(4)] + [{"sentence": "x"}] * 4
    with pytest.raises(games.LLMResponseError):
        games.salvage_challenges(drafts)


async def test_child_flag_reaches_prompt(monkeypatch):
    mocked = AsyncMock(side_effect=[draft_content(), DetectiveReview(valid=True, reason="ok")])
    monkeypatch.setattr(games.llm_adapter, "structured_output", mocked)
    with use_learner(HomeLearner(is_child=True)):
        result = await games.generate_content(generation_request(), 1e12)
    assert len(result.challenges) == 5
    assert child_instruction() in mocked.call_args_list[0].args[0][0]["content"]
    assert mocked.call_args_list[0].args[1] is DetectiveDraftContent


async def test_adult_prompt_has_no_child_instruction(monkeypatch):
    mocked = AsyncMock(side_effect=[draft_content(), DetectiveReview(valid=True, reason="ok")])
    monkeypatch.setattr(games.llm_adapter, "structured_output", mocked)
    await games.generate_content(generation_request(), 1e12)
    assert child_instruction() not in mocked.call_args_list[0].args[0][0]["content"]


def test_mid_word_match_is_dropped():
    draft = DetectiveDraft(
        **draft_dict(
            0,
            sentence="He doesn't like it.",
            wrong_part="do",
            correct_part="does",
            wrong_options=["did", "done"],
        )
    )
    with pytest.raises(ValueError):
        games.build_challenge(draft)


def test_bounded_match_beside_longer_word_is_kept():
    draft = DetectiveDraft(
        **draft_dict(0, sentence="She go to school, going home.", wrong_part="go")
    )
    challenge = games.build_challenge(draft)
    assert challenge.fragments[challenge.error_index] == "go"
    assert challenge.corrected_sentence == "She goes to school, going home."


async def test_order_salvage_drops_invalid_items(monkeypatch):
    source = "grammar:present-simple"
    draft = order_draft(source, count=5)
    draft.challenges.append(order_draft(source).challenges[5])
    draft.challenges[2] = {**draft.challenges[2], "fragments": ["a"]}
    mock = AsyncMock(side_effect=[draft, DetectiveReview(valid=True, reason="ok")])
    monkeypatch.setattr(games.llm_adapter, "structured_output", mock)
    content = await games.generate_content(generation_request("sentence-order", source), 1e12)
    assert len(content.challenges) == 5
    assert all(c.sentence != "I often walk to school on day 2." for c in content.challenges)
    assert mock.call_args_list[0].args[1] is SentenceOrderDraftContent


async def test_pairs_salvage_drops_duplicates_and_malformed(monkeypatch):
    source = "vocabulary:test"
    mock = AsyncMock(side_effect=[pairs_draft(source), DetectiveReview(valid=True, reason="ok")])
    monkeypatch.setattr(games.llm_adapter, "structured_output", mock)
    content = await games.generate_content(generation_request("vocabulary-pairs", source), 1e12)
    assert mock.call_args_list[0].args[1] is VocabularyPairsDraftContent
    assert {(c.term, c.meaning) for c in content.challenges} == {
        (c.term, c.meaning) for c in pairs_content().challenges
    }


def test_upstream_prompts_unchanged():
    from app.services.prompts.games import detective_prompt

    assert "exactly five" in detective_prompt("en-GB", "sv", "A1", "review", {})


@pytest.mark.parametrize(
    ("game_type", "source", "draft"),
    [
        ("detective", "grammar:present-simple", lambda s: draft_content(s)),
        ("sentence-order", "grammar:present-simple", lambda s: order_draft(s)),
        ("vocabulary-pairs", "vocabulary:test", lambda s: pairs_draft(s)),
    ],
)
async def test_review_specification_asks_for_the_kept_five(monkeypatch, game_type, source, draft):
    # The model drafts eight items but the app keeps five: a reviewer told "eight" rejects them all.
    mock = AsyncMock(side_effect=[draft(source), DetectiveReview(valid=True, reason="ok")])
    monkeypatch.setattr(games.llm_adapter, "structured_output", mock)
    await games.generate_content(generation_request(game_type, source), 1e12)
    draft_prompt = mock.call_args_list[0].args[0][0]["content"]
    review_prompt = mock.call_args_list[1].args[0][0]["content"]
    assert "exactly eight" in draft_prompt
    assert "exactly eight" not in review_prompt
    assert "exactly five" in review_prompt.split("SPECIFICATION:")[1]
