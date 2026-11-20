# Fork Surface Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the home fork's behaviour out of upstream FreeLingo files into home-owned paths, leaving upstream files with short, named hook lines, and move home database objects into a separate Alembic history.

**Architecture:** A backend package `app/home/` installed by one call in `main.py`, with its own tables (`home_profiles`, `home_game_stock`) migrated from `backend/alembic_home/` into version table `alembic_version_home`. The current learner's home profile is held in a context variable set where the user is resolved. A frontend `src/home/` tree holds hooks and components rendered from short call sites, and `messages/home/` is merged over upstream messages.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy async, Alembic, pytest; Next.js 16, React, next-intl, Zustand, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-20-fork-surface-design.md`

## Global Constraints

- Work on a new branch `feature/home-surface` created from `feature/home-deployment`. Do not merge `upstream/main` in this plan.
- "Return F to upstream" always means `git checkout main -- F`, then re-add only the hook lines the task names. `main` is the upstream base of this branch.
- Behaviour stays identical except two deliberate changes: a replay uses the profile's current child setting, and the child checkbox saves on click.
- No new dependencies. No Markdown tables in docs.
- Run commands through `./scripts/local.sh {backend|frontend} …`. Standing approval covers targeted pytest, Vitest, ESLint, `tsc` and Ruff runs for this plan. On any failure, stop and report to the owner before changing code or tests. Ask before the full pre-push suite.
- Python follows Ruff `E, W, F, I, UP, B, S, ANN` (tests exempt from `S` and `ANN`), Black line length 100. TypeScript: no semicolons, single quotes, two spaces, ES5 trailing commas.
- Every hook line in an upstream file calls a function or renders a component whose module path starts with `app.home` or `@/home`.
- Moving tests: assertions move unchanged unless the task names a change. A moved test that fails is a failure to report, not to edit.
- Do not apply migrations to any real database. The deployed database is wiped by the maintainer before the first deploy (documented in Task 12).

## Review Focus

- A user with no `home_profiles` row (every existing and newly registered account): must behave as not a child, with no errors. Test in Task 2.
- A request that resolves no user (anonymous endpoints, websockets, background stock jobs): the context variable must read as the default learner, not leak a previous request's learner. Test in Task 2 and Task 4.
- A locale with no `messages/home/<locale>.json` file, or a key missing from it: falls back to the English home string, never a raw key. Test in Task 8.
- Startup against a fresh database: upstream migrations run first, then home migrations, and the home history never writes to `alembic_version`. Test in Task 2.
- Toggling the child checkbox when the request fails: the checkbox returns to its saved value and shows the existing error style. Test in Task 9.

---

### Task 1: Footprint script and home package skeleton

**Files:**
- Create: `scripts/home-surface.sh`
- Create: `backend/app/home/__init__.py`, `backend/app/home/install.py`, `backend/app/home/settings.py`
- Move: `backend/app/routers/speech_session.py` → `backend/app/home/speech_session.py`
- Move: `backend/tests/test_speech_session.py` → `backend/tests/home/test_speech_session.py` (+ `backend/tests/home/__init__.py`)
- Modify: `backend/app/main.py` (stock task and `speech_session` include leave; one `install_home(app)` call), `backend/app/core/config.py` (return to upstream), `backend/app/services/game_stock.py` and `backend/app/routers/conversation.py` (import path only)

**Interfaces:**
- Produces: `install_home(app: FastAPI) -> None` in `app.home.install`. Includes home routers and replaces `app.router.lifespan_context` with a wrapper that enters the original lifespan first and, in later tasks, runs home migrations and the stock loop.
- Produces: `home_settings: HomeSettings` in `app.home.settings`; `HomeSettings(BaseSettings)` with `VOICE_REASONING_EFFORT: str = "low"`, read from the same environment as upstream settings.
- Produces: `app.home.speech_session` with the same public names as today (`router`, `live_llm_is_small`, `_gateway`, `SpeechSessionState`).

- [ ] **Step 1: Write `scripts/home-surface.sh`.** It prints `git diff --numstat $(git merge-base HEAD upstream/main)..HEAD` restricted to modified upstream files, excluding these home-owned paths: `backend/app/home/`, `backend/alembic_home/`, `backend/alembic_home.ini`, `backend/tests/home/`, `frontend/src/home/`, `frontend/tests/home/`, `messages/home/`, `services/speech-gateway/`, `docs/superpowers/`, `specs/home-deployment.instructions.md`, `CLAUDE.md`, `scripts/home-surface.sh`. Last line: `N upstream files, +A -D lines`. It fails with a clear message if the `upstream` remote is missing.
- [ ] **Step 2: Record the baseline.** Run `./scripts/home-surface.sh | tail -1`. Expected: about 80 upstream files. Paste the line into the Task 1 commit message.
- [ ] **Step 3: Move the speech-session router and its test.** Use `git mv`, then fix imports. Add `tests/home/test_install.py::test_install_home_registers_speech_routes`, which asserts the speech-session routes (`/api/speech/session…` as in today's router prefix) appear in `app.routes`.
- [ ] **Step 4: Run.** `./scripts/local.sh backend pytest tests/home -q`. Expected: the new test fails because `install_home` does not exist yet.
- [ ] **Step 5: Implement `install_home` and `HomeSettings`.** Return `main.py` and `config.py` to upstream, then add to `main.py` only `from app.home.install import install_home` and `install_home(app)` after the router includes. For now the stock loop starts from the lifespan wrapper exactly as `main.py` started it (`game_stock.stock_enabled()` / `stock_loop()`). Point readers of `settings.VOICE_REASONING_EFFORT` at `home_settings`.
- [ ] **Step 6: Run.** `./scripts/local.sh backend pytest tests/home tests/test_conversation.py tests/test_game_stock.py -q`, then `./scripts/local.sh backend ruff check app tests`. Expected: all pass.
- [ ] **Step 7: Commit.** `refactor(home): add home package, install hook and footprint script`.

### Task 2: Home tables, separate migration history, learner context, profile API

**Files:**
- Create: `backend/app/home/models.py`, `backend/app/home/context.py`, `backend/app/home/profile.py` (router), `backend/alembic_home.ini`, `backend/alembic_home/env.py`, `backend/alembic_home/script.py.mako` (copy of upstream's), `backend/alembic_home/versions/0001_home_tables.py`
- Modify: `backend/app/core/deps.py` (one hook line in `get_current_user`), `backend/app/home/install.py`
- Test: `backend/tests/home/test_home_migrations.py`, `backend/tests/home/test_profile.py`, `backend/tests/home/test_context.py`

**Interfaces:**
- Produces: models on upstream `Base`. `HomeProfile` (`__tablename__ = "home_profiles"`) has `user_id: int` (primary key, `ForeignKey("users.id", ondelete="CASCADE")`) and `is_child: bool` (default false). `HomeGameStock` (`__tablename__ = "home_game_stock"`) has exactly today's `GameStock` columns, with indexes renamed `ix_home_game_stock_study_plan_id` and `ix_home_game_stock_bucket`. `app.home.models` is imported by `app.home.install`, never by `app.models`.
- Produces: in `app.home.context`, `@dataclass(frozen=True) class HomeLearner: is_child: bool = False; native_code: str = ""`, `DEFAULT_LEARNER = HomeLearner()`, `current_learner() -> HomeLearner`, `async def enter_user(db: AsyncSession, user: User) -> HomeLearner` (loads the profile and sets the context variable), and `use_learner(learner: HomeLearner)` (a context manager for background jobs that resets on exit).
- Produces: `GET /api/home/profile` → `{"is_child": bool, "tagged_languages": list[str]}` and `PUT /api/home/profile` with body `{"is_child": bool}` → the same shape. Both need an authenticated user. `tagged_languages` lists the user's target languages whose active plan makes `tagged_replies_enabled(native, level, target)` true. Rate limit `30/minute`, following the existing limiter decorator pattern.
- Produces: `run_home_migrations() -> None` in `app.home.install`. It runs `command.upgrade(Config("/app/alembic_home.ini"), "head")`. The lifespan wrapper calls it through `asyncio.to_thread` after entering upstream's lifespan.

- [ ] **Step 1: Write the failing tests.**
  - `test_home_migrations.py::test_home_history_creates_only_home_tables`: points `script_location` at `backend/alembic_home`, monkeypatches `settings.DATABASE_URL` to a temporary SQLite file, and runs upgrade to `head`. Asserts tables `home_profiles`, `home_game_stock` and `alembic_version_home` exist, and that `alembic_version` and `users` do not.
  - `test_home_migrations.py::test_home_revision_matches_models`: compares the migrated columns of both tables against `HomeProfile.__table__` and `HomeGameStock.__table__` column names.
  - `test_profile.py::test_profile_defaults_without_row`: a new user's GET returns `{"is_child": false, "tagged_languages": []}` and creates no row.
  - `test_profile.py::test_put_sets_child_and_get_reads_it`: PUT `true`, then GET shows `true`. PUT `false` shows `false`.
  - `test_profile.py::test_profile_requires_auth`: GET and PUT without a token return 401.
  - `test_profile.py::test_tagged_languages_for_swedish_a1_english`: a user with native `sv` and an active `en-GB` A1 plan gets `["en-GB"]`.
  - `test_context.py::test_default_learner_outside_request`: `current_learner() == DEFAULT_LEARNER`.
  - `test_context.py::test_get_current_user_sets_learner`: after an authenticated request through a test route that returns `current_learner()`, the child user reads `is_child=True`. A following anonymous call reads the default.
  - `test_context.py::test_use_learner_resets`: inside `use_learner(HomeLearner(True, "sv"))` the value is set, and after exit it is the default.
- [ ] **Step 2: Run.** `./scripts/local.sh backend pytest tests/home -q`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement.**
  - The home Alembic env mirrors upstream `alembic/env.py`, with two differences: `version_table="alembic_version_home"` and `include_object` accepting only names starting with `home_`.
  - `alembic_home.ini` sets `script_location = /app/alembic_home`.
  - Revision `0001_home_tables` has `down_revision = None` and creates both tables and their indexes.
  - In `deps.get_current_user`, add exactly one line before `return user`: `await enter_user(db, user)`, imported from `app.home.context`.
  - The lifespan wrapper calls `run_home_migrations()`.
- [ ] **Step 4: Run.** `./scripts/local.sh backend pytest tests/home tests/test_auth.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** `feat(home): add home tables, separate migration history and learner context`.

### Task 3: Child and tagged-line prompts through the learner context

**Files:**
- Create: `backend/app/home/prompts.py`
- Move: `backend/app/services/spoken_lines.py` → `backend/app/home/spoken_lines.py`; its test → `backend/tests/home/test_spoken_lines.py`
- Modify (return to upstream, then hook): `backend/app/services/prompts/common.py` (upstream, no hook), `prompts/tutor.py`, `prompts/lesson.py`
- Return to upstream: `backend/app/services/lesson_generator.py`, `backend/app/routers/study_plan.py`, `backend/app/models/user.py`, `backend/app/schemas/auth.py`, `backend/app/routers/auth.py`, `backend/tests/test_auth.py`, `backend/tests/test_prompts.py`
- Modify: `backend/app/routers/conversation.py` (`user_is_child = user.is_child` becomes `user_is_child = (await enter_user(db, user)).is_child`, which sets the learner for the websocket task; this line stays as the router's learner hook), `backend/app/services/conversation_pipeline.py` (stop passing `is_child` to the prompt builders; pass `target_code`)
- Keep for now: revision `0058_user_is_child.py`. All three home revisions are deleted together in Task 4, so the upstream chain is never broken mid-plan.
- Test: `backend/tests/home/test_prompts.py` (receives our assertions from `tests/test_prompts.py`)

**Interfaces:**
- Consumes: `current_learner()` from Task 2.
- Produces, in `app.home.prompts`:
  - `child_instruction() -> str`, with today's text.
  - `instruction_language_rules(level: str, native_code: str, target_code: str) -> str`, with today's text.
  - `child_suffix() -> str`: `"\n\n" + child_instruction()` when `current_learner().is_child`, else `""`.
  - `tutor_suffix(cefr_level: str, target_code: str) -> str`: today's `_extra_sections` output, with the child flag and native code taken from `current_learner()`.
- Hook lines:
  - `build_tutor_system_prompt` and `build_conversation_system_prompt` gain one keyword parameter `target_code: str = ""` and one line `prompt += tutor_suffix(cefr_level, target_code)`.
  - `build_lesson_generation_prompt` gains one line, `prompt = … + child_suffix()`, at its return.

- [ ] **Step 1: Move our prompt assertions** from `tests/test_prompts.py` into `tests/home/test_prompts.py`. Rewrite only the setup: tests that passed `is_child=True` now wrap the call in `use_learner(HomeLearner(is_child=True, native_code="sv"))`, and the expected strings stay unchanged. Add `test_child_suffix_empty_by_default`.
- [ ] **Step 2: Run.** `./scripts/local.sh backend pytest tests/home/test_prompts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Make the moves and returns listed above. Every former `is_child=user.is_child` argument disappears. In `routers/chat.py`, the only change in this task is passing `target_code=target_language` to both builder calls (the chat tagged display comes in Task 6).
- [ ] **Step 4: Run.** `./scripts/local.sh backend pytest tests/home tests/test_prompts.py tests/test_chat.py tests/test_lessons.py tests/test_lesson_generator.py tests/test_auth.py -q`. Expected: PASS. `grep -rn is_child backend/app --include=*.py | grep -v app/home` lists only game files (`models/game.py`, `services/games.py`, `services/game_stock.py`, `prompts/games.py`; handled in Task 4), plus `routers/conversation.py` and `services/conversation_pipeline.py` (handled in Task 5).
- [ ] **Step 5: Commit.** `refactor(home): read the child setting from the home profile`.

### Task 4: Game stock, replay and home game generation

**Files:**
- Move: `backend/app/services/game_stock.py` → `backend/app/home/game_stock.py`; `tests/test_game_stock.py` → `tests/home/test_game_stock.py`
- Create: `backend/app/home/games.py` (generation, salvage, finalize, reshuffle, score, stock-empty output, replay, start-from-stock), `backend/app/home/game_prompts.py`, `backend/app/home/game_schemas.py` (`DetectiveDraft` and the `*DraftContent` models), `backend/app/home/games_router.py` (replay endpoint)
- Return to upstream, then hook: `backend/app/services/games.py`, `backend/app/routers/games.py`
- Return to upstream: `backend/app/models/game.py`, `backend/app/models/__init__.py`, `backend/app/schemas/games.py`, `backend/app/services/prompts/games.py`, `backend/tests/test_games.py`, `backend/tests/test_sentence_order.py`, `backend/tests/test_vocabulary_pairs.py`
- Delete: `backend/alembic/versions/0058_user_is_child.py`, `backend/alembic/versions/0059_game_session_is_child.py`, `backend/alembic/versions/0060_game_stock.py`
- Test: `backend/tests/home/test_games.py` (our assertions from the three upstream game test files)

**Interfaces:**
- Consumes: `HomeGameStock` and `use_learner` (Task 2); `child_suffix` (Task 3).
- Produces, in `app.home.games`:
  - `async def start_from_stock(db: AsyncSession, user: User, plan: StudyPlan, body: GameCreate, game_type: str, request: GameRequest, limited: bool, now: datetime) -> GameSession | None`: today's stock block from `create_game`, unchanged except that `is_child` is no longer copied onto the session.
  - `async def stock_empty_output(db, plan, game_type) -> dict`, `async def replay_game(db, user, session_id) -> GameSession`, `async def generate_content(request: GenerationRequest, deadline: float) -> DetectiveContent | SentenceOrderContent | VocabularyPairsContent`: today's bodies. `GenerationRequest` drops `is_child`; prompts read it through `child_suffix()` under `use_learner(...)`, which the stock worker sets per job from the plan owner's profile.
- Hook lines:
  - In upstream `create_game`, immediately after the quota check, `if stock_mode(): return await start_from_stock(db, user, plan, body, game_type, request, limited, now), False`, where `stock_mode()` comes from `app.home.games` and returns `game_stock.stock_enabled()`. Upstream's return type annotation widens to `tuple[GameSession | None, bool]`.
  - In upstream `routers/games.py` `start_game`, when the session is `None`, return `await stock_empty_output(db, plan, game_type)` with status 200. When stock mode is off, upstream's background generation path stays untouched.
  - The replay endpoint `POST /api/games/sessions/{session_id}/replay` is served by `app.home.games_router`, registered in `install_home`, with the same limiter.
- Replay uses the profile's current child setting. This only affects prompts and generation, and replays generate nothing, so today's replay tests pass unchanged.

- [ ] **Step 1: Move the tests.** Move our assertions into `tests/home/test_games.py` and the moved `test_game_stock.py`, and update imports to `app.home.*`. Replace `GameStock` with `HomeGameStock` and drop `is_child=` arguments to models. Add `test_stock_job_uses_plan_owner_profile`: with a child profile row for the plan owner, the prompt captured by a stubbed `llm_adapter.structured_output` contains `child_instruction()`. Without the row, it does not.
- [ ] **Step 2: Run.** `./scripts/local.sh backend pytest tests/home -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the moves, returns, hooks and deletions above. The lifespan wrapper now imports `stock_enabled` and `stock_loop` from `app.home.game_stock`.
- [ ] **Step 4: Run.** `./scripts/local.sh backend pytest tests/home tests/test_games.py tests/test_sentence_order.py tests/test_vocabulary_pairs.py tests/test_games_postgres.py -q`. Expected: PASS (the Postgres test may skip, as it does today). `ls backend/alembic/versions | tail -1` shows `0057_…`.
- [ ] **Step 5: Commit.** `refactor(home): move game stock, replay and generation into the home package`.

### Task 5: Home conversation pipeline subclass

**Files:**
- Create: `backend/app/home/conversation.py`
- Move: `backend/app/services/provisional_turn.py` → `backend/app/home/provisional_turn.py`, with its test, to `tests/home/`
- Return to upstream, then hook: `backend/app/services/conversation_pipeline.py`, `backend/app/routers/conversation.py`
- Decide per change: `backend/app/services/llm_adapter.py`, `backend/app/services/tts_service.py`
- Return to upstream: `backend/tests/test_conversation_pipeline_service.py`, `backend/tests/test_llm_adapter.py`, `backend/tests/test_tts_service.py`
- Test: `backend/tests/home/test_conversation_pipeline.py`, `backend/tests/home/test_llm_adapter.py`, `backend/tests/home/test_tts_service.py`

**Interfaces:**
- Produces: `class HomeConversationPipeline(ConversationPipeline)`, whose extra constructor keywords are `small_llm: bool` and `generated_opener: bool`. It carries `_StreamedSpeech`, provisional turns, the opener, tagged spoken lines, sentence splitting, `_effort_kwargs` from `home_settings`, and `handle_control(...)` for the provisional `confirm` and `abort` frames.
- Produces: `async def build_pipeline(**kwargs: Any) -> ConversationPipeline` in `app.home.conversation`. It awaits `live_llm_is_small()`, computes `generated_opener`, and returns a `HomeConversationPipeline`.
- Hook lines in `routers/conversation.py`:
  - `pipeline = await build_pipeline(...)` replaces the constructor call with the same keyword arguments.
  - The websocket loop's provisional-frame handling becomes one delegation to `pipeline.handle_control(...)`, guarded by `isinstance(pipeline, HomeConversationPipeline)`.
- Upstream seams: where a behaviour lives inside a large upstream method with no override point, add the smallest extraction in the upstream file, for example a `_synthesize_chunk(text, language=None)` parameter or a single new method that upstream's code calls in place of inline code. Each extraction must leave upstream's tests passing unchanged. Keep a list of extractions for the home spec (Task 12).
- `llm_adapter.py` (reasoning effort, 503 as unavailable, prefilled assistant turn) and `tts_service.py` (language-aware voice): keep each as an in-place patch unless a subclass or wrapper in `app/home/` removes it entirely. Move their tests to `tests/home/` either way.

- [ ] **Step 1: Move our pipeline, adapter and TTS assertions** into the `tests/home/` files. Construct `HomeConversationPipeline` wherever today's tests construct `ConversationPipeline` with home keywords. Add `test_build_pipeline_returns_home_pipeline`, which stubs `live_llm_is_small` to return `True` and asserts `generated_opener is False`.
- [ ] **Step 2: Run.** `./scripts/local.sh backend pytest tests/home -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the subclass, the factory, the router hooks and the minimal seams.
- [ ] **Step 4: Run.** `./scripts/local.sh backend pytest tests/home tests/test_conversation.py tests/test_conversation_pipeline_service.py tests/test_llm_adapter.py tests/test_tts_service.py -q`. Expected: PASS. Then `git diff main -- backend/app/services/conversation_pipeline.py | grep -c '^[+-][^+-]'` is under 40.
- [ ] **Step 5: Commit.** `refactor(home): move voice conversation behaviour into a pipeline subclass`.

### Task 5a: Upstream seam tests

**Files:**
- Create: `backend/tests/home/test_upstream_seams.py`, `backend/app/home/SEAMS.md` (the watchlist, see below)

**Interfaces:**
- Consumes: the hooks and subclass from Tasks 1–5.
- Produces: one test per upstream seam, each asserting with `inspect.signature` / `hasattr`. On failure, the message names the seam and the home module that depends on it, for example `"upstream ConversationPipeline._process_turn changed; HomeConversationPipeline overrides it"`.

- [ ] **Step 1: Write the tests.**
  - `test_pipeline_overridden_methods_exist`: every method `HomeConversationPipeline` defines that also exists on `ConversationPipeline` is still present upstream. Its parameter names, excluding any home-only keywords the subclass adds, match the subclass's call or override.
  - `test_pipeline_constructor_accepts_router_kwargs`: the keyword arguments `routers/conversation.py` passes to `build_pipeline` are all accepted by `ConversationPipeline.__init__`.
  - `test_prompt_builders_accept_target_code`: `build_tutor_system_prompt`, `build_conversation_system_prompt` and `build_lesson_generation_prompt` still exist and accept the parameters our hooks pass.
  - `test_create_game_hook_inputs`: `create_game` still exists with parameters `(db, user, plan, body, game_type)`.
  - `test_get_current_user_sets_learner`: `get_current_user`'s source contains `enter_user(` (guards against the hook being lost in a merge).
  - `test_hook_lines_present`: each upstream hook site from the home spec's hook list still calls its `app.home` function, checked by searching the module source for the call name. This covers `main.py` `install_home(`, `routers/conversation.py` `build_pipeline(`, `routers/games.py` `stock_empty_output(`, `services/games.py` `start_from_stock(`, `routers/chat.py` `TaggedChatStream(`.
- [ ] **Step 2: Run** `./scripts/local.sh backend pytest tests/home/test_upstream_seams.py -q`. Expected: PASS against the current tree. Then temporarily rename one upstream method locally to confirm the failure message names it, and revert.
- [ ] **Step 3: Write `backend/app/home/SEAMS.md`**, a plain list of the upstream files whose changes can break home behaviour: every hooked file, `services/conversation_pipeline.py`, `services/games.py`, `services/prompts/tutor.py`, `services/prompts/lesson.py`, `core/deps.py`, `services/llm_adapter.py`, `services/tts_service.py`, the four frontend files with home call sites (`ConversationMode.tsx`, `GameCatalog.tsx`, `ProfileSection.tsx`, `i18n/request.ts`), and `chat/page.tsx`. One path per line, so the script in Task 12 can read it.
- [ ] **Step 4: Commit.** `test(home): pin the upstream seams home code builds on`.

### Task 6: Chat tagged display and backend leftovers

**Files:**
- Create: `backend/app/home/chat.py`
- Modify: `backend/app/routers/chat.py`
- Return to upstream: `backend/app/routers/languages.py`, `backend/app/schemas/language.py`, `backend/tests/test_chat.py`, `backend/tests/test_multi_language.py`
- Test: `backend/tests/home/test_chat.py`

**Interfaces:**
- Produces: `class TaggedChatStream` in `app.home.chat`, built as `TaggedChatStream(native_code: str, cefr_level: str, target_code: str)`. It has `token(token: str) -> str | None` (returns the token to stream, or `None` while buffering) and `final() -> str | None` (returns the cleaned reply when tagged).
- Hook lines in `chat.py`: construct the stream once, and replace the two streaming lines with calls to `token` and `final`. Keep `"error_code": "llm_unavailable"` as an in-place patch.
- `tagged_replies` leaves `LanguagePlanInfo`; the frontend reads `tagged_languages` from `/api/home/profile` (Task 2).

- [ ] **Step 1: Move our chat and multi-language assertions** into `tests/home/test_chat.py`. Assertions that read `plan.tagged_replies` from `/api/languages` now read `tagged_languages` from `/api/home/profile`.
- [ ] **Step 2: Run** `./scripts/local.sh backend pytest tests/home/test_chat.py -q`. Expected: FAIL. Then implement.
- [ ] **Step 3: Run.** `./scripts/local.sh backend pytest tests/home tests/test_chat.py tests/test_chat_conversations.py tests/test_multi_language.py -q`. Expected: PASS. Then `./scripts/local.sh backend ruff check app tests` and `./scripts/local.sh backend ruff format --check app tests`.
- [ ] **Step 4: Commit.** `refactor(home): move tagged chat display into the home package`.

### Task 7: Speech gateway and compose leftovers

**Files:**
- Return to upstream: `docker-compose.yml`
- Check: `services/speech-gateway/` (home-owned, unchanged)

- [ ] **Step 1: Return `docker-compose.yml` to upstream.** Confirm `VOICE_REASONING_EFFORT` is still read by `home_settings`, with default `low`.
- [ ] **Step 2: Run.** `./scripts/home-surface.sh`. Confirm that no backend file outside the hook list of Tasks 1–6, plus `deps.py`, `llm_adapter.py`, `tts_service.py` and `chat.py`, remains modified. Any other file is a defect in an earlier task: report it.
- [ ] **Step 3: Commit.** `chore(home): return compose to upstream`.

### Task 8: Home translation overlay

**Files:**
- Create: `frontend/src/home/i18n.ts`, `messages/home/<locale>.json` for each of the 16 locales that have our keys today
- Modify: `frontend/src/i18n/request.ts`
- Return to upstream: `messages/*.json` (all 16)
- Test: `frontend/tests/home/i18n.test.ts`

**Interfaces:**
- Produces: `mergeMessages(base: Messages, overlay: Messages): Messages` (deep merge, overlay wins, arrays replaced) and `async function loadHomeMessages(locale: string): Promise<Messages>` (falls back to `en`) in `@/home/i18n`.
- Hook in `request.ts`: after loading `messages`, one line `messages = mergeMessages(messages, await loadHomeMessages(locale))`.
- Each home file holds exactly the keys our branch added today (for example `games.stockEmpty`, `games.firstGamesPending`, `games.replayHeading`, `games.replay`, `profile.isChild`, `profile.isChildHint`, `chat.linguAway`, and the `conversation.*` speech keys), with today's translations, under the same nesting.

- [ ] **Step 1: Write the tests.**
  - `test_merge_keeps_base_and_adds_overlay`.
  - `test_overlay_wins_on_conflict`.
  - `test_missing_locale_falls_back_to_english`: `loadHomeMessages('xx')` equals the English file.
  - `test_every_home_locale_has_english_keys`: every `messages/home/*.json` has the same key set as `messages/home/en.json`.
- [ ] **Step 2: Run** `./scripts/local.sh frontend npx vitest run tests/home/i18n.test.ts`. Expected: FAIL. Then implement and generate the home files from `git diff main -- messages/`.
- [ ] **Step 3: Run** `./scripts/local.sh frontend npx vitest run tests/home tests/i18n`. Expected: PASS.
- [ ] **Step 4: Commit.** `refactor(home): load home translations as an overlay`.

### Task 9: Home profile store, child toggle and chat read-aloud

**Files:**
- Create: `frontend/src/home/store/profile.ts`, `frontend/src/home/components/ChildProfileToggle.tsx`
- Modify: `frontend/src/components/settings/ProfileSection.tsx` (one import, one element), `frontend/src/app/(app)/chat/page.tsx`
- Return to upstream: `frontend/src/lib/mappers.ts`, `frontend/src/store/auth.ts`, `frontend/src/store/language.ts`, `frontend/tests/lib/mappers.test.ts`, `frontend/tests/components/ProfileSection.test.tsx`
- Test: `frontend/tests/home/ChildProfileToggle.test.tsx`, `frontend/tests/home/chat-tagged.test.tsx` (our cases from `tests/app/chat-memory-stream.test.tsx`)

**Interfaces:**
- Consumes: `GET`/`PUT /api/home/profile` (Task 2).
- Produces: `useHomeProfileStore` with state `{ isChild: boolean; taggedLanguages: string[]; loaded: boolean }` and actions `load(): Promise<void>` and `setChild(value: boolean): Promise<void>`. `setChild` is optimistic and rolls back on failure. It uses `apiFetch`.
- Produces: `useTaggedReplies(languageCode: string | null): boolean` in the same module.
- Hook in the chat page: `const taggedReplies = useTaggedReplies(activeLanguage)` replaces today's selector. The `linguAway` and `error_code` lines stay as in-place patches.

- [ ] **Step 1: Write the tests.**
  - `toggle reflects loaded profile`.
  - `click saves immediately via PUT /api/home/profile`.
  - `failed save restores previous value and shows an error`, which uses the existing settings error styling.
  - `tagged language hides read-aloud`, moved from today's chat test.
- [ ] **Step 2: Run** `./scripts/local.sh frontend npx vitest run tests/home`. Expected: FAIL. Then implement.
- [ ] **Step 3: Run** `./scripts/local.sh frontend npx vitest run tests/home tests/components/ProfileSection.test.tsx tests/app tests/lib`. Expected: PASS.
- [ ] **Step 4: Commit.** `refactor(home): move the child toggle and tagged-reply flag to the home profile`.

### Task 10: Stock-empty note and replay in the game catalog

**Files:**
- Create: `frontend/src/home/components/StockEmptyNote.tsx`, `frontend/src/home/lib/games.ts` (types `ReplayableGame`, `GameStockEmpty`, guard `isStockEmpty(value: unknown): value is GameStockEmpty`)
- Modify: `frontend/src/components/games/GameCatalog.tsx`
- Return to upstream: `frontend/src/lib/detective.ts`, `frontend/tests/app/detective.test.tsx`
- Test: `frontend/tests/home/StockEmptyNote.test.tsx`

**Interfaces:**
- Produces: `<StockEmptyNote empty={GameStockEmpty} gamePath={string} disabled={boolean} />`. It owns the replay request (`POST /sessions/{id}/replay` through `gameRequest`), its own busy state, and navigation.
- Hook in `GameCatalog.tsx`: an `empty` state, an `isStockEmpty(session)` branch after the start request (resetting `pending.current`), and one render line for `<StockEmptyNote … />`. The local `replay` function leaves `GameCatalog`.

- [ ] **Step 1: Move today's detective and catalog empty-stock cases** into `StockEmptyNote.test.tsx`. Add `replay button posts and navigates`.
- [ ] **Step 2: Run, implement, run.** `./scripts/local.sh frontend npx vitest run tests/home tests/app/detective.test.tsx`. Expected: PASS.
- [ ] **Step 3: Commit.** `refactor(home): render the empty-stock note from a home component`.

### Task 11: Speech session and voice conversation hooks

**Files:**
- Move: `frontend/src/hooks/useSpeechSession.ts` → `frontend/src/home/hooks/useSpeechSession.ts`; `frontend/src/store/speech-session.ts` → `frontend/src/home/store/speech-session.ts`; `frontend/tests/hooks/useSpeechSession.test.tsx` → `frontend/tests/home/`
- Create: `frontend/src/home/hooks/useProvisionalTurn.ts`, `frontend/src/home/components/HeardLine.tsx`, `frontend/src/home/components/SpeechStatusNotice.tsx`, `frontend/src/home/lib/conversation.ts` (`PROVISIONAL_SILENCE_MS`, `provisionalTurnsEnabled`, `joinAudioFrames`, `TurnControl`, `turnControl`)
- Modify: `frontend/src/components/conversation/ConversationMode.tsx`, `frontend/src/app/(app)/layout.tsx` (import path only)
- Return to upstream: `frontend/src/lib/conversation-vad.ts`, `frontend/src/lib/conversation-ws.ts`, `frontend/tests/lib/conversation-ws.test.ts`, `frontend/tests/components/ConversationMode.test.tsx`, `frontend/tests/components/ConversationModeWordTooltip.test.tsx`
- Keep in place: `frontend/src/components/conversation/MicButton.tsx` (`canStart` prop)
- Test: `frontend/tests/home/ConversationMode.home.test.tsx` (our cases from today's `ConversationMode.test.tsx`), `frontend/tests/home/conversation.test.ts`

**Interfaces:**
- Produces: `useProvisionalTurn({ wsRef, redemptionMs }: { wsRef: RefObject<WebSocket | null>; redemptionMs: number })`, returning `{ onFrame(frame: Float32Array, isSpeech: boolean): void; onSpeechEnd(): 'confirmed' | 'sent'; abort(): void; reset(): void }`. Today's provisional logic moves here unchanged.
- Produces: `<HeardLine text={string} onRedo={() => void} disabled={boolean} />` and `<SpeechStatusNotice />` (reads the speech-session store and renders today's status texts and link).
- Hook lines in `ConversationMode.tsx`: the hook call, calls at today's VAD callback points, the redo handler, `canStart` derived from the speech-session state, and the two component elements. The target is under 60 changed lines against upstream.

- [ ] **Step 1: Move our cases** into `tests/home/ConversationMode.home.test.tsx`, rendering the real `ConversationMode` with the same mocks as today. Move the `conversation-ws` and VAD helper cases into `tests/home/conversation.test.ts`.
- [ ] **Step 2: Run** `./scripts/local.sh frontend npx vitest run tests/home`. Expected: FAIL on imports. Then implement.
- [ ] **Step 3: Run** `./scripts/local.sh frontend npx vitest run tests/home tests/components tests/hooks tests/lib tests/app`, `./scripts/local.sh frontend npm run lint` and `./scripts/local.sh frontend npx tsc --noEmit`. Expected: all pass. Then `git diff main -- frontend/src/components/conversation/ConversationMode.tsx | grep -c '^[+-][^+-]'` is under 60.
- [ ] **Step 4: Commit.** `refactor(home): move voice conversation additions into home hooks and components`.

### Task 12: Home spec, agent pointer and final footprint

**Files:**
- Create: `specs/home-deployment.instructions.md`, `CLAUDE.md`
- Return to upstream: all eight `specs/*.instructions.md` files our branch edited
- Modify: `docs/superpowers/specs/2026-11-20-fork-surface-design.md` (only if something changed during the build, recorded as current design)

- [ ] **Step 1: Write the home spec** from today's diffs of the eight upstream specs, rewritten as current behaviour (no history), plus these sections, as concise lists without tables:
  - home layout;
  - hook points, listing every upstream file still modified with a one-line reason, including the Task 5 seams;
  - home migrations (version table, startup order, adding a revision with `alembic -c alembic_home.ini revision`);
  - the pre-deploy database wipe for this release;
  - `VOICE_REASONING_EFFORT`;
  - the footprint script.
- [ ] **Step 2: Write `CLAUDE.md`.** Three lines telling agents to read `AGENTS.md`, then `specs/home-deployment.instructions.md`, and to put new home behaviour in home paths with hooks only.
- [ ] **Step 3: Return the eight upstream specs.** Run `./scripts/home-surface.sh`. Expected: about 15 to 20 upstream files, every one listed in the home spec's hook section.
- [ ] **Step 3a: Add the sync report and checklist.**
  - `scripts/home-surface.sh --since <rev>` prints, for `<rev>..upstream/main`, the upstream commits (`git log --oneline`) that touch any path in `backend/app/home/SEAMS.md`, grouped by path, then a count. Without `--since`, behaviour is unchanged.
  - Add `chat/page.tsx`'s seam to `test_hook_lines_present` if Task 9 left a home call there.
  - The home spec gets an "Upstream sync" section with this checklist:
    1. Run `./scripts/home-surface.sh --since <last synced upstream commit>` and read the listed commits.
    2. Merge `upstream/main`.
    3. Run `pytest tests/home`, including the seam tests, frontend `tsc`, and `vitest run tests/home`.
    4. By hand on the deployed app: one voice conversation as a child profile, and one game start.
    5. Record the synced upstream commit in the home spec.
- [ ] **Step 4: Ask the owner before the full pre-push validation**, then run it with the `pre-push` skill if approved.
- [ ] **Step 5: Commit.** `docs(home): document the home layout and hook points`. Include the final footprint line in the message.
