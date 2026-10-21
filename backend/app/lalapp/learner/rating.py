"""Online ability/difficulty estimation on a logistic (Rasch) scale.

Each response is treated as a match between a learner skill (theta) and an item (difficulty
b): P(success) = sigmoid(theta - b). Both sides keep a variance, and each update is a single
Laplace/Kalman step: the step size equals the posterior variance, so updates are large while
little is known and shrink as evidence accumulates. That is the damping that makes estimates
settle instead of oscillating. Uncertainty on the other side is discounted Glicko-style.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
SKILLS = ("vocabulary", "grammar", "reading", "listening", "speaking", "writing")

# Typical difficulty of an item written for each CEFR level.
CEFR_ITEM_DIFFICULTY = {"A1": -2.5, "A2": -1.5, "B1": -0.5, "B2": 0.5, "C1": 1.5, "C2": 2.5}

# A learner is "at" a level when they succeed on about 70% of that level's items.
MASTERY_PROBABILITY = 0.7
MASTERY_OFFSET = math.log(MASTERY_PROBABILITY / (1 - MASTERY_PROBABILITY))

LEARNER_PRIOR_SD = 1.0
ITEM_PRIOR_SD = 1.0
MIN_SD = 0.15
MAX_SD = 1.5
# Variance added per day without evidence: learners improve and forget between sessions.
LEARNER_DRIFT_PER_DAY = 0.002


@dataclass(frozen=True)
class Estimate:
    mean: float
    sd: float


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _discount(other_variance: float) -> float:
    # Glicko-style g(): a less certain opponent makes the result less informative. Uses the
    # probit approximation E[sigmoid(x)] ~= sigmoid(mu / sqrt(1 + pi * var / 8)).
    return 1.0 / math.sqrt(1.0 + math.pi * other_variance / 8.0)


def expected_score(learner: Estimate, item: Estimate) -> float:
    return sigmoid(learner.mean - item.mean)


def _step(own: Estimate, other: Estimate, observed: float, sign: float) -> Estimate:
    g = _discount(other.sd**2)
    # Probability that the learner succeeds; the same quantity for both sides of the match.
    p_success = sigmoid(sign * g * (own.mean - other.mean))
    information = g**2 * p_success * (1.0 - p_success)
    variance = 1.0 / (1.0 / own.sd**2 + information)
    mean = own.mean + sign * variance * g * (observed - p_success)
    sd = min(MAX_SD, max(MIN_SD, math.sqrt(variance)))
    return Estimate(mean, sd)


def update(learner: Estimate, item: Estimate, observed: float) -> tuple[Estimate, Estimate]:
    """Return the updated (learner, item) estimates after one scored response.

    ``observed`` is a score in [0, 1]; partial credit from graded answers is used directly.
    """
    observed = min(1.0, max(0.0, observed))
    new_learner = _step(learner, item, observed, 1.0)
    # For the item, "winning" means the learner failed, hence the mirrored sign.
    new_item = _step(item, learner, observed, -1.0)
    return new_learner, new_item


def drift(estimate: Estimate, days: float) -> Estimate:
    if days <= 0:
        return estimate
    variance = estimate.sd**2 + LEARNER_DRIFT_PER_DAY * days
    return Estimate(estimate.mean, min(MAX_SD, math.sqrt(variance)))


def normalize_level(level: str | None) -> str | None:
    if not level:
        return None
    level = level.strip().upper()[:2]
    return level if level in CEFR_ITEM_DIFFICULTY else None


def item_prior(level: str | None, sd: float = ITEM_PRIOR_SD) -> Estimate:
    level = normalize_level(level)
    mean = CEFR_ITEM_DIFFICULTY[level] if level else 0.0
    return Estimate(mean, sd)


def learner_prior(level: str | None, sd: float = LEARNER_PRIOR_SD) -> Estimate:
    level = normalize_level(level)
    mean = CEFR_ITEM_DIFFICULTY[level] + MASTERY_OFFSET if level else 0.0
    return Estimate(mean, sd)


def cefr_from_theta(theta: float) -> str:
    """Highest level whose typical items the learner passes with mastery probability."""
    reached = CEFR_LEVELS[0]
    for level in CEFR_LEVELS:
        if theta >= CEFR_ITEM_DIFFICULTY[level] + MASTERY_OFFSET:
            reached = level
    return reached
