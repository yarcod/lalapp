---
applyTo: "backend/app/home/**, backend/alembic_home/**, frontend/src/home/**, messages/home/**, services/speech-gateway/**, scripts/home-surface.sh"
---

# Home deployment

This repository is a fork of upstream FreeLingo for a kids-only deployment on a single-GPU home host.
All home behaviour lives in home-owned paths and reaches upstream files through short hooks. This spec
is the only home-specific spec; upstream specs describe upstream behaviour and are not edited for the
fork. Where this spec and an upstream spec disagree about a home feature, this spec wins.

## Layout

- `backend/app/home/`: home backend code (context, profile, prompts, chat, conversation, provisional
  turns, spoken lines, games, game stock, speech session, settings, models, installer).
- `backend/app/home/SEAMS.md`: the list of upstream files the fork modifies, read by the sync report.
- `backend/alembic_home/` and `backend/alembic_home.ini`: the home migration history.
- `backend/tests/home/`: home tests, including `test_upstream_seams.py`.
- `frontend/src/home/` and `frontend/tests/home/`: home components, hooks, stores and libraries.
- `messages/home/<locale>.json`: home translations for all 15 UI locales.
- `services/speech-gateway/`: the local speech and LLM-routing gateway (not a Compose service).
- `scripts/home-surface.sh`: footprint and sync report.

Home code imports upstream freely; upstream imports home code only at the hook lines below.

## Settings

Home settings are `HomeSettings` in `app/home/settings.py`, read from the same environment as
upstream settings.

- `VOICE_REASONING_EFFORT` (default `low`; empty omits it): reasoning effort for local voice replies.
  It is sent only to the local Ollama path and only on the full-LLM tier, never on the shared small
  tier.
- `HOME_GAME_STOCK` (default `false`): enables stock mode. Stock mode runs only when
  `HOME_GAME_STOCK` is true and `LLM_PROVIDER` is `ollama`; otherwise upstream's on-demand game
  generation is used and the stock loop does not start.

## Child profile

- `home_profiles` holds `is_child` per user. A user without a row is not a child; every account
  starts that way.
- `GET /api/home/profile` and `PUT /api/home/profile` (30/min, authenticated) read and write the flag.
  The response is `{is_child, tagged_languages}`, where `tagged_languages` lists the user's active
  plan languages for which tagged replies apply. Upstream `/api/auth/me` does not carry the flag.
- The frontend profile store (`frontend/src/home/store/profile.ts`) holds the profile. The Settings
  profile section shows a child checkbox that saves on click; if the request fails the checkbox
  returns to its saved value and shows the shared error alert. Saves are serialized, the store
  resets on session change, and it reloads when the language store's `userLanguages` change so
  `tagged_languages` follows plan changes. The app layout loads it once the user is loaded, through
  `useHomeSession`; pages such as chat only read the store, so they send no extra request.
- `app/home/context.py` holds the current learner (`is_child`, native language) in a context variable.
  `get_current_user` sets it once per authenticated request through `enter_user`; the
  conversation WebSocket sets it where it resolves the user; background work uses `use_learner`.
  `LearnerScopeMiddleware` resets the variable to the default learner at the start of every HTTP or
  WebSocket request, so a request that resolves no user never sees a previous learner.
- A child learner is about 9 to 11 years old. `child_instruction()` is appended to the tutor, voice
  conversation, lesson generation and the three game generation prompts: simple words, a warm tone,
  everyday topics. Game review prompts do not receive it. Replaying a game uses the profile's current
  setting.

## Tagged replies and spoken lines

`tagged_replies_enabled(native_code, cefr_level, target_code)` in `spoken_lines.py` is true only for a
Swedish native speaker at CEFR A1 or A2 learning English or Spanish. When true the tutor and voice
prompts append `instruction_language_rules`, which overrides the target-language-only instruction.
The tutor writes one tagged item per line:

- `[sv]` (also the default for an untagged line): Swedish only, with no quoted target-language text
  and no English or Spanish words.
- `[en]` or `[es]`: a full target-language sentence.
- `[screen]`: text shown but never spoken.

The rules require 4 to 6 lines, the corrected sentence in a target line, and a closing question
followed by its Swedish meaning. Otherwise the instruction is empty and replies are not tagged.

- `parse_reply` parses lines, `invalid_swedish_lines` validates Swedish lines, and `display_text`
  removes tags. A Swedish line is invalid if it has quoted text, a word from a small English/Spanish
  list, or any of `ñ¿¡áíóú`.
- Voice: each spoken line is synthesized with its own ISO 639-1 language, so the gateway uses the
  matching reference voice. Screen lines are not synthesized. Transcripts and saved messages show
  text without tags; model history keeps the tags. An invalid Swedish line after audio has started
  moves to `[screen]` without rewriting. Before any audio, or for an empty reply, speech stops and one
  non-streaming rewrite pass corrects the reply; lines still invalid move to `[screen]`. An empty
  tagged reply is retried once, then fails as `llm_failed`.
- Written chat: `TaggedChatStream` (`app/home/chat.py`) hides tags while tokens stream and a final
  cleaned text replaces the stream; saved text has no tags. The chat page hides the per-message audio
  player when tagged replies apply, because a mixed-language text cannot be read aloud by one voice.
- When the LLM is unavailable the chat stream's error event carries `error_code: "llm_unavailable"`
  and the chat page shows the "Lingu is away" message instead of the generic error.

## Voice conversation additions

The home pipeline is `HomeConversationPipeline` (`app/home/conversation.py`), a subclass of upstream
`ConversationPipeline`, built by `build_pipeline`. `build_pipeline` reads the gateway tier once per
connection and enables the generated opener only when `LLM_PROVIDER=ollama` and the tier is not the
shared small LLM.

- Streaming: assistant text streams into TTS sentence by sentence, in order, while the LLM continues.
  A fragment longer than 140 characters is cut at clause punctuation (`, ; : -` followed by
  whitespace). Dots between digits and ellipses stay inside a fragment. Each audio fragment is
  followed by a `transcript` with `final: false` carrying the text spoken so far; the complete
  `final: true` transcript follows the last audio. A failed fragment is retried once. When the LLM
  adapter resets its stream, unspoken text is dropped and new text continues after what was played.
- Opener: each turn first generates a short opener (at most 24 tokens, 2 to 5 words reacting to the
  topic, without judgement, praise, correction or teaching, reasoning disabled), spoken at once; the
  reply continues it as a trailing assistant message. Tagged sessions request one `[sv]` line. If the
  opener fails or yields no audio the reply runs without it.
- Provisional turns: when the resolved end-of-turn pause exceeds 1000 ms, the browser sends the
  utterance so far after 800 ms of silence (`{"type":"provisional"}` then the WAV), provided no tutor
  turn is active and the usual filters pass. Resumed speech or a misfire sends `abort`; reaching the
  full pause sends `confirm` instead of audio. The backend runs the whole turn early but holds its
  effects in a `ProvisionalTurn` (`app/home/provisional_turn.py`): socket frames are buffered, memory
  saves are queued (the model is told they are queued), usage is held, and the user message stays out
  of history. `confirm` flushes frames in order, runs the queued saves and commits history and
  persistence; `abort` drops everything; `confirm` with nothing pending is ignored. A provisional
  frame arriving while another turn runs cancels that turn silently.
- Redo: after each user transcript the interface shows "Lingu heard:" with a "Try again" button under
  the latest learner bubble. It sends `client_event` with `event: "discard_last_turn"`, cancels
  playback and removes that bubble and everything after it. The backend cancels the running task,
  removes the last user and assistant entries from history and deletes their `ChatHistory` rows
  (assistant first). Awarded XP is kept. Without a finished turn the event does nothing.
- Control frames handled by `handle_control`: `provisional`, `confirm`, `abort` and
  `client_event/discard_last_turn`.
- The reasoning effort for the local LLM comes from `VOICE_REASONING_EFFORT`.
- `llm_adapter.chat` accepts `reasoning_effort` and `max_tokens`. `reasoning_effort` reaches only the
  local Ollama path (primary call, fallbacks, tool continuations). `max_tokens` applies to the
  OpenAI-compatible local path. A trailing prefilled assistant message is merged into the
  continuation's assistant message so roles keep alternating. A 503 from the local model is mapped
  to unavailable.
- `tts_service` adds an ISO 639-1 `language` field to the Kokoro-compatible request body when a
  language is supplied; the gateway requires it and stock Kokoro ignores it.

## Speech session

`/api/speech-session` (`app/home/speech_session.py`) proxies the gateway session lifecycle. Endpoints
require an authenticated user and return `{ "state": "off" | "switching" | "ready" | "busy" | "shared" | "away" }`
with HTTP 200.

- `POST /open` (30/min): requests a session; on the full GPU tier this asks the host to switch the LLM
  to speech mode.
- `POST /keepalive` (30/min): extends the session; the gateway releases it after ten idle minutes.
- `GET /status` (60/min): reports the state.

`away` means the gateway was unreachable, answered with an error or a bad body, or reported an
unknown state. When `STT_PROVIDER` is not `local` the state is always `ready`. Gateway calls use a
3-second timeout. `live_llm_is_small()` reports whether the state is `shared` (the small LLM tier).

Frontend: the app layout (through `useHomeSession`, which calls `useSpeechSession`) opens a session once the user is loaded, sends
a keepalive every 60 seconds while the tab is visible and on return to visibility, and reopens when
the stored state is missing, `off` or `away`. Voice can start only when the state is `ready` or
`shared` (`useCanStartVoice`); start buttons and topic buttons are disabled otherwise. The
conversation page shows a notice for `switching` ("getting ready"), `busy` ("busy for a moment") and
`away` ("no voice"); `busy` and `away` link to text chat. `ready`, `shared` and `off` show no notice.

## Game stock

Games are served from pre-generated stock in stock mode (see Settings). Stock lives in
`home_game_stock` (`HomeGameStock`) per study plan, mode and game type (a bucket).

- Columns: integer id; `study_plan_id` (FK to `study_plans`, cascade on delete); `mode`; `game_type`;
  `target_language`; `native_language`; `level`; `is_child`; `content` (JSON challenge list in the
  generated format, before per-play shuffling); `source_hash` (hash of permitted source IDs, empty for
  `free`); `created_at`; booleans `is_stale`, `replaced`, `counts_toward_cap`; nullable `taken_at`.
  Indexes: `study_plan_id` and `ix_home_game_stock_bucket` on `(study_plan_id, mode, game_type)`.
- An item is claimed by setting `taken_at` from null in an atomic update. The application never
  deletes rows, because daily-cap counting and first-fill detection read them.

Refill (`app/home/game_stock.py`):

- The application lifespan starts `stock_loop` only in stock mode and cancels it on shutdown. Each
  pass runs every ten minutes under a PostgreSQL advisory lock so one worker refills, uses its own
  database sessions, and never fails the application: a failed pass is logged and the loop continues.
- It generates only while the speech gateway reports `off` (the full model is free), rechecking before
  each game, and stops when a speech session starts. Each game has its own 600-second limit and no
  open database transaction while waiting.
- It covers active plans of active users. A bucket exists only when its mode has sources. Each bucket
  keeps up to three fresh items. Plans with no stock go first.
- Each plan generates at most three new games per UTC day (`counts_toward_cap`). A plan's first fill
  is the exception: one game per bucket, uncapped, counted toward that day's cap.
- Stock for `review` and `prepare` goes stale when the permitted source IDs change; `free` stock never
  goes stale. A stale item is replaced once; replacements do not count toward the cap. Surplus stale
  items in an already full bucket are marked replaced.
- The stock job runs as the item's learner (`use_learner`), so the child flag applies to generation.

Generation (home game prompts in `app/home/game_prompts.py`, schemas in `game_schemas.py`):

- The model writes eight draft items per game; `salvage_challenges` keeps the first five that are
  valid, distinct and cite an allowed source. Fewer than five valid items fails the attempt. Draft
  responses are validated leniently (1 to 16 raw items).
- Detective draft: `sentence` (exactly one error), `wrong_part` (copied exactly, occurring once,
  matched on word boundaries for spaced scripts), `correct_part`, two `wrong_options`, `explanation`,
  `source_id`. The app splits fragments, shuffles the three options and computes the indices.
- Sentence Order and Vocabulary Pairs drafts use the final challenge shape and are validated per item
  (Vocabulary Pairs needs five distinct nonempty terms and meanings; salvage deduplicates both).
- Items citing unpermitted sources or repeating a recent sentence are dropped. A separate structured
  LLM review checks validity, unique correction, language, level and source scope; at most two
  candidates are generated.

Serving (`POST /api/games/{game_type}` in stock mode):

- Nothing is generated on request. The response is 202 with a session (the request's existing
  session, the plan's active game of that type, or a new `ready` session built from stock).
- The oldest fresh item that does not repeat sentences of the plan's last five finished games is
  claimed atomically; repeating items are marked stale. Vocabulary Pairs are reshuffled and given
  per-play choice indices when served.
- The claim, session insert, request record and (for limited users) the consumed admission share one
  transaction. If another request wins the single active-game slot, the claim is undone and the
  winning game is returned.
- The free-tier quota is checked before stock is touched, so an exhausted limited user receives 402
  even when stock is empty. Stock-served games consume quota like generated ones.
- With no stock the response is 200 `{status: "empty", first_games_pending, replayable}`.
  `first_games_pending` is true when the plan has no completed game of that type yet; `replayable`
  lists up to five completed games, newest first, as `{id, mode, completed_at, score, total,
  xp_earned}`. An empty response stores no request, so the UUID stays reusable and uses no quota.
- The catalog shows the empty result as a friendly note with replay buttons (`StockEmptyNote`), not
  as an alert or paywall. Starting a replay clears the catalog's error alert, and catalog starts and
  other replays stay blocked while it runs and, after success, until the page navigates.

Replay: `POST /api/games/sessions/{id}/replay` (10/min, maintenance checked) requires an owned
`completed` session (otherwise 409 `game_not_completed`). It returns the plan's active game of that
type if one exists, otherwise a new `ready` session with the same content reshuffled where the game
shuffles and fresh answers. A replay uses no quota; XP follows the normal daily game cap.

## Home migrations

- Home tables (`home_profiles`, `home_game_stock`) have their own Alembic history in
  `backend/alembic_home/` with version table `alembic_version_home`. The home history never writes to
  upstream's `alembic_version`, and upstream's chain never contains home revisions.
- At startup upstream's migrations run first (upstream lifespan); `install_home` then upgrades the
  home history to head, before the stock loop starts. No deployment file changes are needed.
- Create a revision with `alembic -c alembic_home.ini revision` in `backend/`, and commit it. Home
  revisions may reference upstream tables by foreign key but must not alter them.
- Home models share upstream's SQLAlchemy `Base`, so that foreign keys to upstream tables resolve.
  Known caveat: an upstream `alembic revision --autogenerate` run in a process that imported
  `app.home` would propose creating the home tables. Do not autogenerate upstream revisions with home
  models imported.

## Speech gateway

`services/speech-gateway/` is a FastAPI service on port 8090 that acts as the local TTS and STT
provider and a stable LLM address for a single-GPU home host. The backend reaches it through the
unchanged Kokoro and Whisper adapters, with `TTS_BASE_URL`, `STT_BASE_URL` and `OLLAMA_BASE_URL`
pointing at it; the browser never calls it.

- `POST /asr` accepts the Whisper-ASR-compatible request (`audio_file`, `language`, `output`, `task`)
  and returns `{ "text", "spoken_language" }`. `language` is the explicit recognition language and
  must resolve to `en` or `es` (the learner's target); anything else returns 400. Unreadable audio
  returns 400; silent audio returns empty text without calling an engine.
- One-button routing: every clip is first transcribed by the always-on CPU Parakeet engine with the
  target language. A lingua detector (Swedish versus the target) decides `spoken_language`.
  Target-language speech is returned as is; Swedish speech is re-transcribed by Whisper with `sv`.
  `spoken_language` is informational and never replaces the plan language.
- Whisper runs in a child process; the model depends on the plan language and available VRAM (a CPU
  model on small GPUs, where it is not gated on the session). A GPU Whisper request while the session
  is not ready returns 503.
- `POST /v1/audio/speech` accepts `input`, a required `language` (`sv`, `en` or `es`; otherwise 400)
  and optional `voice`, `model`, `response_format`, and returns MP3. The OmniVoice engine clones one
  reference voice per language from `REFS_DIR` (`{lang}.wav` plus `refs.json`); a missing reference
  returns 503. Input is split into sentences, each synthesized, polished and joined with faint room
  tone. Out-of-memory is retried once, then 503. The `voice` field is ignored.
- `GET /v1/models` and `GET /` are health endpoints that do not depend on the LLM.
- Speech session: `POST /session/open`, `POST /session/keepalive` and `GET /session/status` return
  `{ "state" }` with one of `off`, `switching`, `ready`, `busy`, `shared`. On the full GPU tier,
  opening a session asks the host to switch from the LLM to speech mode, loads the GPU engines when
  ready, and releases them after ten minutes without keepalive; `busy` means the host refused the
  switch. `shared` means the GPU is shared with another workload, the small LLM tier is live, and GPU
  engines are held without switching. TTS requires `ready` or `shared`.
- `POST /v1/chat/completions` proxies to the live LLM tier read from `LLM_TIER_FILE`: `full` forwards
  to ninfer, `shared` to Ollama, rewriting only the model name.

Image: `services/speech-gateway/Dockerfile` builds from `python:3.12`, installs `ffmpeg`, creates a
separate virtual environment at `/opt/whisper-env` for the Whisper worker, runs the gateway unit tests
at build time, and serves `uvicorn gateway.app:build --factory` on port 8090. It is built separately
and run on the GPU host; the workflows do not publish it.

- `HF_HOME=/models/hf`; `REFS_DIR` (default `/models/refs`); mount `/models` persistently.
- `TORCHDYNAMO_DISABLE=1` and `PYTHONUNBUFFERED=1` are set in the image.
- `LLM_TIER_FILE` (default `/run/llm-tier`) names the boot-time tier file (`full` or `shared`); mount
  it read-only. A missing file means `full`.
- The session manager reads and writes `desired-mode` and `mode-state.json` in
  `/var/lib/speech-gateway`; the host script `deploy/ninfer-mode` applies the requested mode and
  refuses while the LLM is busy. On the shared tier it only reports `shared`.
- The container needs GPU access for the GPU engines; the gateway falls back to CPU Whisper on small
  GPUs.

## Hook points in upstream files

Every upstream file the fork still modifies, with the reason. Every hook line calls a function or
renders a component whose module path starts with `app.home` or `@/home`. Every backend and frontend
path below, including the non-hook `manifest.ts` change, is listed in `backend/app/home/SEAMS.md`.
`backend/tests/home/test_upstream_seams.py` pins the upstream signatures the home modules build on and
checks that the hook calls are still present in the upstream sources (by substring); a failure names
the seam or the missing hook.

Backend:

- `backend/app/main.py`: `install_home(app)` includes the home routers, adds the middleware and wraps
  the lifespan (home migrations, stock loop).
- `backend/app/core/deps.py`: `get_current_user` calls `enter_user` to set the current learner.
- `backend/app/routers/chat.py`: passes `target_code` to the prompt builders, filters streamed tokens
  through `TaggedChatStream`, and adds `error_code: "llm_unavailable"` to the error event.
- `backend/app/routers/conversation.py`: `enter_user` sets the learner for the socket and
  `build_pipeline(ConversationPipeline, ...)` constructs the home pipeline. Upstream's import stays,
  so upstream tests that patch `ConversationPipeline` in the router still work: `build_pipeline`
  calls a replaced class unchanged.
- `backend/app/routers/games.py`: returns `stock_empty_response` when the start returns no session.
- `backend/app/services/conversation_pipeline.py`: base seams whose bodies are the code they replaced,
  so upstream behaviour is unchanged. They are `_build_conversation_system_prompt(..., target_code)`
  (tagged prompt suffix), `_chat` (reasoning effort, opener, held memory tool calls, spoken stream),
  `_reply_text` (streamed text, tagged-line validation and rewrite), `_add_reply` (tagged history,
  provisional commit, redo tracking), `_record_usage` (hold usage while provisional),
  `_synthesize_chunk(text, language)` (per-line TTS language), `_tts_items` (replay tagged lines in
  their languages) and `handle_control(msg, ws) -> bool`, which runs in `run()` right after JSON
  decoding and does nothing in the base class; the home class handles control frames there, so
  upstream never imports home code.
- `backend/app/services/games.py`: `create_game` delegates to `start_from_stock` in stock mode and may
  return no session.
- `backend/app/services/llm_adapter.py`: reasoning effort, `max_tokens`, 503 as unavailable and the
  merged prefilled assistant turn. These run inside the tool-stream fallbacks and continuations, so no
  seam exists and a small patch stays.
- `backend/app/services/tts_service.py`: sends the language field. A subclass would copy
  `synthesize`, so a small patch stays.
- `backend/app/services/prompts/lesson.py`: appends the child suffix to the lesson prompt.
- `backend/app/services/prompts/tutor.py`: appends the tutor suffix (child instruction and tagged
  rules) to the tutor and voice prompts.

Frontend:

- `frontend/src/app/(app)/chat/page.tsx`: hides the per-message audio player when tagged replies apply and shows
  the "Lingu is away" message for `llm_unavailable`.
- `frontend/src/app/(app)/layout.tsx`: calls `useHomeSession` (speech session and home profile).
- `frontend/src/components/conversation/ConversationMode.tsx`: call sites for the provisional-turn
  hook, speech-session gating, the redo line and the status notice.
- `frontend/src/components/conversation/MicButton.tsx`: `canStart` prop from the speech-session state.
- `frontend/src/components/games/GameCatalog.tsx`: renders `StockEmptyNote` for an empty result.
- `frontend/src/components/settings/ProfileSection.tsx`: renders `ChildProfileToggle`.
- `frontend/src/i18n/request.ts`: merges `messages/home/<locale>.json` over upstream messages,
  falling back to the English home file for a missing locale or key. It passes the home import to
  `loadHomeMessages` next to its own messages import, so both resolve in the same layout (`/app` in
  the image); a missing English home file throws instead of rendering raw keys.
- `frontend/tests/components/ConversationMode.test.tsx`: the "sends the same detected voice" case
  accounts for provisional audio frames.
- `frontend/vitest.config.mts`: adds the home test setup file, which defaults the speech state to
  `ready`.
- `frontend/src/app/manifest.ts`: not a home hook. A PWA icon-size fix to the declared sizes.

`useProvisionalTurn(options)` (`frontend/src/home/hooks/useProvisionalTurn.ts`) takes `{ wsRef,
speechPause, cefrLevel, speechStartedAtRef, assistantTurnActiveRef, assistantSpeakingRef,
isLikelySpeech, logger }` and returns a stable object with `onFrame`, `onSpeechEnd`, `settle`,
`abort`, `reset` and `forget`.

## Footprint and upstream sync

`./scripts/home-surface.sh` prints the upstream-path files the branch modifies, adds or deletes
relative to the merge base with `upstream/main` (home-owned paths excluded), with added and removed
lines, and a total. It fails
with a clear message if the `upstream` remote or `upstream/main` is missing. `./scripts/home-surface.sh
--since <rev>` prints, for `<rev>..upstream/main`, the upstream commits that touch a path listed in
`SEAMS.md`, grouped by path, with a count.

Upstream sync checklist:

1. Run `./scripts/home-surface.sh --since <last synced upstream commit>` and read the listed commits.
2. Merge `upstream/main`.
3. Run `pytest tests/home` (including the seam tests), frontend `tsc`, and `vitest run tests/home`.
   Also run the upstream tests for every file with a conflict or a hook line: seam tests do not see
   upstream test fixtures that patch a name we replaced, or extra requests that a test's fetch mock
   does not expect.
4. By hand on the deployed app: one voice conversation as a child profile, and one game start.
5. Record the synced upstream commit below.

Last synced upstream commit: `59d53d2d284ebb9b6fdb4624e9626ec07322c253`

## Deployment rules

- Production runs from the owner's terranse Ansible template, not this repository's Compose file. The
  template must set `HOME_GAME_STOCK=true` for games to come from stock, and may set
  `VOICE_REASONING_EFFORT`.
- Before the first deploy of this layout the deployed database must be wiped and recreated: the earlier
  fork revisions `0058` to `0060` no longer exist, so the backend cannot start against a database
  stamped `0060`. The owner then re-creates the accounts.
- Do not apply migrations to a real database from a workstation; deployment applies upstream's and
  home migrations at startup.
- `CHANGELOG.md` is upstream's; the fork adds no entries.
