import random

import pytest

from app.lalapp.learner import rating
from app.lalapp.learner.rating import Estimate


def test_success_raises_learner_and_lowers_item():
    learner, item = Estimate(0.0, 1.0), Estimate(0.0, 1.0)
    new_learner, new_item = rating.update(learner, item, 1.0)
    assert new_learner.mean > learner.mean
    assert new_item.mean < item.mean
    assert new_learner.sd < learner.sd and new_item.sd < item.sd


def test_failure_lowers_learner_and_raises_item():
    new_learner, new_item = rating.update(Estimate(0.0, 1.0), Estimate(0.0, 1.0), 0.0)
    assert new_learner.mean < 0.0
    assert new_item.mean > 0.0


def test_expected_outcome_barely_moves_a_confident_estimate():
    learner, item = Estimate(1.0, 0.2), Estimate(-1.0, 0.2)
    new_learner, _ = rating.update(learner, item, rating.expected_score(learner, item))
    assert new_learner.mean == pytest.approx(learner.mean, abs=0.01)


def test_step_size_shrinks_as_evidence_accumulates():
    learner, item = Estimate(0.0, 1.0), Estimate(0.0, 0.3)
    steps = []
    for _ in range(10):
        updated, _ = rating.update(learner, item, 1.0)
        steps.append(updated.mean - learner.mean)
        learner = Estimate(learner.mean, updated.sd)  # same position, growing certainty
    assert all(a > b for a, b in zip(steps, steps[1:], strict=False))


@pytest.mark.parametrize("true_theta", [-2.0, 0.0, 1.8])
def test_estimate_converges_on_true_ability(true_theta):
    rng = random.Random(42)
    learner = rating.learner_prior("A2")
    items = [Estimate(rng.uniform(-3, 3), 0.15) for _ in range(300)]
    for item in items:
        observed = 1.0 if rng.random() < rating.sigmoid(true_theta - item.mean) else 0.0
        learner, _ = rating.update(learner, item, observed)
    assert learner.mean == pytest.approx(true_theta, abs=0.35)
    assert learner.sd < 0.3


def test_partial_scores_are_clamped():
    a, _ = rating.update(Estimate(0.0, 1.0), Estimate(0.0, 1.0), 1.7)
    b, _ = rating.update(Estimate(0.0, 1.0), Estimate(0.0, 1.0), 1.0)
    assert a == b


def test_drift_widens_uncertainty_over_time_but_is_capped():
    assert rating.drift(Estimate(0.0, 0.2), 0).sd == 0.2
    assert rating.drift(Estimate(0.0, 0.2), 30).sd > 0.2
    assert rating.drift(Estimate(0.0, 0.2), 10_000).sd == rating.MAX_SD


def test_priors_and_cefr_mapping_agree():
    for level in rating.CEFR_LEVELS:
        assert rating.cefr_from_theta(rating.learner_prior(level).mean) == level
        prior = rating.learner_prior(level)
        assert rating.expected_score(prior, rating.item_prior(level)) == pytest.approx(
            rating.MASTERY_PROBABILITY
        )
    assert rating.cefr_from_theta(-10.0) == "A1"
    assert rating.cefr_from_theta(10.0) == "C2"


def test_unknown_level_falls_back_to_scale_centre():
    assert rating.item_prior(None).mean == 0.0
    assert rating.learner_prior("zz").mean == 0.0
    assert rating.normalize_level("b2+") == "B2"
