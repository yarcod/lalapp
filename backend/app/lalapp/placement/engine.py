"""Computerised adaptive placement over upstream's static assessment bank.

Pure logic: the caller supplies the bank, the item difficulty estimates and the session state.
Each answer updates an overall ability estimate and a per-skill estimate. The next question is
the most informative one (expected success closest to 50%) for the least-tested skill, and the
test stops once the overall estimate is precise enough.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.lalapp.learner import rating
from app.lalapp.learner.rating import Estimate

MIN_QUESTIONS = 10
MAX_QUESTIONS = 25
STOP_SD = 0.45
# Unknown starting point: centred on B1 mastery, the middle of the scale, with a spread wide
# enough that shrinkage toward it stays small at both ends. Beginners can start lower by
# passing a self-assessed level.
DEFAULT_START_LEVEL = "B1"
UNKNOWN_START_SD = 2.0
SELF_ASSESSED_START_SD = 1.0
# Bank items carry a curated CEFR label, so their difficulty prior is tighter than for templates.
BANK_ITEM_PRIOR_SD = 0.5
# Pick randomly among the few most informative items, so repeated tests differ.
SELECTION_POOL = 3
DONT_KNOW_ANSWER = "__dont_know__"  # Matches the upstream quiz card's sentinel.

STRENGTH_THRESHOLD = 0.65  # Upstream's strength/weakness thresholds on skill profiles.
WEAKNESS_THRESHOLD = 0.45
NEUTRAL_PROFILE = 0.55
_NEUTRAL_PROFILE_LOGIT = math.log(NEUTRAL_PROFILE / (1 - NEUTRAL_PROFILE))


class BankItem(Protocol):
    id: str
    skill: str
    difficulty: str
    correct: str


@dataclass
class PlacementState:
    overall: Estimate
    skills: dict[str, Estimate]
    asked: list[str] = field(default_factory=list)
    responses: list[dict] = field(default_factory=list)

    @classmethod
    def start(cls, skills: Sequence[str], self_level: str | None = None) -> PlacementState:
        if rating.normalize_level(self_level):
            prior = rating.learner_prior(self_level, SELF_ASSESSED_START_SD)
        else:
            prior = rating.learner_prior(DEFAULT_START_LEVEL, UNKNOWN_START_SD)
        return cls(overall=prior, skills=dict.fromkeys(skills, prior))

    def to_json(self) -> dict:
        return {
            "overall": [self.overall.mean, self.overall.sd],
            "skills": {k: [v.mean, v.sd] for k, v in self.skills.items()},
            "asked": self.asked,
            "responses": self.responses,
        }

    @classmethod
    def from_json(cls, data: Mapping) -> PlacementState:
        return cls(
            overall=Estimate(*data["overall"]),
            skills={k: Estimate(*v) for k, v in data["skills"].items()},
            asked=list(data["asked"]),
            responses=list(data["responses"]),
        )


def bank_item_key(target_language: str, item_id: str) -> str:
    return f"bank:{target_language}:{item_id}"


def bank_item_prior(item: BankItem) -> Estimate:
    return rating.item_prior(item.difficulty, BANK_ITEM_PRIOR_SD)


def score_answer(item: BankItem, answer: str) -> float:
    return 1.0 if answer != DONT_KNOW_ANSWER and answer == item.correct else 0.0


def record(
    state: PlacementState, item: BankItem, item_est: Estimate, answer: str
) -> tuple[float, Estimate]:
    """Apply one answer; returns the score and the updated item estimate."""
    score = score_answer(item, answer)
    state.overall, new_item = rating.update(state.overall, item_est, score)
    if item.skill in state.skills:
        state.skills[item.skill], _ = rating.update(state.skills[item.skill], item_est, score)
    state.asked.append(item.id)
    state.responses.append(
        {
            "id": item.id,
            "skill": item.skill,
            "score": score,
            "dont_know": answer == DONT_KNOW_ANSWER,
        }
    )
    return score, new_item


def is_finished(state: PlacementState, remaining: int) -> bool:
    n = len(state.asked)
    if remaining == 0 or n >= MAX_QUESTIONS:
        return True
    return n >= MIN_QUESTIONS and state.overall.sd < STOP_SD


def next_item(
    state: PlacementState,
    bank: Sequence[BankItem],
    estimates: Mapping[str, Estimate],
    rng: random.Random,
) -> BankItem | None:
    """``estimates`` maps item id to its current difficulty estimate."""
    asked = set(state.asked)
    remaining = [item for item in bank if item.id not in asked]
    if not remaining:
        return None
    counts = {skill: 0 for skill in state.skills}
    for response in state.responses:
        if response["skill"] in counts:
            counts[response["skill"]] += 1
    available = {item.skill for item in remaining}
    skill = min((s for s in counts if s in available), key=lambda s: counts[s], default=None)
    candidates = [item for item in remaining if skill is None or item.skill == skill]
    candidates.sort(
        key=lambda item: abs(rating.expected_score(state.overall, estimates[item.id]) - 0.5)
    )
    return rng.choice(candidates[:SELECTION_POOL])


def result(state: PlacementState) -> dict:
    """Upstream's AssessmentResult shape, so its plan-creation flow can be reused unchanged."""
    level = rating.cefr_from_theta(state.overall.mean)
    # Skills are profiled relative to the overall estimate: a skill level with the overall
    # ability sits at NEUTRAL_PROFILE, between upstream's weakness and strength thresholds.
    profile = {
        skill: round(rating.sigmoid(estimate.mean - state.overall.mean + _NEUTRAL_PROFILE_LOGIT), 2)
        for skill, estimate in state.skills.items()
    }
    gaps = {skill: 0 for skill in state.skills}
    totals = {skill: 0 for skill in state.skills}
    for response in state.responses:
        if response["skill"] in totals:
            totals[response["skill"]] += 1
            gaps[response["skill"]] += response["dont_know"]
    return {
        "cefr_level": level,
        # Expected success on typical items of the placed level.
        "score": round(rating.expected_score(state.overall, rating.item_prior(level)), 2),
        "skill_profile": profile,
        "strengths": [s for s, v in profile.items() if v >= STRENGTH_THRESHOLD],
        "weaknesses": [
            s
            for s, v in profile.items()
            if v < WEAKNESS_THRESHOLD or (totals[s] and gaps[s] / totals[s] >= 0.5)
        ],
        "theta": round(state.overall.mean, 3),
        "theta_sd": round(state.overall.sd, 3),
        "questions_answered": len(state.asked),
    }
