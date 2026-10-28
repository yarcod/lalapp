---
description: "Lalapp fork extensions: package boundary, upstream hook rule, migration branch, and the learner model."
applyTo: "backend/app/lalapp/**, backend/tests/lalapp/**, backend/alembic/versions/l*.py"
---

# Lalapp Extensions

Lalapp is a long-lived fork of FreeLingo. This spec describes current behavior only.

## Boundary and upstream hooks

- Lalapp code lives in `backend/app/lalapp/`, with tests in `backend/tests/lalapp/`.
- Upstream files carry only minimal calls into the package. Each such line is marked
  `# lalapp-hook`, so `git grep lalapp-hook` lists the complete footprint on upstream code.
- Lalapp adds its own tables (prefixed `lalapp_`) and never adds columns to upstream tables.
- Lalapp settings use the `LALAPP_` environment prefix (`app/lalapp/config.py`) and are read only by
  the package.
- Current hooks:
  - `main.py`: registers the Lalapp router and upgrades Alembic to `heads`.
  - `routers/lessons.py`: after a lesson exercise answer is scored and committed.
  - `routers/flashcards.py`: after a flashcard review is committed (not on idempotent replays).
  - `routers/listening.py` and `routers/reading.py`: after a comprehension attempt is committed.
  - `routers/games.py`: after a newly persisted game answer.
  - `routers/chat.py` and `services/conversation_pipeline.py`: their tutor-prompt wrappers pass the
    upstream prompt through `personas.service.apply`; `chat` activates the conversation's character
    before building prompts.
  - `routers/conversation.py`: before creating the voice pipeline, activates the conversation's
    character and uses its TTS voice instead of the client's voice preference.
  - `frontend/src/app/(app)/assessment/page.tsx`: when `NEXT_PUBLIC_LALAPP_PLACEMENT` is not
    `false`, starting the quiz renders `LalappPlacementQuiz` instead of the client-side staircase.
    Its result feeds upstream's result, duration and plan-creation steps unchanged.
  - `frontend/src/app/(app)/settings/page.tsx`: renders `PersonaSection` (choice of conversation
    partner) next to the voice settings.
  - `frontend/src/app/(app)/chat/page.tsx`: renders `ConversationPersona` in the chat header. It shows
    the preferred partner for a new conversation, for an existing one a selector to switch
    character, and for a scene only the NPC's name. It renders `ScenarioPanel` (a scene's goals,
    checked after each finished reply) below the header, and on load it opens the conversation
    named by `?conversation=` when it is among the user's conversations.
  - `frontend/src/app/(app)/scenarios/page.tsx`: a new route rendering `ScenarioList`.
    `frontend/src/app/(app)/layout.tsx` adds its navigation entry through `useLalappNavItems`, and
    `frontend/src/middleware.ts` lists it as a protected route.
  - `frontend/src/app/(app)/dashboard/page.tsx`: renders `LalappDashboard` after today's lessons: the
    adaptive next lesson with the level-up offer, and the rhythm card.
  - `frontend/vitest.config.mts`: upstream's tests run with Lalapp frontend features switched off
    (`NEXT_PUBLIC_LALAPP_PLACEMENT`, `NEXT_PUBLIC_LALAPP_PERSONAS`, `NEXT_PUBLIC_LALAPP_ADAPTIVE`,
    `NEXT_PUBLIC_LALAPP_SCENARIOS`, `NEXT_PUBLIC_LALAPP_RHYTHM`). Lalapp frontend tests live in
    `frontend/tests/lalapp/` and enable features explicitly.
- Lalapp interface strings live in `frontend/src/lalapp/i18n.ts` (English, Swedish, Spanish; other
  interface languages fall back to English) rather than in upstream's message catalogs.

## Migrations

- Lalapp revisions form a separate Alembic branch labelled `lalapp`, with ids prefixed `l` (for
  example `l0001_lalapp_learner_model`).
- The branch base depends on the upstream revision whose tables it references, so upstream's linear
  `00NN_` chain stays untouched.
- Startup runs `alembic upgrade heads` so both branches are applied: in `main.py`, and in the backend
  `command` of `docker-compose.yml` and `docker-compose.dev.yml` (`lalapp-hook` comments). A plain
  `upgrade head` fails with more than one head.
- `docker-compose.lalapp.yml` is an override for `docker-compose.yml` that builds the backend and
  frontend from this repository instead of pulling upstream's published images, which lack Lalapp:
  `docker compose -f docker-compose.yml -f docker-compose.lalapp.yml up -d --build`.
- Upstream's migration tests that assert a single head ignore `l0` revisions (`lalapp-hook` lines in
  `tests/test_progress_migration.py`, `test_flashcard_receipt_migration.py`,
  `test_flashcard_management_migration.py` and `test_sentence_order_migration.py`). The lalapp
  branch has its own offline checks in `tests/lalapp/test_migrations.py`: one linear chain on top of
  upstream, DDL for every `lalapp_` table and index matching the models, and a downgrade that drops
  every table.

## Learner model

- The learner model records estimates from every scored activity. Its estimates drive only Lalapp
  features (adaptive next lesson, level-up offer); upstream's day grid and level test are unchanged.
  `LALAPP_LEARNER_MODEL_ENABLED` (default `true`) turns recording off.
- Each scored response is a match between a learner skill and an item on a logistic (Rasch) scale,
  with `P(success) = sigmoid(theta - difficulty)`.
  - Both sides keep a standard deviation. Each update is a single Laplace step whose size equals the
    posterior variance, so estimates move quickly while uncertain and settle as evidence accumulates.
  - The other side's uncertainty discounts the update (Glicko-style).
  - Learner uncertainty grows slowly with time since the last response.
  - Partial scores in `[0, 1]` are used directly.
- CEFR item difficulties are anchored at A1 -2.5, A2 -1.5, B1 -0.5, B2 0.5, C1 1.5 and C2 2.5. A
  learner is at a level when the expected success on that level's typical items is at least 70%.
  The initial learner estimate for a skill is the active plan's CEFR level under that rule.
- Skills: vocabulary, grammar, reading, listening, speaking, writing.
- Evidence sources and mapping:
  - Lesson exercises: free writing maps to writing and pronunciation to speaking; other exercises
    use the lesson type, with review lessons counted as grammar.
  - Listening and reading attempts: the fraction of correct questions. Replays are skipped.
  - Games: Error Detective and Sentence Order count as grammar, Vocabulary Pairs as vocabulary.
  - Flashcard reviews: vocabulary, with quality divided by 5.
- Item difficulty is pooled per item template, because upstream exercises are generated and have no
  stable identity. Keys combine language, source, exercise type, CEFR level and, for lessons, the
  first grammar slug.

## Adaptive placement

- Placement is a computerised adaptive test over upstream's static assessment bank
  (`get_assessment_bank`), scored on the server. The correct option never leaves the server.
- Each answer updates an overall estimate and the estimate for the item's skill, using the same
  rating update as the learner model. Bank items are rated under `bank:{language}:{item_id}` with a
  prior of their CEFR label at standard deviation 0.5, so placements also calibrate the bank.
- Question selection: take the least-tested skill that still has unasked items, rank its items by how
  close the expected success is to 50%, and pick randomly among the best three.
- Start: centred on B1 mastery with standard deviation 2.0, or on an optional self-assessed level
  with standard deviation 1.0.
- Stop: after at least 10 questions once the overall standard deviation is below 0.45, after 25
  questions, or when the bank is exhausted.
- `__dont_know__` (upstream's quiz-card sentinel) scores 0 and is recorded as a declared gap.
- The result uses upstream's `AssessmentResult` shape:
  - `cefr_level` comes from the overall estimate.
  - `score` is the expected success on typical items of that level.
  - `skill_profile` measures each skill relative to the overall estimate, with 0.55 meaning on par.
  - Strengths and weaknesses use upstream's 0.65 and 0.45 thresholds; a skill where at least half
    the answers were declared gaps is also a weakness.
  - It additionally carries `theta`, `theta_sd` and `questions_answered`.
- A finished placement replaces the learner-model estimates for that language. Skills the text bank
  cannot measure (listening, speaking, writing) take the overall estimate with a standard deviation
  of at least 0.8. If the user has no `user_languages` row yet, the stored result seeds the skill
  rows when they are first created. Otherwise new rows start from the active plan's level.

## Personas

- Characters and roles are Python modules in `app/lalapp/personas/`. Personas hold voice,
  background and personality (`cast_en.py`, `cast_es.py`); roles hold pedagogical behaviour
  (`roles.py`). Each carries a `version`.
- Launch cast per target-language family (`en`, `es`): a bilingual Swedish-speaking guide, two
  conversation partners in different dialects (en-GB and en-US; es-ES and es-MX), and an examiner.
  The examiner is not selectable for conversations.
- Each persona maps to a TTS voice per provider (`openai`, `local`). Humour varies by learner level.
- Prompt composition keeps upstream's prompt (mandatory rules, student context, memories, language
  overlay). It replaces the identity line and the upstream tutor name, then appends:
  - a character block;
  - a role block, including the native-language policy;
  - an honesty block (an AI-voiced fictional character; never claims to be human, never flirts,
    never guilt-trips);
  - a precedence note: the character and role instructions override the earlier guidelines but
    never the mandatory rules.
  If upstream's identity line changes, the identity is prepended instead.
- Conversation character:
  - It is fixed per conversation in `lalapp_conversation_personas` when the conversation is first
    used.
  - It defaults to the learner's preferred partner for that language, otherwise the partner whose
    dialect matches the target language, otherwise the first partner.
  - The learner can switch a conversation to any selectable character of its language.
- The active character is held in a context variable for the request or voice session. Prompts
  built without an activated character are left unchanged, and activation failures fall back to
  upstream's tutor.
- `LALAPP_PERSONAS_ENABLED` (default `true`) turns characters off.
- Roles are `guide`, `peer`, `examiner` and `npc`; only peers are selectable as partners.
- Upstream's Lingu remains the app mascot in the interface.

## Adaptive next lesson and level-up

- The selector (`app/lalapp/adaptive/selector.py`) is pure; the service reads its inputs from the
  learner model, the response log, the item ratings and the plan's curriculum.
- Skill: among the plan's goal skills (all lesson skills when none match), the one with the highest
  priority. Priority is the gap between plan-level mastery and the skill estimate, plus 0.5 times its
  standard deviation, minus 0.4 when it was the skill of the plan's previous adaptive lesson. A skill
  without a row counts as the plan-level prior.
- Lesson level: the plan level. It steps down one level when the predicted success there is below
  55%, and up one level when the predicted success one level higher is at least 75%.
  - Predicted success uses the calibrated difficulty of generated lessons of that type and level:
    the evidence-weighted mean of the matching lesson template ratings, shrunk toward the CEFR
    anchor with a weight of 10 responses. Without ratings, the anchor is used.
- Content:
  - For grammar and writing, a weak grammar point is reviewed first. A point is weak with at least 3
    recent lesson responses and a posterior mean below 60% (a Beta prior worth 2 responses at 70%).
    Only points of units up to the current unit count, weakest first.
  - Grammar more than 0.5 above plan-level mastery, after subtracting one standard deviation,
    previews the next unit.
  - Otherwise the lesson practises the current unit: the unit of the plan's current day, else the
    plan's `current_unit`, else the first unit.
- Generation calls upstream's `generate_lesson` with the chosen level, the skill as lesson type, the
  unit's title, vocabulary sets and the focus grammar points, and the unit's existing lessons as
  history.
- Adaptive lessons are ordinary `lessons` rows with `week_number` 1000 and `day_number` numbering
  them within the plan. They are therefore never part of the day grid, today's lessons, pending
  lessons or the level-test gate, but completing one counts for progress, streaks and unit
  competency like any lesson.
- A plan has at most one open adaptive lesson. Requesting the next lesson while one is open returns
  it instead of generating another.
- Level-up is offered when at least two of the plan's goal skills have 20 or more responses, and
  every goal skill with that much evidence is above mastery of the next level by one standard
  deviation. There is no offer at C2. Accepting it creates a plan at the next level through
  upstream's `POST /api/study-plan/generate`, with the current plan's goals, duration and days per
  week. Skill estimates carry over because they belong to the user language.
- `LALAPP_ADAPTIVE_ENABLED` (default `true`) turns the API off; `NEXT_PUBLIC_LALAPP_ADAPTIVE=false`
  hides the dashboard card.

## Role-play scenarios

- Scenes are Python modules per target-language family (`app/lalapp/scenarios/catalog_en.py`,
  `catalog_es.py`), each with a `version`. A scene has:
  - one NPC: a persona with role `npc`, not selectable as a partner;
  - a setting and the NPC's own goal (English, for the prompt);
  - a title in the target language (the conversation title), a summary per interface language
    (`en`, `sv`, `es`), and the NPC's opening line;
  - two or three missions: a learner-facing goal per interface language and an English rubric for
    the judge.
- Scenes belong to story arcs with recurring NPCs and are numbered from 1 within the arc. A scene
  is locked until the previous scene of its arc is completed; its CEFR level is advisory. A scene
  whose latest run is still active (including a replay of a completed scene) is listed as
  `active`.
- Starting a scene creates an ordinary upstream conversation titled after the scene, with the
  NPC's opening line stored as its first assistant message, and a run in `lalapp_scenario_runs`.
  Starting again creates a new run; completion is kept per run, so it survives deleting the
  conversation.
- In a scene's conversation, persona activation uses the NPC and appends a scene block after the
  role block. The block lists the setting, the NPC's goal and the learner's open goals. It tells
  the NPC to create chances without doing the work, to close the scene once all goals are
  reached, and that the scene is an app instruction while the persona lock still applies to
  learner requests. The conversation's character cannot be switched.
- Mission judge:
  - It runs on request, only when the learner has written since the last check, and only for
    open missions.
  - It sees the last 40 messages and must quote, for each achieved goal, an excerpt of a learner
    message. A goal counts only if the quote, with case, accents and punctuation folded, occurs
    in what the learner wrote. Quotes shorter than three characters never count.
  - When every mission has evidence, the run is `done` and the next scene of the arc unlocks.
- `LALAPP_SCENARIOS_ENABLED` (default `true`) turns the API off; existing scene conversations then
  fall back to the preferred partner. `NEXT_PUBLIC_LALAPP_SCENARIOS=false` hides the page, its
  navigation entry and the chat panel.

## Rhythm, turns and milestones

- Instead of a daily streak, the learner sets a weekly goal of active days (1 to 7, default 3) per
  language. Upstream's streak and XP are unchanged.
- An active day (UTC, like upstream's progress) has any learner-model response or any learner
  message in the language's conversations (chat or voice).
- Each week runs Monday to Sunday and is judged on its own. The summary shows this week's active
  days and how many of the last 8 completed weeks met the current goal. Nothing is framed as a
  loss.
- Turns are the learner's own messages in the language's conversations. A stretch turn this week
  has more words than the median of the previous 4 weeks' turns, counted only with at least 10
  earlier turns.
- Milestones are informational firsts, each recorded once per language and shown until dismissed:
  - `turns:{n}` when the total number of turns reaches 25, 100, 500, 1000 or 5000 (only the
    highest level reached is recorded);
  - `skill_level:{skill}:{level}` when a skill with at least 10 responses is estimated above the
    plan's level, once per level;
  - `scene_done:{scenario}` when a scene is completed.
- `LALAPP_RHYTHM_ENABLED` (default `true`) turns the API off; `NEXT_PUBLIC_LALAPP_RHYTHM=false`
  hides the card. Milestones are recorded either way.

## Persistence

- `lalapp_learner_skills`: one row per user language and skill. It is owned by `user_languages`, not
  by a study plan, so estimates survive plan changes and deletion.
- `lalapp_item_ratings`: difficulty and uncertainty per item key.
- `lalapp_placement_sessions`: per-user placement state (estimates, asked items, responses), the
  pending question id, status `active` or `done`, and the result.
- `lalapp_conversation_personas`: the character and its version per conversation, cascading with
  the conversation.
- `lalapp_language_preferences`: per user language, the chosen conversation partner.
- `lalapp_adaptive_lessons`: per adaptive lesson, the plan, skill, level, unit, focus grammar points,
  reason (`practice`, `review` or `preview`) and predicted success, so predictions can be checked
  against outcomes. It cascades with the lesson and the plan.
- `lalapp_scenario_runs`: per scene attempt, the user language, the conversation (set to null when
  the conversation is deleted), scene id and version, status `active` or `done`, mission evidence
  (mission id to quote), and the last judged learner message.
- `lalapp_rhythm_goals`: per user language, the weekly goal of active days.
- `lalapp_milestones`: per user language, unique milestone keys with display data, creation time
  and when they were dismissed.
- `lalapp_learner_responses`: an append-only log of every response, with the expected score and the
  estimates before the update, so ratings can be refitted offline.

## Failure behavior

Hooks run after the caller has committed. The learner update uses its own session on the caller's
engine, so a failure is logged and discarded. It never fails the request or expires the caller's
loaded objects.

## API

- `POST /api/lalapp/placement/start` (authenticated, 10/minute) takes `language` (a supported target
  language) and an optional `self_level`. It returns a step: `session_id`, `question_number`,
  `max_questions`, `question` (id, skill, difficulty, question, options) and `result`.
- `POST /api/lalapp/placement/{session_id}/answer` (authenticated, 60/minute) takes `question_id` and
  `answer` and returns the next step. When finished, `question` is null and `result` is set. A
  foreign or unknown session returns 404. An answer to a question that is not pending, or to a
  finished session, returns 409.
- `GET /api/lalapp/personas` (60/minute) returns the active language's selectable characters and
  `preferred_peer_id`. `PUT /api/lalapp/personas/peer` (20/minute) sets the preferred partner and
  returns 422 for anything other than a partner of the active language.
- `GET` and `PUT /api/lalapp/conversations/{id}/persona` (60/minute and 20/minute) read or switch a
  conversation's character. Foreign conversations and unavailable characters return 404.
- `GET /api/lalapp/next` (60/minute) returns null without an active plan. Otherwise it returns the
  current suggestion (`skill`, `cefr_level`, `reason`, `focus`, `unit_title`,
  `predicted_success`), the open adaptive `lesson` if any, and `level_up` (`next_level` and the
  current plan's goals, duration, days per week and target language) when earned. It generates
  nothing.
- `POST /api/lalapp/next` (10/minute) generates the suggested lesson, or keeps the open one, and
  returns the same shape. It returns 503 when generation fails and 404 without an active plan.
  Both return 404 when `LALAPP_ADAPTIVE_ENABLED` is off.
- `GET /api/lalapp/scenarios` (60/minute) lists the active language's scenes with `status`
  (`locked`, `available`, `active` or `done`), the latest run's conversation, the NPC, and missions
  with `done` flags, plus `plan_level`.
- `POST /api/lalapp/scenarios/{id}/start` (10/minute) returns the new run. Scenes of another
  language or unknown ids return 404, and locked scenes 409.
- `GET /api/lalapp/scenarios/runs/{conversation_id}` (60/minute) returns a run's state, and
  `POST .../check` (30/minute) judges it and also returns `newly_done`. Conversations that are not
  the user's scenes return 404, and a failed judgement 503.
- `GET /api/lalapp/rhythm` (60/minute) returns `days_per_week`, `week_start`, this week's
  `active_days`, `weeks_kept` of `weeks_counted`, `turns_this_week`, `stretch_turns_this_week` and
  undismissed `milestones` (`id`, `key`, `data`, `created_at`). `PUT /api/lalapp/rhythm`
  (20/minute) sets `days_per_week` (1 to 7, otherwise 422) and returns the same.
  `POST /api/lalapp/milestones/{id}/seen` (60/minute) dismisses a milestone (204, or 404 for
  another user's or an unknown one).
- `GET /api/lalapp/learner` (authenticated, 30/minute) returns the current user's skill estimates per
  target language: `skill`, `theta`, `theta_sd`, the derived `cefr` level, and the response count `n`.
