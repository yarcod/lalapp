"""Home games: stock serving, replay and lenient draft generation for the stock worker.

Upstream `app.services.games` imports this module, so its helpers are imported inside the
functions that need them; importing either module first then works.
"""

import random
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from random import SystemRandom
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.home.game_prompts import (
    detective_prompt,
    detective_review_spec,
    sentence_order_prompt,
    vocabulary_pairs_prompt,
)
from app.home.game_schemas import (
    DetectiveDraft,
    DetectiveDraftContent,
    SentenceOrderDraftContent,
    VocabularyPairsDraftContent,
)
from app.models.game import GameAdmission, GameRequest, GameSession
from app.models.study_plan import StudyPlan
from app.models.user import User
from app.schemas.games import (
    DetectiveChallenge,
    DetectiveContent,
    DetectiveReview,
    GameCreate,
    SentenceOrderChallenge,
    SentenceOrderContent,
    VocabularyPair,
    VocabularyPairsContent,
)
from app.services.llm_adapter import LLMResponseError, llm_adapter
from app.services.prompts.games import (
    detective_review_prompt,
    sentence_order_review_prompt,
    vocabulary_pairs_review_prompt,
)


def stock_mode() -> bool:
    """Games come only from the pre-generated stock when the local model serves them."""
    from app.home import game_stock

    return game_stock.stock_enabled()


async def start_from_stock(
    db: AsyncSession,
    user: User,
    plan: StudyPlan,
    body: GameCreate,
    game_type: str,
    request: GameRequest,
    limited: bool,
    now: datetime,
) -> GameSession | None:
    """Start a ready game from stock; None means the stock is empty."""
    from app.home import game_stock

    item = await game_stock.take_from_stock(db, plan, body.mode, game_type)
    if item is None:
        await db.commit()
        return None
    session = GameSession(
        id=str(body.request_id),
        user_id=user.id,
        study_plan_id=plan.id,
        mode=body.mode,
        game_type=game_type,
        target_language=item.target_language,
        native_language=item.native_language,
        level=item.level,
        status="ready",
        context={"sources": [], "stock_id": item.id},
        created_at=now,
        deadline=now,
        challenges=finalize_challenges(game_type, item.content),
        answers=[{} for _ in item.content],
        xp_earned=0,
    )
    db.add(session)
    try:
        await db.flush()
    except IntegrityError:
        # Another request won the single active slot: undo the claim and resume its game.
        await db.rollback()
        active = await db.scalar(
            select(GameSession).where(
                GameSession.study_plan_id == body.study_plan_id,
                GameSession.game_type == game_type,
                GameSession.status.in_(["generating", "ready"]),
            )
        )
        if active is None:
            raise
        return active
    request.session_id = session.id
    db.add(request)
    if limited:
        db.add(
            GameAdmission(
                id=session.id,
                user_id=user.id,
                date=now.date(),
                status="consumed",
                deadline=now,
            )
        )
    await db.commit()
    return session


async def stock_empty_response(db: AsyncSession, plan: StudyPlan, game_type: str) -> JSONResponse:
    """The stock-empty note as a 200 response, for the upstream start route (which uses 202)."""
    return JSONResponse(await stock_empty_output(db, plan, game_type))


GAMES_REQUESTED = 8
GAMES_NEEDED = 5


def build_challenge(draft: DetectiveDraft) -> DetectiveChallenge:
    """Split the sentence around wrong_part and shuffle the options; raises ValueError if unusable."""
    sentence, wrong = draft.sentence, draft.wrong_part
    # Spaced scripts must match whole words; unspaced text (CJK) has no word boundaries to use.
    bounded = any(ch.isspace() for ch in sentence)
    pattern = re.escape(wrong)
    if bounded:
        pattern = rf"(?<!\w){pattern}(?!\w)"
    starts = [m.start() for m in re.finditer(f"(?={pattern})", sentence)]
    if len(starts) != 1:
        raise ValueError("wrong_part must occur exactly once in the sentence")
    if draft.correct_part == wrong:
        raise ValueError("correct_part must differ from wrong_part")
    start = starts[0]
    before, after = sentence[:start], sentence[start + len(wrong) :]
    fragments = [
        *re.findall(r"\s*\S+\s*", before),
        wrong,
        *re.findall(r"\s*\S+\s*", after),
    ]
    if "".join(fragments) != sentence:
        raise ValueError("Sentence cannot be split into fragments")
    options = [draft.correct_part, *draft.wrong_options]
    random.shuffle(options)
    error_index = len(re.findall(r"\s*\S+\s*", before))
    correct_index = options.index(draft.correct_part)
    return DetectiveChallenge(
        sentence=sentence,
        fragments=fragments,
        error_index=error_index,
        options=options,
        correct_index=correct_index,
        corrected_sentence=sentence[:start] + draft.correct_part + after,
        explanation=draft.explanation,
        source_id=draft.source_id,
    )


def _build_detective(item: object) -> DetectiveChallenge:
    draft = item if isinstance(item, DetectiveDraft) else DetectiveDraft.model_validate(item)
    return build_challenge(draft)


def _norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def salvage_challenges(
    drafts: list,
    needed: int = GAMES_NEEDED,
    *,
    build: Callable[[object], object] = _build_detective,
    keys: Callable[[object], tuple[str, ...]] = lambda c: (_norm(c.sentence),),
    accept: Callable[[object], bool] = lambda c: True,
) -> list:
    """Keep the first `needed` valid, distinct items; invalid ones are dropped, not fatal."""
    kept: list = []
    seen: list[set[str]] = []
    for item in drafts:
        try:
            challenge = build(item)
        except ValueError, ValidationError, TypeError:
            continue
        if not accept(challenge):
            continue
        item_keys = keys(challenge)
        if len(seen) < len(item_keys):
            seen.extend(set() for _ in range(len(item_keys) - len(seen)))
        if any(not key or key in seen[i] for i, key in enumerate(item_keys)):
            continue
        for i, key in enumerate(item_keys):
            seen[i].add(key)
        kept.append(challenge)
        if len(kept) == needed:
            return kept
    raise LLMResponseError(f"Only {len(kept)} of {needed} required challenges were valid")


@dataclass
class GenerationRequest:
    """The fields content generation reads; lets stock build games without a GameSession."""

    game_type: str
    mode: str
    target_language: str
    native_language: str
    level: str
    context: dict


async def generate_content(
    session: GameSession | GenerationRequest, deadline: float
) -> DetectiveContent | SentenceOrderContent | VocabularyPairsContent:
    """Ask for more challenges than needed and keep the first valid ones."""
    from app.services.games import shuffled_order_challenge

    ordering = session.game_type == "sentence-order"
    prompt_builder = sentence_order_prompt if ordering else detective_prompt
    review_builder = sentence_order_review_prompt if ordering else detective_review_prompt
    schema = SentenceOrderContent if ordering else DetectiveContent
    draft_schema = SentenceOrderDraftContent if ordering else DetectiveDraftContent
    build = SentenceOrderChallenge.model_validate if ordering else _build_detective
    keys = lambda c: (_norm(c.sentence),)  # noqa: E731
    if session.game_type == "vocabulary-pairs":
        prompt_builder = vocabulary_pairs_prompt
        review_builder = vocabulary_pairs_review_prompt
        schema = VocabularyPairsContent
        draft_schema = VocabularyPairsDraftContent
        build = VocabularyPair.model_validate
        keys = lambda c: (_norm(c.term), _norm(c.meaning))  # noqa: E731
    prompt_args = (
        session.target_language,
        session.native_language,
        session.level,
        session.mode,
        session.context,
    )
    prompt = prompt_builder(*prompt_args)
    # The reviewer audits the five kept items in their final format.
    if prompt_builder is detective_prompt:
        review_spec = detective_review_spec(*prompt_args)
    else:
        review_spec = prompt_builder(*prompt_args, count="five")
    permitted = {s["source_id"] for s in session.context["sources"]}
    recent = session.context.get("recent_sentences", [])
    rejection = ""
    for _ in range(2):
        draft = await llm_adapter.structured_output(
            [{"role": "system", "content": prompt + rejection}], draft_schema, deadline=deadline
        )
        try:
            challenges = salvage_challenges(
                draft.challenges,
                GAMES_NEEDED,
                build=build,
                keys=keys,
                accept=lambda c: c.source_id in permitted and c.sentence not in recent,
            )
        except LLMResponseError:
            rejection = (
                "\nPrevious candidate rejected: too few valid challenges. Follow the format, "
                "use only supplied source IDs and do not repeat recent sentences."
            )
            continue
        content = schema(challenges=challenges)
        review = await llm_adapter.structured_output(
            [{"role": "system", "content": review_builder(review_spec, content.model_dump())}],
            DetectiveReview,
            deadline=deadline,
        )
        if review.valid:
            if ordering:
                return SentenceOrderContent(
                    challenges=[shuffled_order_challenge(c) for c in content.challenges]
                )
            return content
        rejection = "\nPrevious candidate rejected; create a new one. Audit: " + review.reason
    raise LLMResponseError("Game content did not pass review")


def finalize_challenges(game_type: str, challenges: list[dict]) -> list[dict]:
    """Per-play shuffles applied to raw generated content, for stock, generation and replay."""
    if game_type == "vocabulary-pairs":
        items = [{k: v for k, v in c.items() if k != "choice_index"} for c in challenges]
        SystemRandom().shuffle(items)
        choices = SystemRandom().sample(range(len(items)), len(items))
        return [{**c, "choice_index": choices[i]} for i, c in enumerate(items)]
    return [dict(c) for c in challenges]


def reshuffled(game_type: str, challenge: dict) -> dict:
    """Reshuffle what the game shuffles within a challenge, so a replay is not the same puzzle."""
    from app.services.games import shuffled_order_challenge

    if game_type == "sentence-order":
        return shuffled_order_challenge(
            SentenceOrderChallenge.model_validate(challenge)
        ).model_dump()
    if game_type == "detective":
        options = list(challenge["options"])
        correct = options[challenge["correct_index"]]
        SystemRandom().shuffle(options)
        return {**challenge, "options": options, "correct_index": options.index(correct)}
    return challenge


def answer_score(session: GameSession) -> int:
    """Challenges played without a mistake."""
    score = 0
    for challenge, answer in zip(session.challenges, session.answers, strict=False):
        if session.game_type == "vocabulary-pairs":
            score += bool(answer.get("matched")) and not answer.get("assisted", False)
        elif session.game_type == "sentence-order":
            score += bool(answer.get("correct"))
        else:
            score += (
                answer.get("detection") == challenge["error_index"]
                and answer.get("correction") == challenge["correct_index"]
            )
    return score


async def stock_empty_output(db: AsyncSession, plan: StudyPlan, game_type: str) -> dict:
    """The happy note: what a learner can replay, and whether this is their very first games."""
    finished = (
        await db.scalars(
            select(GameSession)
            .where(
                GameSession.study_plan_id == plan.id,
                GameSession.game_type == game_type,
                GameSession.status == "completed",
            )
            .order_by(GameSession.completed_at.desc(), GameSession.created_at.desc())
        )
    ).all()
    return {
        "status": "empty",
        "first_games_pending": not finished,
        "replayable": [
            {
                "id": s.id,
                "mode": s.mode,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "score": answer_score(s),
                "total": len(s.challenges),
                "xp_earned": s.xp_earned,
            }
            for s in finished[:5]
        ],
    }


async def replay_game(db: AsyncSession, user: User, session_id: str) -> GameSession:
    """A new ready session from a finished game's content, with fresh answers."""
    from app.services.games import lock_user, now_utc, owned_game

    source = await owned_game(db, user.id, session_id)
    await lock_user(db, user.id)
    if source.status != "completed":
        raise HTTPException(409, "game_not_completed")
    active = await db.scalar(
        select(GameSession).where(
            GameSession.study_plan_id == source.study_plan_id,
            GameSession.game_type == source.game_type,
            GameSession.status.in_(["generating", "ready"]),
        )
    )
    if active is not None:
        await db.commit()
        return active
    now = now_utc()
    challenges = finalize_challenges(
        source.game_type, [reshuffled(source.game_type, c) for c in source.challenges]
    )
    session = GameSession(
        id=str(uuid4()),
        user_id=user.id,
        study_plan_id=source.study_plan_id,
        mode=source.mode,
        game_type=source.game_type,
        target_language=source.target_language,
        native_language=source.native_language,
        level=source.level,
        status="ready",
        context={"sources": [], "replay_of": source.id},
        created_at=now,
        deadline=now,
        challenges=challenges,
        answers=[{} for _ in challenges],
        xp_earned=0,
    )
    db.add(session)
    await db.commit()
    return session
