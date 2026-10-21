import random

import pytest
from sqlalchemy import select

from app.data.assessment_bank import get_assessment_bank
from app.lalapp.learner import rating
from app.lalapp.models import ItemRating, LearnerSkill
from app.lalapp.placement import engine

LANGUAGE = "en-US"


def _simulate(true_theta, *, language="es-ES", seed=1, self_level=None):
    rng = random.Random(seed)
    bank = get_assessment_bank(language)
    state = engine.PlacementState.start(sorted({i.skill for i in bank}), self_level)
    estimates = {item.id: engine.bank_item_prior(item) for item in bank}
    while True:
        item = engine.next_item(state, bank, estimates, rng)
        p = rating.sigmoid(true_theta - rating.CEFR_ITEM_DIFFICULTY[item.difficulty])
        answer = item.correct if rng.random() < p else engine.DONT_KNOW_ANSWER
        engine.record(state, item, estimates[item.id], answer)
        if engine.is_finished(state, len(bank) - len(state.asked)):
            return state


@pytest.mark.parametrize("level", ["A1", "A2", "B1", "B2", "C1"])
def test_simulated_learner_is_placed_at_their_level(level):
    # Middle of the band: half a logit above the level's mastery boundary.
    true_theta = rating.learner_prior(level).mean + 0.5
    placed = [engine.result(_simulate(true_theta, seed=seed))["cefr_level"] for seed in range(20)]
    index = rating.CEFR_LEVELS.index(level)
    near = [lvl for lvl in placed if abs(rating.CEFR_LEVELS.index(lvl) - index) <= 1]
    assert len(near) == len(placed), placed
    assert placed.count(level) >= 12, placed


def test_test_length_stays_within_bounds_and_precision_improves():
    state = _simulate(0.5)
    assert engine.MIN_QUESTIONS <= len(state.asked) <= engine.MAX_QUESTIONS
    assert state.overall.sd < engine.UNKNOWN_START_SD
    assert len(set(state.asked)) == len(state.asked)


def test_questions_rotate_across_skills():
    state = _simulate(0.0)
    counts = {skill: 0 for skill in state.skills}
    for response in state.responses:
        counts[response["skill"]] += 1
    assert max(counts.values()) - min(counts.values()) <= 1


def test_dont_know_scores_zero_and_marks_gap():
    bank = get_assessment_bank("es-ES")
    item = bank[0]
    state = engine.PlacementState.start(["grammar", "reading", "vocabulary"])
    score, _ = engine.record(state, item, engine.bank_item_prior(item), engine.DONT_KNOW_ANSWER)
    assert score == 0.0
    assert state.responses[-1]["dont_know"] is True


def test_result_matches_upstream_assessment_shape():
    result = engine.result(_simulate(0.0))
    assert result["cefr_level"] in rating.CEFR_LEVELS
    assert set(result["skill_profile"]) == {"grammar", "reading", "vocabulary"}
    assert all(0 <= v <= 1 for v in result["skill_profile"].values())
    assert 0 <= result["score"] <= 1
    assert isinstance(result["strengths"], list) and isinstance(result["weaknesses"], list)


def test_state_round_trips_through_json():
    state = _simulate(1.0)
    restored = engine.PlacementState.from_json(state.to_json())
    assert restored.overall == state.overall
    assert restored.skills == state.skills
    assert restored.asked == state.asked


async def _run_placement(client, headers, *, correct: bool):
    bank = {item.id: item for item in get_assessment_bank(LANGUAGE)}
    step = (
        await client.post(
            "/api/lalapp/placement/start", headers=headers, json={"language": LANGUAGE}
        )
    ).json()
    session_id = step["session_id"]
    while step["question"] is not None:
        assert "correct" not in step["question"]
        item = bank[step["question"]["id"]]
        answer = item.correct if correct else engine.DONT_KNOW_ANSWER
        response = await client.post(
            f"/api/lalapp/placement/{session_id}/answer",
            headers=headers,
            json={"question_id": item.id, "answer": answer},
        )
        assert response.status_code == 200, response.text
        step = response.json()
    return session_id, step


async def test_placement_api_places_strong_learner_high_and_seeds_learner_model(
    client, db_session, test_user
):
    user, headers = test_user
    session_id, step = await _run_placement(client, headers, correct=True)

    assert step["result"]["cefr_level"] in {"C1", "C2"}
    assert step["question_number"] <= engine.MAX_QUESTIONS
    skills = (await db_session.scalars(select(LearnerSkill))).all()
    assert {s.skill for s in skills} == set(rating.SKILLS)
    assert all(rating.cefr_from_theta(s.theta) in {"B2", "C1", "C2"} for s in skills)
    calibrated = (await db_session.scalars(select(ItemRating))).all()
    assert len(calibrated) == step["question_number"]

    finished = await client.post(
        f"/api/lalapp/placement/{session_id}/answer",
        headers=headers,
        json={"question_id": "x", "answer": "y"},
    )
    assert finished.status_code == 409


async def test_placement_api_places_non_answering_learner_at_a1(client, test_user):
    _, headers = test_user
    _, step = await _run_placement(client, headers, correct=False)
    assert step["result"]["cefr_level"] == "A1"


async def test_placement_api_rejects_wrong_question_and_other_users(client, test_user, admin_user):
    _, headers = test_user
    _, admin_headers = admin_user
    step = (
        await client.post(
            "/api/lalapp/placement/start", headers=headers, json={"language": LANGUAGE}
        )
    ).json()
    url = f"/api/lalapp/placement/{step['session_id']}/answer"

    mismatch = await client.post(
        url, headers=headers, json={"question_id": "not-it", "answer": "a"}
    )
    assert mismatch.status_code == 409
    foreign = await client.post(
        url, headers=admin_headers, json={"question_id": step["question"]["id"], "answer": "a"}
    )
    assert foreign.status_code == 404
    unsupported = await client.post(
        "/api/lalapp/placement/start", headers=headers, json={"language": "xx-XX"}
    )
    assert unsupported.status_code == 422
