# Design 01: Personas and Adaptive Learner Model

*Status: proposal, 2026-10-21. Builds on research-01 and research-02. Line references are to
upstream FreeLingo v1.10.50.*

## Guiding principle: stay mergeable with upstream

Lalapp is a long-lived fork. Every edit to an upstream file is a future merge conflict, so:

- **Our code lives in our own package**, `backend/app/lalapp/`, with its own routers,
  services, models, data and tests (`backend/tests/lalapp/`).
  - The frontend equivalents are `frontend/src/lalapp/` and new routes under
    `frontend/src/app/(app)/lalapp/`.
- **Upstream files get only hook lines.** These are one- or two-line calls into our package,
  each tagged `# lalapp-hook`, so `git grep lalapp-hook` lists our whole footprint.
  - Hooks must be no-ops when our feature is off.
- **New tables only.** We never add columns to upstream tables. Anything we need to link to
  upstream rows goes in our own tables with foreign keys to theirs.
- **Our migrations are a separate Alembic branch**, using `branch_labels=("lalapp",)` and their
  own revision ids (`l0001_…`).
  - This avoids fighting upstream's linear `00NN_` chain.
  - The startup upgrade in `backend/app/main.py:63` must change from `"head"` to `"heads"`.
    That is a one-word hook.
- **Our own spec**, `specs/lalapp.instructions.md`. Upstream specs are left untouched unless
  a hook changes behaviour that they describe.
- **Feature flags** in our own settings class (`LALAPP_*` env vars), read only by our package.

## Part A: Learner model (θ)

### What exists upstream
- **Placement:** a client-side staircase (`assessment/page.tsx`): 15 questions, start at A2,
  move after 2 answers in a row.
  - The **client decides correctness**, and `/evaluate` trusts it.
  - Only `StudyPlan.cefr_level` is persisted; the skill profile is discarded.
- **Skill scores:** a per-day exponential moving average (`0.7·old + 0.3·new`), keyed by
  lesson type.
  - Listening, reading and games never update skills.
- **Plan-owned rows:** all per-plan rows cascade from `study_plan_id`, so anything stored per
  plan is lost when a new plan is created.

### Our model
**Storage (new tables).** Both ratings use Glicko-style (rating, deviation) pairs:
- `lalapp_learner_skill(user_language_id, skill, theta, theta_sd, n, updated_at)`.
  - Skills are `vocabulary`, `grammar`, `reading`, `listening`, `speaking`, `writing`.
  - Keyed to `user_language_id`, not the study plan, so it **survives plan changes**.
- `lalapp_item_rating(item_key, target_language, difficulty, difficulty_sd, n)`.
- `lalapp_response(id, user_language_id, item_key, skill, score, expected, theta_before,
  source, created_at)`: an append-only log, so ratings can be refitted later.

**Rating scale.** A logit scale with CEFR anchors at A1 = −2.5, A2 = −1.5, B1 = −0.5,
B2 = 0.5, C1 = 1.5, C2 = 2.5.
- P(correct) = σ(θ − b).
- Partial scores (0–1, from LLM grading) are used directly as the observed value.

**Update rule.**
- θ ← θ + K·(observed − expected), where K shrinks with θ_sd. This is the "PID damping".
- Each item's difficulty b is updated the same way, with its own uncertainty.

**Item keys.** Upstream exercises have no stable ids, so difficulty is pooled per template:
- Assessment bank items use their own id, e.g. `bank:es:g-a1-001`.
- Generated exercises use
  `tpl:{lang}:{lesson_type}:{exercise_type}:{cefr}:{grammar_slug or '-'}`.
- Listening, reading and games use
  `tpl:{lang}:{kind}:{exercise_type or game_type}:{level}`.
- Flashcards use `vocab:{lang}:{cefr of the set}`. FSRS/SM-2 stays in charge of review
  timing; θ only gets the evidence.

**Hook points.** One call each to `lalapp.learner.record_response(...)`, best-effort: a
failure is logged and never fails the request.
- `routers/lessons.py`, after `update_daily_progress`, around line 565.
- `routers/flashcards.py`, review, around line 290.
- `services/listening_service.py` and `services/reading_service.py`, in `submit_attempt`.
- `services/games.py`, in `answer_game`.

**Rollout.**
1. **Shadow mode first.** θ is recorded and shown on an admin/debug endpoint but changes
   nothing users see. This lets us check that the estimates converge sensibly before
   anything depends on them (Duolingo ran Birdbrain this way).

### Placement (computerised adaptive test)
- **New router `/api/lalapp/placement`, scored server-side.** The client never receives the
  answer key.
- **Item selection:** maximum information, i.e. P(correct) ≈ 0.5 against the current θ.
- **Item sources:**
  - **Text items** are upstream's bank (about 120–180 items per language), read through
    their `get_assessment_bank()` without modifying it.
  - **Spoken placement:** later, an optional free-production turn with the Examiner persona,
    scored by an LLM rubric.
- **Stopping rule:** stop when θ_sd < 0.35, after at least 8 and at most 25 items.
- **Start point:** the prior comes from a one-tap self-assessment ("I can…" statements in
  Swedish), which shortens the test.
- **Output:** the CEFR band and the per-skill θ. These are written to our tables, and the
  study plan is then created through upstream's existing `/api/assessment/complete`, so
  their plan flow still works.
- **Frontend:** a new page `/lalapp/placement`. One hook redirects the onboarding link from
  `/assessment` to it while the flag is on.
- Upstream's page stays intact.

### Adaptive activity selection (later phase)
- Replaces "what is today's slot" with "what should this learner do next".
- **Candidate pool:**
  - skills whose θ is low relative to the plan's CEFR target;
  - grammar slugs from the unit graph that are not yet mastered;
  - items due in FSRS.
- **Choice:** target P(success) ≈ 0.75–0.85, then generate the lesson to that specification
  using upstream's lesson generator.
- **Integration:** our own `/api/lalapp/next` endpoint and a "Next up" card.
  - Upstream's day-grid keeps working, so the two can coexist during migration.
- **Level-up:** happens automatically when θ for the target band is confidently reached.
  - This replaces the manual "advance" step that upstream never automated.

## Part B: Personas

### What exists upstream
- **Single persona:**
  - `TUTOR_DISPLAY_NAME = "Lingu"` (`prompts/common.py:23`).
  - Two f-string prompt builders (`prompts/tutor.py`): text at line 35 and voice at line
    100. Both contain a "PERSONA LOCK".
- **Prompt builders are called in two places:**
  - `routers/chat.py`, in `_build_tutor_system_prompt`, around lines 57–84.
  - `services/conversation_pipeline.py`, in its wrapper, around lines 48–70.
- **Voice is chosen client-side**, from localStorage `tts_voice`, and sent in the WebSocket
  auth message.
  - Allowed voices are listed in three separate places.
- **Lingu in the frontend:** the name and 3D avatar are hard-wired across about 8 components
  and about 53 strings per locale.
- **Per-dialect guidance already exists** in `_LANGUAGE_PROMPT_OVERLAYS` (en-GB, en-US,
  es-ES, …). We reuse it.

### Our model
**Persona files.** `backend/app/lalapp/personas/<lang>/<id>.yaml` holds the persona layer:
- name, age, dialect, backstory, personality, level-dependent knobs, sample lines;
- `tts_voice` for each speech provider;
- `version`.

**Role files.** `backend/app/lalapp/roles/<id>.yaml` holds the role layer:
- `guide`, `peer`, `examiner`, `npc`;
- explicit pedagogical rules, and whether Swedish may be used.

**Prompt composer.** `lalapp.personas.compose_system_prompt(persona, role, base_prompt)`:
- Takes upstream's prompt (its rules, memories, progress and overlay are all still useful).
- Swaps the identity line and persona lock for ours.
- Appends a role block and a compact reminder placed after the chat history, against
  persona drift.
- Works as a wrapper over upstream's output, so their builders stay untouched.

**Storage (new tables).**
- `lalapp_conversation_persona(conversation_id PK/FK, persona_id, persona_version)`.
- `lalapp_language_prefs(user_language_id PK/FK, peer_persona_id)`.

**Hook points.**
- `chat.py` and `conversation_pipeline.py` prompt wrappers: one line each to pass the
  upstream prompt through our composer.
- `conversation_pipeline.py:289`: one line letting the persona override the TTS voice.
- `routers/conversation.py`: the WebSocket auth message accepts an optional `persona_id`
  (about 2 lines).
- A `chat` request field for `persona_id`. To avoid touching their schema, this goes through
  our own endpoint `/api/lalapp/chat/persona` instead, which sets it per conversation.

**Frontend.** Kept minimal at first:
- a persona picker (two peers) on our own settings card;
- the persona's name shown in chat and voice headers through one hook component.

**Launch cast.**
- **es:** Guide (bilingual, Swedish-speaking), Peer es-ES, Peer es-MX, Examiner.
- **en:** Guide, Peer en-GB, Peer en-US, Examiner.
- **NPCs:** generated from a scenario template (a later phase).

## Phasing

| Phase | Content | Upstream hooks |
|---|---|---|
| 0 | `app/lalapp` package skeleton, settings, Alembic branch, `head`→`heads`, router registration | `main.py` (2 lines) |
| 1 | Learner model in shadow mode: tables, Elo/Glicko, response hooks, debug endpoint | 5 call sites |
| 2 | CAT placement: backend and new frontend page, onboarding redirect | 1 frontend link |
| 3 | Personas: YAML, composer, 8 core personas, voice override, picker | ~5 lines over 3 files, plus 1 frontend component |
| 4 | Adaptive "next activity" selector and auto level-up | new endpoint, dashboard card hook |
| 5 | Scenario NPCs, missions, gamification changes | — |

## Open decisions
1. **Persona file format:** YAML (needs PyYAML, a new dependency), JSON (stdlib), or Python
   modules (matches upstream's `app/data` pattern).
2. **Lingu:** keep it as the app's mascot and brand with the new characters alongside, or
   retire it?
   - Retiring it touches about 8 upstream components and about 53 strings per locale, which
     means heavy conflicts.
3. **Order:** learner model first (it is the foundation) or personas first (the more visible
   win)?
