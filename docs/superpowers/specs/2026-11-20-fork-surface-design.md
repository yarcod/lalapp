# Shrinking the home fork's footprint on upstream FreeLingo

## Intent

The home deployment (see `2026-11-05-home-deployment-design.md`) is a fork of `artcc/freelingo`.
Its 38 commits on `feature/home-deployment` modify about 80 upstream files, and upstream has since
changed about 60 of those. A trial rebase onto `upstream/main` stopped on conflicts 13 times, and
both sides created Alembic revisions 0058 to 0060 from the same parent.

The goal is to move our behaviour into files upstream never touches, leaving upstream files with
only a few small, obvious hook lines. That makes today's sync cheaper and every later one cheap.
The home features are strictly for home; nothing is being prepared for upstream contribution.

## Goals

- Our code, tests, translations, specs and migrations live in home-owned paths.
- Upstream files carry only short hook call sites, each easy to re-apply by hand after a conflict.
- Our database objects never enter upstream's Alembic chain.
- Behaviour after the refactor is identical to today's branch, except the deliberate changes listed
  under Behaviour changes.
- A command reports the remaining footprint on upstream files so it can be watched over time.

## Non-goals

- Merging `upstream/main`. That is the next step, done after this refactor lands.
- New features or behaviour fixes beyond what the refactor needs.
- Making any of this suitable for upstream.

## Anti-goals

- Hiding fork behaviour so well that a future reader cannot find it. Every hook line names the
  home module it calls.
- Copying whole upstream files into home paths when a hook would do. A copy never conflicts but
  silently stops receiving upstream fixes.
- Weakening any AGENTS.md invariant (auth, per-language isolation, backend-only provider access).

## Constraints

- Docker is unavailable locally. Validation is backend tests and static checks, frontend
  lint/typecheck/unit tests. For this refactor the owner gave standing approval for targeted tests,
  lint and typecheck between commits; any failure still stops work for a report, and the full
  pre-push suite still needs asking.
- The deployed database at `learning.edholm.cc` is at revision `0060_game_stock` with only the
  owner's test account. Nothing in it needs keeping.
- No new dependencies.
- AGENTS.md documentation rules apply. The owner approved one home-owned spec in place of edits to
  upstream specs.

## Approaches considered (database)

- **A. No database changes.** Child flag from an environment list of usernames, game stock in Redis.
  Fully upstream schema, but loses the Settings toggle and rewrites the stock logic.
- **B. Home-owned tables with a separate Alembic history.** Chosen by the owner. Upstream's tables
  and revision chain stay untouched; existing stock code and the toggle mostly survive.
- **C. Keep our revisions in upstream's chain.** Rejected: every sync needs a new merge revision.

## Design

### Home-owned locations

- Backend package `backend/app/home/` holding models, routers, services, prompts, settings and the
  pipeline subclass. Existing home-only modules move here: `routers/speech_session.py`,
  `services/game_stock.py`, `services/provisional_turn.py`, `services/spoken_lines.py`.
- Home migrations in `backend/alembic_home/` with `backend/alembic_home.ini`.
- Backend tests in `backend/tests/home/`.
- Frontend code in `frontend/src/home/` (components, hooks, store). Existing
  `hooks/useSpeechSession.ts` and `store/speech-session.ts` move here.
- Frontend tests in `frontend/tests/home/`.
- Translations in `messages/home/<locale>.json`.
- One spec, `specs/home-deployment.instructions.md`, describing current home behaviour.
- `services/speech-gateway/` and `docs/superpowers/` stay where they are; upstream has neither.

### Database

- Two tables, both prefixed `home_`:
  - `home_profiles`: `user_id` (primary key, FK to `users.id`, cascade delete) and `is_child`.
    A missing row means not a child.
  - `home_game_stock`: today's `game_stock` columns unchanged.
- `game_sessions.is_child` is dropped. Replaying a game uses the profile's current child setting.
- Home models use upstream's `Base` so the foreign key to `users` resolves and test `create_all`
  includes them. They are imported only from `app.home`, never from `app.models`.
- `backend/alembic_home/env.py` uses version table `alembic_version_home` and an `include_object`
  filter that only sees `home_` tables. Its single initial revision creates both tables.
- Our three revisions 0058 to 0060 are deleted.
- Home migrations run inside the app, so no deployment file changes. Upstream's lifespan already runs
  `alembic upgrade head` (`_run_migrations` in `main.py`), and the live deployment (the terranse
  template `freelingo.yaml.j2`) also runs it before uvicorn. `install_home(app)` wraps the lifespan:
  it enters upstream's lifespan first, then upgrades the home history to head, then starts the
  stock loop. (Builder check; my call.)
- The deployed database is wiped and recreated before the first deploy of this refactor (owner's
  decision). The backend fails to start against revision `0060_game_stock` once that revision is
  deleted, so the wipe must come first. The owner re-creates the test account afterwards. The wipe
  is a deployment step for the maintainer, not part of the code change; the plan states it.

### Backend hooks into upstream

Each upstream file keeps at most a few lines. The intended hooks:

- `main.py`: one call, `install_home(app)`, which includes home routers and wraps the app's
  lifespan to start and stop the stock loop. The `speech_session` router include and the inline
  stock task leave `main.py`.
- `core/config.py`: no change. Home settings such as `VOICE_REASONING_EFFORT` move to a
  `HomeSettings` class in `app/home/settings.py`, read from the same environment.
- Child flag: a context variable in `app/home/context.py` holds the current learner's home profile.
  It is set once per request or socket (where the user is resolved) and by the stock worker per
  job. Prompt builders call a single home function, for example `home_prompt_suffix(...)`, instead
  of every builder and router threading an `is_child` argument. This removes the `is_child`
  parameters from the chat, conversation, study-plan and lesson-generator call chains.
- Tagged Swedish lines and the child instruction live in `app/home/prompts.py`. Upstream prompt
  modules keep only the one-line call into it where the text must be placed.
- Auth: `UserResponse`, `UserUpdate` and `routers/auth.py` return to upstream. The toggle reads and
  writes `GET`/`PUT /api/home/profile`.
- Conversation: `ConversationPipeline` returns to upstream. `HomeConversationPipeline` in
  `app/home/conversation.py` subclasses it and carries streamed speech, provisional turns, the
  generated opener, tagged spoken lines, sentence splitting and reasoning effort. The conversation
  router constructs the home class through one line. Where upstream has no method to override, the
  builder adds the smallest possible split in the upstream file (for example extracting a method)
  rather than copying a large method.
- Games: the stock, replay, salvage, finalize and reshuffle logic leaves `services/games.py` for
  `app/home/games.py`. The replay endpoint moves to a home router. The upstream games router keeps
  one hook where a new game is started, to serve from stock. Prompt changes to the game prompts
  (eight detective challenges and similar) move to home prompt functions selected at that hook.
- `llm_adapter.py` and `tts_service.py`: small changes (reasoning effort, 503 as unavailable,
  prefilled assistant turn, language-aware TTS). Keep them as small patches if no clean seam exists;
  the builder decides per change.
- `docker-compose.yml`: returns to upstream, with no home override file. Production runs from the
  terranse template, not lalapp's compose files. `VOICE_REASONING_EFFORT` keeps its default `low`
  in `HomeSettings`; setting it in production belongs to the terranse template. (My call.)

### Frontend hooks into upstream

- Translations: `frontend/src/i18n/request.ts` deep-merges `messages/home/<locale>.json` over the
  upstream messages, falling back to `messages/home/en.json`. The 16 upstream message files return to
  upstream. Keys keep their current names and namespaces so components need no change.
- `ConversationMode.tsx`: our logic leaves the component as hooks in `frontend/src/home/`, such as
  `useProvisionalTurn`, the speech-session state, and redo, plus small presentational pieces
  (the "Lingu heard" line and the speech status notice). The component keeps short call sites.
  Upstream rewrote this component, so the call sites are re-applied onto upstream's version during
  the merge; this design only makes that re-application small.
- `GameCatalog.tsx`: the stock-empty note and the replay list become one home component rendered
  from one line.
- `ProfileSection.tsx`: one line renders a home `ChildProfileToggle` that uses the home endpoint.
  `mappers.ts` and `store/auth.ts` return to upstream.
- Chat page, `MicButton`, `conversation-vad.ts`, `conversation-ws.ts`, `detective.ts`,
  `(app)/layout.tsx`, `store/language.ts`: each moves into home code where a seam exists, and
  otherwise stays a small patch. The builder records which.

### Tests

- Our assertions leave upstream test files for `tests/home/` files. Upstream test files return to
  upstream unless a home hook changes behaviour they assert; then the smallest adjustment stays.
- New tests cover the home Alembic environment (only `home_` tables, separate version table) and
  the i18n merge.

### Documentation

- `specs/home-deployment.instructions.md` documents current home behaviour, the home layout, the
  hook points, the two-step migration and the one-time cleanup. Our edits to the eight upstream
  specs are reverted and their content moves here, as current behaviour rather than history.
- A root `CLAUDE.md` (absent upstream) tells agents to read AGENTS.md, then the home spec, and to
  put new home behaviour in home paths. AGENTS.md stays upstream's.
- `CHANGELOG.md` is upstream's; this refactor adds no entry.

### Measuring the footprint

- `scripts/home-surface.sh` lists upstream files the branch modifies relative to the merge base
  with `upstream/main`, with line counts, ignoring home-owned paths. It is the yardstick for this
  work and later syncs.
- Expected result: about 80 modified upstream files today, down to roughly 15 to 20, each with a
  short change.

### Behaviour changes

- Replaying a finished game uses the profile's current child setting instead of the setting when it
  was first played.
- The child checkbox in Settings saves as soon as it is clicked, instead of with Save Changes
  (owner's decision).
- Nothing else is meant to change.

## Left to the builder

- Exact module and function names inside the home package.
- Per small change (adapter, TTS, VAD, websocket helpers), whether a seam exists or it stays a patch.
- Where the context variable is set for HTTP requests and websockets.
- Commit order, as long as each commit leaves tests passing.
