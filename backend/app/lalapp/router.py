from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_active_study_plan, get_active_study_plan_optional, get_current_user
from app.core.limiter import limiter
from app.lalapp.adaptive import service as adaptive
from app.lalapp.config import lalapp_settings
from app.lalapp.learner.rating import cefr_from_theta
from app.lalapp.models import LearnerSkill, PlacementSession, ScenarioRun
from app.lalapp.personas import registry as persona_registry
from app.lalapp.personas import service as persona_service
from app.lalapp.personas.types import Persona
from app.lalapp.placement import engine
from app.lalapp.placement import service as placement
from app.lalapp.rhythm import service as rhythm
from app.lalapp.scenarios import service as scenarios
from app.lalapp.scenarios.types import Scenario
from app.models.conversation import Conversation
from app.models.study_plan import StudyPlan
from app.models.user import User
from app.models.user_language import UserLanguage
from app.schemas.auth import SUPPORTED_TARGET_LANGUAGES
from app.services.user_language_service import get_active_language

router = APIRouter(prefix="/api/lalapp", tags=["lalapp"])


class LearnerSkillOut(BaseModel):
    skill: str
    theta: float
    theta_sd: float
    cefr: str
    n: int


class LearnerLanguageOut(BaseModel):
    target_language: str
    skills: list[LearnerSkillOut]


@router.get("/learner", response_model=list[LearnerLanguageOut])
@limiter.limit("30/minute")
async def get_learner_model(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LearnerLanguageOut]:
    """The current user's per-language skill estimates (shadow mode, read-only)."""
    rows = (
        await db.execute(
            select(UserLanguage.target_language, LearnerSkill)
            .join(LearnerSkill, LearnerSkill.user_language_id == UserLanguage.id)
            .where(UserLanguage.user_id == current_user.id)
            .order_by(UserLanguage.target_language, LearnerSkill.skill)
        )
    ).all()
    languages: dict[str, list[LearnerSkillOut]] = {}
    for target_language, skill in rows:
        languages.setdefault(target_language, []).append(
            LearnerSkillOut(
                skill=skill.skill,
                theta=round(skill.theta, 3),
                theta_sd=round(skill.theta_sd, 3),
                cefr=cefr_from_theta(skill.theta),
                n=skill.n,
            )
        )
    return [LearnerLanguageOut(target_language=k, skills=v) for k, v in languages.items()]


class PlacementStartRequest(BaseModel):
    language: str = Field(max_length=10)
    self_level: str | None = Field(default=None, max_length=2)


class PlacementAnswerRequest(BaseModel):
    question_id: str = Field(max_length=50)
    answer: str = Field(max_length=500)


class PlacementQuestion(BaseModel):
    id: str
    skill: str
    difficulty: str
    question: str
    options: list[str]


class PlacementStep(BaseModel):
    session_id: str
    question_number: int
    max_questions: int
    question: PlacementQuestion | None
    result: dict | None


def _step(session: PlacementSession) -> PlacementStep:
    question = None
    if session.pending_item_id:
        item = placement._bank(session.target_language)[session.pending_item_id]
        # The correct option never leaves the server.
        question = PlacementQuestion(
            id=item.id,
            skill=item.skill,
            difficulty=item.difficulty,
            question=item.question,
            options=list(item.options),
        )
    return PlacementStep(
        session_id=session.id,
        question_number=len(session.state["asked"]) + (1 if question else 0),
        max_questions=engine.MAX_QUESTIONS,
        question=question,
        result=session.result,
    )


@router.post("/placement/start", response_model=PlacementStep)
@limiter.limit("10/minute")
async def start_placement(
    request: Request,
    data: PlacementStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlacementStep:
    if data.language not in SUPPORTED_TARGET_LANGUAGES:
        raise HTTPException(status_code=422, detail="unsupported_language")
    session = await placement.start(db, current_user.id, data.language, data.self_level)
    return _step(session)


@router.post("/placement/{session_id}/answer", response_model=PlacementStep)
@limiter.limit("60/minute")
async def answer_placement(
    request: Request,
    session_id: str,
    data: PlacementAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlacementStep:
    session = await placement.answer(db, current_user.id, session_id, data.question_id, data.answer)
    return _step(session)


class PersonaOut(BaseModel):
    id: str
    name: str
    role: str
    dialect: str
    age: int
    backstory: str
    personality: list[str]


class PersonaCastOut(BaseModel):
    target_language: str
    preferred_peer_id: str | None
    personas: list[PersonaOut]


class PersonaChoice(BaseModel):
    persona_id: str = Field(max_length=50)


def _persona_out(persona: Persona) -> PersonaOut:
    return PersonaOut(
        id=persona.id,
        name=persona.name,
        role=persona.role,
        dialect=persona.dialect,
        age=persona.age,
        backstory=persona.backstory,
        personality=list(persona.personality),
    )


async def _active_target_language(db: AsyncSession, user: User) -> str:
    active = await get_active_language(db, user.id)
    if active is None:
        raise HTTPException(status_code=404, detail="no_active_language")
    return active.target_language


@router.get("/personas", response_model=PersonaCastOut)
@limiter.limit("60/minute")
async def list_personas(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaCastOut:
    """Characters available for the active language, and the chosen conversation partner."""
    target_language = await _active_target_language(db, current_user)
    peer = await persona_service.preferred_peer(db, current_user.id, target_language)
    return PersonaCastOut(
        target_language=target_language,
        preferred_peer_id=peer.id if peer else None,
        personas=[_persona_out(p) for p in persona_registry.selectable_for(target_language)],
    )


@router.put("/personas/peer", response_model=PersonaCastOut)
@limiter.limit("20/minute")
async def choose_peer(
    request: Request,
    data: PersonaChoice,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaCastOut:
    target_language = await _active_target_language(db, current_user)
    if not await persona_service.set_preferred_peer(
        db, current_user.id, target_language, data.persona_id
    ):
        raise HTTPException(status_code=422, detail="invalid_persona")
    return await list_personas(request, current_user, db)


@router.get("/conversations/{conversation_id}/persona", response_model=PersonaOut)
@limiter.limit("60/minute")
async def get_conversation_persona(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    persona = await persona_service.conversation_persona(
        db, current_user.id, conversation_id, conversation.target_language or ""
    )
    if persona is None:
        raise HTTPException(status_code=404, detail="no_persona")
    return _persona_out(persona)


@router.put("/conversations/{conversation_id}/persona", response_model=PersonaOut)
@limiter.limit("20/minute")
async def set_conversation_persona(
    request: Request,
    conversation_id: int,
    data: PersonaChoice,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    persona = await persona_service.set_conversation_persona(
        db, current_user.id, conversation_id, data.persona_id
    )
    if persona is None:
        raise HTTPException(status_code=404, detail="persona_or_conversation_not_found")
    return _persona_out(persona)


class NextLessonOut(BaseModel):
    id: int
    title: str
    lesson_type: str
    cefr_level: str
    reason: str
    focus: list[str]
    predicted_success: float


class LevelUpOut(BaseModel):
    next_level: str
    goals: list[str]
    duration_weeks: int
    days_per_week: int
    target_language: str


class NextUpOut(BaseModel):
    plan_id: int
    skill: str
    cefr_level: str
    reason: str
    focus: list[str]
    unit_title: str | None
    predicted_success: float
    lesson: NextLessonOut | None
    level_up: LevelUpOut | None


def _require_adaptive() -> None:
    if not lalapp_settings.ADAPTIVE_ENABLED:
        raise HTTPException(status_code=404, detail="adaptive_disabled")


async def _next_up(db: AsyncSession, plan: StudyPlan) -> NextUpOut:
    recommendation = await adaptive.recommend(db, plan)
    existing = await adaptive.open_lesson(db, plan.id)
    next_level = await adaptive.level_up(db, plan)
    lesson = None
    if existing:
        row, meta = existing
        lesson = NextLessonOut(
            id=row.id,
            title=row.title,
            lesson_type=row.lesson_type,
            cefr_level=row.cefr_level,
            reason=meta.reason,
            focus=list(meta.focus or []),
            predicted_success=meta.predicted_success,
        )
    return NextUpOut(
        plan_id=plan.id,
        skill=recommendation.skill,
        cefr_level=recommendation.cefr_level,
        reason=recommendation.reason,
        focus=list(recommendation.focus),
        unit_title=recommendation.unit.title if recommendation.unit else None,
        predicted_success=round(recommendation.predicted_success, 3),
        lesson=lesson,
        level_up=(
            LevelUpOut(
                next_level=next_level,
                goals=list(plan.goals or []),
                duration_weeks=plan.duration_weeks,
                days_per_week=plan.days_per_week,
                target_language=plan.target_language,
            )
            if next_level
            else None
        ),
    )


@router.get("/next", response_model=NextUpOut | None)
@limiter.limit("60/minute")
async def get_next_up(
    request: Request,
    plan: StudyPlan | None = Depends(get_active_study_plan_optional),
    db: AsyncSession = Depends(get_db),
) -> NextUpOut | None:
    """What the learner model suggests next for the active plan; generates nothing."""
    _require_adaptive()
    if plan is None:
        return None
    return await _next_up(db, plan)


@router.post("/next", response_model=NextUpOut)
@limiter.limit("10/minute")
async def create_next_lesson(
    request: Request,
    current_user: User = Depends(get_current_user),
    plan: StudyPlan = Depends(get_active_study_plan),
    db: AsyncSession = Depends(get_db),
) -> NextUpOut:
    """Generate the suggested lesson, or keep the one already waiting."""
    _require_adaptive()
    plan_id = plan.id
    try:
        await adaptive.create_lesson(db, plan, native_language=current_user.native_language)
    except Exception as exc:
        await db.rollback()
        adaptive.logger.exception("Adaptive lesson generation failed for plan %s", plan_id)
        raise HTTPException(status_code=503, detail="lesson_generation_failed") from exc
    plan = await db.get(StudyPlan, plan_id)
    return await _next_up(db, plan)


class MissionOut(BaseModel):
    id: str
    goal: dict[str, str]
    done: bool
    evidence: str | None


class ScenarioOut(BaseModel):
    id: str
    title: str
    summary: dict[str, str]
    level: str
    arc: str
    order: int
    npc: PersonaOut
    status: str
    conversation_id: int | None
    missions: list[MissionOut]


class ScenarioListOut(BaseModel):
    target_language: str
    plan_level: str | None
    scenarios: list[ScenarioOut]


class ScenarioRunOut(BaseModel):
    conversation_id: int
    newly_done: list[str]
    scenario: ScenarioOut


def _require_scenarios() -> None:
    if not lalapp_settings.SCENARIOS_ENABLED:
        raise HTTPException(status_code=404, detail="scenarios_disabled")


def _scenario_out(
    scenario: Scenario, status: str, conversation_id: int | None, evidence: dict[str, str]
) -> ScenarioOut:
    return ScenarioOut(
        id=scenario.id,
        title=scenario.title,
        summary=scenario.summary,
        level=scenario.level,
        arc=scenario.arc,
        order=scenario.order,
        npc=_persona_out(scenario.npc),
        status=status,
        conversation_id=conversation_id,
        missions=[
            MissionOut(id=m.id, goal=m.goal, done=m.id in evidence, evidence=evidence.get(m.id))
            for m in scenario.missions
        ],
    )


@router.get("/scenarios", response_model=ScenarioListOut)
@limiter.limit("60/minute")
async def list_scenarios(
    request: Request,
    current_user: User = Depends(get_current_user),
    plan: StudyPlan | None = Depends(get_active_study_plan_optional),
    db: AsyncSession = Depends(get_db),
) -> ScenarioListOut:
    """Role-play scenes for the active language, with lock state and mission progress."""
    _require_scenarios()
    user_language = await get_active_language(db, current_user.id)
    if user_language is None:
        raise HTTPException(status_code=404, detail="no_active_language")
    states = await scenarios.scene_states(db, user_language)
    return ScenarioListOut(
        target_language=user_language.target_language,
        plan_level=plan.cefr_level if plan else None,
        scenarios=[
            _scenario_out(
                state.scenario,
                state.status,
                state.conversation_id if state.status != "locked" else None,
                {m: "" for m in state.missions_done},
            )
            for state in states
        ],
    )


async def _owned_run(
    db: AsyncSession, user: User, conversation_id: int
) -> tuple[ScenarioRun, Scenario]:
    conversation = await db.get(Conversation, conversation_id)
    run = await scenarios.run_for_conversation(db, conversation_id)
    scenario = scenarios.get(run.scenario_id) if run else None
    if conversation is None or conversation.user_id != user.id or scenario is None:
        raise HTTPException(status_code=404, detail="not_a_scenario_conversation")
    return run, scenario


def _run_out(run: ScenarioRun, scenario: Scenario, newly_done: list[str]) -> ScenarioRunOut:
    return ScenarioRunOut(
        conversation_id=run.conversation_id,
        newly_done=newly_done,
        scenario=_scenario_out(scenario, run.status, run.conversation_id, dict(run.missions or {})),
    )


@router.post("/scenarios/{scenario_id}/start", response_model=ScenarioRunOut)
@limiter.limit("10/minute")
async def start_scenario(
    request: Request,
    scenario_id: str,
    current_user: User = Depends(get_current_user),
    plan: StudyPlan | None = Depends(get_active_study_plan_optional),
    db: AsyncSession = Depends(get_db),
) -> ScenarioRunOut:
    """Open a new conversation for the scene, starting with the NPC's first line."""
    _require_scenarios()
    user_language = await get_active_language(db, current_user.id)
    scenario = scenarios.get(scenario_id)
    if (
        user_language is None
        or scenario is None
        or scenario not in scenarios.scenarios_for(user_language.target_language)
    ):
        raise HTTPException(status_code=404, detail="scenario_not_found")
    try:
        run = await scenarios.start(
            db,
            user_id=current_user.id,
            user_language=user_language,
            scenario=scenario,
            study_plan_id=plan.id if plan else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="scenario_locked") from exc
    return _run_out(run, scenario, [])


@router.get("/scenarios/runs/{conversation_id}", response_model=ScenarioRunOut)
@limiter.limit("60/minute")
async def get_scenario_run(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioRunOut:
    _require_scenarios()
    run, scenario = await _owned_run(db, current_user, conversation_id)
    return _run_out(run, scenario, [])


@router.post("/scenarios/runs/{conversation_id}/check", response_model=ScenarioRunOut)
@limiter.limit("30/minute")
async def check_scenario_run(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioRunOut:
    """Judge the learner's messages since the last check against the open missions."""
    _require_scenarios()
    run, scenario = await _owned_run(db, current_user, conversation_id)
    try:
        newly_done = await scenarios.check_missions(db, run, current_user.id)
    except Exception as exc:
        await db.rollback()
        scenarios.logger.exception("Mission check failed for conversation %s", conversation_id)
        raise HTTPException(status_code=503, detail="mission_check_failed") from exc
    return _run_out(run, scenario, newly_done)


class MilestoneOut(BaseModel):
    id: int
    key: str
    data: dict
    created_at: datetime


class RhythmOut(BaseModel):
    target_language: str
    days_per_week: int
    week_start: date
    active_days: list[date]
    weeks_kept: int
    weeks_counted: int
    turns_this_week: int
    stretch_turns_this_week: int
    milestones: list[MilestoneOut]


class RhythmGoalIn(BaseModel):
    days_per_week: int = Field(ge=1, le=7)


def _require_rhythm() -> None:
    if not lalapp_settings.RHYTHM_ENABLED:
        raise HTTPException(status_code=404, detail="rhythm_disabled")


async def _active_user_language(db: AsyncSession, user: User) -> UserLanguage:
    user_language = await get_active_language(db, user.id)
    if user_language is None:
        raise HTTPException(status_code=404, detail="no_active_language")
    return user_language


@router.get("/rhythm", response_model=RhythmOut)
@limiter.limit("60/minute")
async def get_rhythm(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RhythmOut:
    """This week against the learner's own goal, recent weeks kept, turns, and new milestones."""
    _require_rhythm()
    user_language = await _active_user_language(db, current_user)
    state = await rhythm.summary(db, user_language)
    return RhythmOut(
        target_language=user_language.target_language,
        days_per_week=state.days_per_week,
        week_start=state.week_start,
        active_days=state.active_days,
        weeks_kept=state.weeks_kept,
        weeks_counted=state.weeks_counted,
        turns_this_week=state.turns_this_week,
        stretch_turns_this_week=state.stretch_turns_this_week,
        milestones=[
            MilestoneOut(id=m.id, key=m.key, data=m.data or {}, created_at=m.created_at)
            for m in state.milestones
        ],
    )


@router.put("/rhythm", response_model=RhythmOut)
@limiter.limit("20/minute")
async def set_rhythm_goal(
    request: Request,
    data: RhythmGoalIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RhythmOut:
    _require_rhythm()
    user_language = await _active_user_language(db, current_user)
    await rhythm.set_goal(db, user_language.id, data.days_per_week)
    return await get_rhythm(request, current_user, db)


@router.post("/milestones/{milestone_id}/seen", status_code=204)
@limiter.limit("60/minute")
async def mark_milestone_seen(
    request: Request,
    milestone_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _require_rhythm()
    user_language = await _active_user_language(db, current_user)
    if not await rhythm.mark_seen(db, user_language.id, milestone_id):
        raise HTTPException(status_code=404, detail="milestone_not_found")
