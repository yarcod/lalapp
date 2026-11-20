"""Pre-generated game stock, refilled slowly in the background by the big model only."""

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import engine
from app.home.context import load_learner
from app.home.speech_session import _gateway
from app.models.game import GameSession, GameStock
from app.models.study_plan import StudyPlan
from app.models.user import User
from app.services.games import GenerationRequest, generate_content, now_utc, source_context
from app.utils.db import db_session

logger = logging.getLogger(__name__)

STOCK_TARGET = 3
DAILY_NEW_GAMES_PER_PLAN = 3
PASS_INTERVAL_SECONDS = 600
GENERATION_TIMEOUT_SECONDS = 600
STATE_POLL_SECONDS = 5
FAILED_BUCKET_COOLDOWN_SECONDS = 3600
MODES = ("review", "prepare", "free")
GAME_TYPES = ("detective", "sentence-order", "vocabulary-pairs")
RECENT_GAMES = 5

# (plan id, mode, game type) -> monotonic time a failed bucket may be tried again. Per process.
bucket_cooldowns: dict[tuple[int, str, str], float] = {}


def _now() -> float:
    return time.monotonic()


async def gateway_state() -> str:
    return (await _gateway("GET", "/session/status")).state


def source_hash(context: dict) -> str:
    ids = sorted(s["source_id"] for s in context.get("sources", []))
    return hashlib.sha256("\n".join(ids).encode()).hexdigest()


class Bucket:
    def __init__(self, plan: StudyPlan, user: User, mode: str, game_type: str, context: dict):
        self.plan, self.user, self.mode, self.game_type = plan, user, mode, game_type
        self.context = context
        self.fresh = 0
        self.unreplaced = 0


async def plan_buckets(db: AsyncSession, plan: StudyPlan, user: User) -> list[Bucket]:
    """Buckets this plan can fill now, after marking progress-stale stock stale."""
    lesson_contexts = {m: await source_context(db, plan, m) for m in ("review", "prepare")}
    buckets = []
    for mode in MODES:
        for game_type in GAME_TYPES:
            if mode == "free":
                context = await source_context(db, plan, mode, game_type)
            else:
                context = lesson_contexts[mode]
                stale = update(GameStock).where(
                    GameStock.study_plan_id == plan.id,
                    GameStock.mode == mode,
                    GameStock.game_type == game_type,
                    GameStock.is_stale.is_(False),
                    GameStock.taken_at.is_(None),
                )
                if context["sources"]:
                    stale = stale.where(GameStock.source_hash != source_hash(context))
                await db.execute(stale.values(is_stale=True))
            if context["sources"]:
                buckets.append(Bucket(plan, user, mode, game_type, context))
    await db.commit()
    for bucket in buckets:
        rows = (
            await db.execute(
                select(GameStock.is_stale, GameStock.taken_at, GameStock.replaced).where(
                    GameStock.study_plan_id == plan.id,
                    GameStock.mode == bucket.mode,
                    GameStock.game_type == bucket.game_type,
                )
            )
        ).all()
        bucket.fresh = sum(1 for stale, taken, _ in rows if not stale and taken is None)
        bucket.unreplaced = sum(1 for stale, _, replaced in rows if stale and not replaced)
        if bucket.fresh >= STOCK_TARGET and bucket.unreplaced:
            # Surplus stale rows must not grant uncapped generations later.
            await db.execute(
                update(GameStock)
                .where(
                    GameStock.study_plan_id == plan.id,
                    GameStock.mode == bucket.mode,
                    GameStock.game_type == bucket.game_type,
                    GameStock.is_stale.is_(True),
                    GameStock.replaced.is_(False),
                )
                .values(replaced=True)
            )
            await db.commit()
            bucket.unreplaced = 0
    return buckets


def bucket_key(bucket: Bucket) -> tuple[int, str, str]:
    return bucket.plan.id, bucket.mode, bucket.game_type


def bucket_cooling(bucket: Bucket) -> bool:
    return _now() < bucket_cooldowns.get(bucket_key(bucket), 0.0)


MADE, SKIPPED, STOP = "made", "skipped", "stop"


async def generate_while_off(request: GenerationRequest, deadline: float):  # noqa: ANN201
    """Generate beside a status poll. Returns None when the gateway leaves `off`, so a child
    opening the app never waits for a game that nobody asked for."""
    task = asyncio.create_task(generate_content(request, deadline))
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=STATE_POLL_SECONDS)
            if not task.done() and await gateway_state() != "off":
                return None
        return task.result()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def generate_item(db: AsyncSession, bucket: Bucket, *, replacement: bool) -> str:
    """Generate one stock item. STOP means the gateway left the full tier."""
    if await gateway_state() != "off":
        return STOP
    plan, user = bucket.plan, bucket.user
    request = GenerationRequest(
        game_type=bucket.game_type,
        mode=bucket.mode,
        target_language=plan.target_language,
        native_language=user.native_language,
        level=plan.cefr_level,
        context=bucket.context,
        is_child=(await load_learner(db, user)).is_child,
    )
    # Never hold a transaction open while waiting for the provider.
    await db.commit()
    try:
        deadline = asyncio.get_running_loop().time() + GENERATION_TIMEOUT_SECONDS
        async with asyncio.timeout_at(deadline):
            content = await generate_while_off(request, deadline)
    except Exception:
        logger.exception("Game stock generation failed: plan %s %s", plan.id, bucket.mode)
        bucket_cooldowns[bucket_key(bucket)] = _now() + FAILED_BUCKET_COOLDOWN_SECONDS
        return SKIPPED
    if content is None:
        return STOP
    db.add(
        GameStock(
            study_plan_id=plan.id,
            mode=bucket.mode,
            game_type=bucket.game_type,
            target_language=request.target_language,
            native_language=request.native_language,
            level=request.level,
            is_child=request.is_child,
            content=[c.model_dump() for c in content.challenges],
            source_hash=source_hash(bucket.context) if bucket.mode != "free" else "",
            created_at=now_utc(),
            counts_toward_cap=not replacement,
        )
    )
    if replacement:
        oldest = await db.scalar(
            select(GameStock)
            .where(
                GameStock.study_plan_id == plan.id,
                GameStock.mode == bucket.mode,
                GameStock.game_type == bucket.game_type,
                GameStock.is_stale.is_(True),
                GameStock.replaced.is_(False),
            )
            .order_by(GameStock.created_at, GameStock.id)
        )
        if oldest is not None:
            oldest.replaced = True
        bucket.unreplaced -= 1
    bucket.fresh += 1
    await db.commit()
    return MADE


async def used_today(db: AsyncSession, plan: StudyPlan) -> int:
    start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    return await db.scalar(
        select(func.count())
        .select_from(GameStock)
        .where(
            GameStock.study_plan_id == plan.id,
            GameStock.counts_toward_cap.is_(True),
            GameStock.created_at >= start,
            GameStock.created_at < start + timedelta(days=1),
        )
    )


async def refill_plan(
    db: AsyncSession, plan: StudyPlan, user: User, first_fill: bool
) -> tuple[int, bool]:
    """Generate for one plan; returns (games made, whether the pass must stop)."""
    buckets = [b for b in await plan_buckets(db, plan, user) if not bucket_cooling(b)]
    made = 0
    for bucket in buckets:
        # Replacing a stale game is not new generation and does not use the daily cap.
        while bucket.unreplaced > 0 and bucket.fresh < STOCK_TARGET:
            result = await generate_item(db, bucket, replacement=True)
            if result == STOP:
                return made, True
            if result == SKIPPED:
                break
            made += 1
    # A first fill is one game per bucket and is not capped; later passes use the daily budget.
    budget = (
        len(buckets)
        if first_fill
        else max(0, DAILY_NEW_GAMES_PER_PLAN - await used_today(db, plan))
    )
    hungry = [b for b in buckets if b.fresh < STOCK_TARGET]
    while budget > 0 and hungry:
        for bucket in list(hungry):
            if budget == 0:
                break
            result = await generate_item(db, bucket, replacement=False)
            if result == STOP:
                return made, True
            if result == SKIPPED:
                hungry.remove(bucket)
                continue
            made += 1
            budget -= 1
            if first_fill or bucket.fresh >= STOCK_TARGET:
                hungry.remove(bucket)
    return made, False


async def refill_once(db: AsyncSession) -> int:
    """One pass: only on the full card with no speech session. Returns games generated."""
    if await gateway_state() != "off":
        return 0
    rows = (
        await db.execute(
            select(StudyPlan, User)
            .join(User, User.id == StudyPlan.user_id)
            .where(StudyPlan.is_active.is_(True), User.is_active.is_(True))
            .order_by(StudyPlan.id)
        )
    ).all()
    planned = []
    for plan, user in rows:
        existing = await db.scalar(
            select(func.count()).select_from(GameStock).where(GameStock.study_plan_id == plan.id)
        )
        planned.append((existing > 0, plan, user))
    planned.sort(key=lambda item: item[0])  # plans with nothing generated yet go first
    total = 0
    for has_stock, plan, user in planned:
        made, stop = await refill_plan(db, plan, user, first_fill=not has_stock)
        total += made
        if stop:
            break
    return total


def recent_sentences_query(plan: StudyPlan):  # noqa: ANN201
    return (
        select(GameSession)
        .where(
            GameSession.study_plan_id == plan.id,
            GameSession.status.in_(["completed", "abandoned"]),
        )
        .order_by(GameSession.created_at.desc(), GameSession.id)
        .limit(RECENT_GAMES)
    )


async def claim_item(db: AsyncSession, item: GameStock) -> bool:
    """Atomic take: only one caller can flip taken_at from NULL, on SQLite and Postgres alike."""
    result = await db.execute(
        update(GameStock)
        .where(
            GameStock.id == item.id,
            GameStock.taken_at.is_(None),
            GameStock.is_stale.is_(False),
        )
        .values(taken_at=now_utc())
    )
    return result.rowcount == 1


async def take_from_stock(
    db: AsyncSession, plan: StudyPlan, mode: str, game_type: str
) -> GameStock | None:
    """Oldest fresh item not repeating recent sentences; repeated items are marked stale.

    The caller commits, so the claim and the session built from it are one transaction."""
    recent: set[str] = set()
    for session in (await db.scalars(recent_sentences_query(plan))).all():
        recent.update(c["sentence"] for c in session.challenges)
    candidates: Sequence[GameStock] = (
        await db.scalars(
            select(GameStock)
            .where(
                GameStock.study_plan_id == plan.id,
                GameStock.mode == mode,
                GameStock.game_type == game_type,
                GameStock.is_stale.is_(False),
                GameStock.taken_at.is_(None),
            )
            .order_by(GameStock.created_at, GameStock.id)
        )
    ).all()
    for item in candidates:
        if any(c["sentence"] in recent for c in item.content):
            await db.execute(update(GameStock).where(GameStock.id == item.id).values(is_stale=True))
            continue
        if await claim_item(db, item):
            await db.refresh(item)
            return item
    await db.flush()
    return None


ADVISORY_LOCK_KEY = 0x46_4C_47_53  # "FLGS": one refill pass at a time across workers


@asynccontextmanager
async def pass_lock() -> AsyncIterator[bool]:
    """Session-level Postgres advisory lock on a dedicated autocommit connection."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        got = await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
        try:
            yield bool(got)
        finally:
            if got:
                await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})


async def run_pass() -> int:
    async with pass_lock() as acquired:
        if not acquired:
            return 0
        async with db_session() as db:
            return await refill_once(db)


async def stock_loop() -> None:
    """Background refill; one failed pass never stops the loop."""
    while True:
        try:
            made = await run_pass()
            if made:
                logger.info("Game stock refill generated %s games", made)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Game stock refill pass failed")
        await asyncio.sleep(PASS_INTERVAL_SECONDS)


def stock_enabled() -> bool:
    return settings.LLM_PROVIDER == "ollama"
