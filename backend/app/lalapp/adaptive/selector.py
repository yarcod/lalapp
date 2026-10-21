"""Choose the next lesson from the learner model.

Pure functions over skill estimates and the curriculum, so the policy can be tested without a
database or an LLM. The policy, in order:

1. Skill: the plan goal skill with the largest gap below mastery of the plan level, plus a bonus
   for uncertainty (an unexplored skill is worth a look) and a penalty for repeating the skill
   of the previous adaptive lesson.
2. Difficulty: the plan level, stepped down one level while predicted success there is below
   ``STEP_DOWN_BELOW`` and up one level as a stretch when predicted success one level higher is
   at least ``STEP_UP_FROM``.
3. Content: a grammar point the response log shows as weak (review), otherwise the unit the plan
   is on, or the following unit when the learner is well ahead in grammar (preview).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.lalapp.learner import rating

LESSON_SKILLS = ("grammar", "vocabulary", "reading", "writing", "listening", "speaking")

UNCERTAINTY_WEIGHT = 0.5
REPEAT_PENALTY = 0.4
STEP_DOWN_BELOW = 0.55
STEP_UP_FROM = 0.75
PREVIEW_MARGIN = 0.5

# Per grammar point, a Beta prior worth this many responses at this success rate.
SLUG_PRIOR_N = 2.0
SLUG_PRIOR_MEAN = 0.7
WEAK_SLUG_MIN_N = 3
WEAK_SLUG_BELOW = 0.6

# Level-up: every goal skill with enough evidence must clear mastery of the next level by one
# standard deviation, and at least two skills must have that much evidence.
LEVEL_UP_MIN_N = 20
LEVEL_UP_MIN_SKILLS = 2
LEVEL_UP_Z = 1.0


@dataclass(frozen=True)
class Unit:
    id: str
    title: str
    grammar_points: tuple[str, ...]
    vocabulary_set_ids: tuple[str, ...]


@dataclass(frozen=True)
class SlugStat:
    n: int
    score_sum: float

    @property
    def mean(self) -> float:
        return (self.score_sum + SLUG_PRIOR_N * SLUG_PRIOR_MEAN) / (self.n + SLUG_PRIOR_N)


@dataclass(frozen=True)
class Recommendation:
    skill: str
    cefr_level: str
    unit: Unit | None
    focus: tuple[str, ...]
    reason: str  # "practice", "review" or "preview"
    predicted_success: float


def mastery_theta(level: str) -> float:
    return rating.learner_prior(level).mean


def goal_skills(goals: list[str] | None) -> tuple[str, ...]:
    chosen = tuple(s for s in LESSON_SKILLS if goals and s in goals)
    return chosen or LESSON_SKILLS


def skill_priority(estimate: rating.Estimate, plan_level: str, *, repeated: bool) -> float:
    gap = mastery_theta(plan_level) - estimate.mean
    return gap + UNCERTAINTY_WEIGHT * estimate.sd - (REPEAT_PENALTY if repeated else 0.0)


def choose_skill(
    estimates: dict[str, rating.Estimate],
    plan_level: str,
    goals: list[str] | None,
    last_skill: str | None,
) -> str:
    prior = rating.learner_prior(plan_level)
    return max(
        goal_skills(goals),
        key=lambda s: skill_priority(estimates.get(s, prior), plan_level, repeated=s == last_skill),
    )


def choose_level(
    estimate: rating.Estimate, plan_level: str, difficulty: dict[str, float]
) -> tuple[str, float]:
    """Lesson level and the predicted per-exercise success there.

    ``difficulty`` maps a CEFR level to the item difficulty of this kind of lesson; levels it
    lacks use the CEFR anchor.
    """

    def success(level: str) -> float:
        b = difficulty.get(level, rating.CEFR_ITEM_DIFFICULTY[level])
        return rating.expected_score(estimate, rating.Estimate(b, 0.0))

    index = rating.CEFR_LEVELS.index(plan_level)
    level = plan_level
    if success(level) < STEP_DOWN_BELOW and index > 0:
        level = rating.CEFR_LEVELS[index - 1]
    elif index + 1 < len(rating.CEFR_LEVELS):
        higher = rating.CEFR_LEVELS[index + 1]
        if success(higher) >= STEP_UP_FROM:
            level = higher
    return level, success(level)


def weak_slugs(stats: dict[str, SlugStat], allowed: set[str]) -> list[str]:
    """Grammar points with enough evidence of trouble, weakest first."""
    weak = [
        slug
        for slug, stat in stats.items()
        if slug in allowed and stat.n >= WEAK_SLUG_MIN_N and stat.mean < WEAK_SLUG_BELOW
    ]
    return sorted(weak, key=lambda slug: stats[slug].mean)


def choose_content(
    skill: str,
    estimate: rating.Estimate,
    plan_level: str,
    units: list[Unit],
    current_unit_id: str | None,
    slug_stats: dict[str, SlugStat],
) -> tuple[Unit | None, tuple[str, ...], str]:
    if not units:
        return None, (), "practice"
    index = next((i for i, u in enumerate(units) if u.id == current_unit_id), 0)
    current = units[index]

    if skill in ("grammar", "writing"):
        # Only what the learner has reached: units up to and including the current one.
        reached = units[: index + 1]
        slug_unit = {slug: u for u in reached for slug in u.grammar_points}
        weak = weak_slugs(slug_stats, set(slug_unit))
        if weak:
            return slug_unit[weak[0]], (weak[0],), "review"

    if (
        skill == "grammar"
        and index + 1 < len(units)
        and estimate.mean - estimate.sd >= mastery_theta(plan_level) + PREVIEW_MARGIN
    ):
        upcoming = units[index + 1]
        return upcoming, upcoming.grammar_points, "preview"

    return current, current.grammar_points, "practice"


def recommend(
    *,
    estimates: dict[str, rating.Estimate],
    plan_level: str,
    goals: list[str] | None,
    last_skill: str | None,
    units: list[Unit],
    current_unit_id: str | None,
    slug_stats: dict[str, SlugStat],
    difficulty: dict[str, dict[str, float]] | None = None,
) -> Recommendation:
    skill = choose_skill(estimates, plan_level, goals, last_skill)
    estimate = estimates.get(skill, rating.learner_prior(plan_level))
    level, predicted = choose_level(estimate, plan_level, (difficulty or {}).get(skill, {}))
    unit, focus, reason = choose_content(
        skill, estimate, plan_level, units, current_unit_id, slug_stats
    )
    return Recommendation(
        skill=skill,
        cefr_level=level,
        unit=unit,
        focus=focus,
        reason=reason,
        predicted_success=predicted,
    )


def level_up(
    estimates: dict[str, tuple[rating.Estimate, int]],
    plan_level: str,
    goals: list[str] | None,
) -> str | None:
    """The next CEFR level once the learner is confidently past the plan level, else None.

    ``estimates`` maps a skill to its estimate and evidence count.
    """
    index = rating.CEFR_LEVELS.index(plan_level)
    if index + 1 >= len(rating.CEFR_LEVELS):
        return None
    next_level = rating.CEFR_LEVELS[index + 1]
    threshold = mastery_theta(next_level)
    evidenced = [
        estimate
        for skill, (estimate, n) in estimates.items()
        if skill in goal_skills(goals) and n >= LEVEL_UP_MIN_N
    ]
    if len(evidenced) < LEVEL_UP_MIN_SKILLS:
        return None
    if all(e.mean - LEVEL_UP_Z * e.sd >= threshold for e in evidenced):
        return next_level
    return None
