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
  - `frontend/src/app/(app)/assessment/page.tsx`: when `NEXT_PUBLIC_LALAPP_PLACEMENT` is not
    `false`, starting the quiz renders `LalappPlacementQuiz` instead of the client-side staircase.
    Its result feeds upstream's result, duration and plan-creation steps unchanged.

## Migrations

- Lalapp revisions form a separate Alembic branch labelled `lalapp`, with ids prefixed `l` (for
  example `l0001_lalapp_learner_model`).
- The branch base depends on the upstream revision whose tables it references, so upstream's linear
  `00NN_` chain stays untouched.
- Startup runs `alembic upgrade heads` so both branches are applied.

## Learner model

- The learner model runs in shadow mode: it records estimates but does not change user-facing
  behavior. `LALAPP_LEARNER_MODEL_ENABLED` (default `true`) turns recording off.
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

## Persistence

- `lalapp_learner_skills`: one row per user language and skill. It is owned by `user_languages`, not
  by a study plan, so estimates survive plan changes and deletion.
- `lalapp_item_ratings`: difficulty and uncertainty per item key.
- `lalapp_placement_sessions`: per-user placement state (estimates, asked items, responses), the
  pending question id, status `active` or `done`, and the result.
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
- `GET /api/lalapp/learner` (authenticated, 30/minute) returns the current user's skill estimates per
  target language: `skill`, `theta`, `theta_sd`, the derived `cefr` level, and the response count `n`.
