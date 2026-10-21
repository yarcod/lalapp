# Research 02: Build vs. Fork, Gamification, Persona Cast

*Status: research notes, 2026-10-21. Follows `research-01`.*

Source labels:
- **[E]** evidence: peer-reviewed or published data.
- **[C]** company claim.
- **[O]** our opinion.

FreeLingo and OpenLingo were audited by reading their code only (shallow clones; nothing
was run). Key claims were spot-checked by hand.

## TL;DR

- **Nothing in FOSS is a "measurably good and appreciated" LLM tutor.** None has published
  learning outcomes, and none has a large, verifiable user base.
  - Only the non-LLM building blocks clearly clear that bar: Anki (32k★), FSRS (4k★),
    Lute v3 and LinguaCafe.
  - The *approach* is supported: meta-analyses of chatbot L2 practice show g ≈ 0.5–0.6,
    with high heterogeneity [E].
- **FreeLingo is the best base. Recommendation: fork it.**
  - It already supports **Swedish as L1**: a full Swedish UI, and explanations in Swedish.
  - It covers en-GB/en-US/es-ES targets, CEFR placement, Ollama, local voice, XP and
    streaks, tests and CI.
  - It is AGPL, the same as us.
  - Gap to our vision: about **6–9 developer-weeks**. Most of that is replacing its
    curriculum day-grid with an Elo/IRT learner model and procedural lesson selection.
- **OpenLingo: borrow parts only (MIT).**
  - Its exercise widgets and markdown exercise format are worth taking.
  - It has no i18n, English-only glosses, no placement, 2 test files and no CI.
  - It has an unsafe LLM-written-SQL tool.
  - It has not been pushed since 2026-05.
- **Gamification:** reward *conversation* rather than taps. Use forgiving, self-set streaks,
  missions inside role-plays and narrative progression with recurring characters. **Avoid**
  energy/hearts, default competitive leagues and guilt messaging.
- **Cast:** **4 fixed-role characters per target language**:
  - a bilingual Swedish-speaking Guide;
  - 2 conversation peers in different dialects (the learner picks one);
  - an Examiner.

  Generated scenario NPCs come on top of that. Don't launch with a 10-character roster.

---

## 1. FreeLingo vs. OpenLingo (code audit)

| | **FreeLingo** (artcc/freelingo) | **OpenLingo** (pretzelai/openlingo) |
|---|---|---|
| Licence | AGPL-3.0 + CLA (owner may relicense commercially) + paid hosted tier | MIT |
| Activity | v1.10.50, daily releases, last commit 2026-10-21 | v0.1.0, last commit 2026-05-15 |
| Popularity | ~196★, 50 forks, effectively single author | ~90★, 24 forks, single author |
| Stack | FastAPI + SQLAlchemy/Alembic + Postgres + Redis; Next.js 16 | Next.js 16 + Bun + Drizzle/Postgres; Vercel AI SDK 6. Two parallel rewrites in progress (Rust, Cloudflare) |
| Size / tests | ~24k LOC backend logic + ~200k LOC of curriculum data; ~37k LOC frontend; 78 backend + 104 frontend test files; CI | ~22k LOC TS; 2 test files; no CI |
| **Swedish as L1** | **Yes.** `sv` is in `SUPPORTED_LANGUAGES`. `messages/sv.json` has 1759/1759 keys translated. Prompts require a `native_explanation` in the learner's language. | **Partial and broken.** `sv` is selectable at onboarding, but there is no i18n (UI is English only). Dictionary glosses are English only. The `switchLanguage` tool rejects `sv`. About 3–4 weeks of work. |
| Targets | en-US, en-GB, es-ES (+ de, fr, it, ja, ko, pt, zh) | en, es (+ 10 more) |
| Placement | Client-side staircase over a hand-authored item bank; "highest level with ≥2 questions and ≥60% correct" | None |
| Lesson flow | Deterministic week/day grid over hand-authored CEFR units. The LLM generates lesson content inside each unit. No ongoing level estimation. | The chat tutor creates units (markdown) on request via tool calls. No learner model beyond SM-2 cards. |
| Exercises | multiple choice, fill-blank, free-write, pronunciation; reading, listening and speaking lessons; "Error Detective" game | 10 widgets: MC, translation, cloze, matching, listening, word bank, speaking, free text, flashcards |
| Tutor / persona | One tutor, "Lingu", with a hard "PERSONA LOCK"; voice; user-controllable memories | One editable system prompt; per-user override |
| Gamification | XP, streaks, skill scores, competencies; no badges or leagues | Streaks only |
| LLM providers | Ollama (default), OpenAI, Anthropic, DeepSeek. A generic OpenAI-compatible provider is ~1 day of work. | Google, OpenAI, Anthropic (+ proxy URL). Ollama/compatible is ~½ day. |
| Speech | STT: faster-whisper or OpenAI. TTS: Kokoro or OpenAI behind a duck-typed `synthesize()`. **Piper ≈ 1–2 days**, but per-language voice selection must be added. | OpenAI only, hard-wired, with R2 caching. Piper is ~1–2 days of refactoring. |
| Concerns | Open-core coupling (Stripe/freemium, off by flag); CLA for upstream contributions | `srs` tool executes **LLM-written raw SQL** (`client.unsafe`), so prompt injection could reach other users' rows; PostHog telemetry |

### Gap estimate for a FreeLingo fork

| Work item | Estimate |
|---|---|
| Generic OpenAI-compatible / OpenRouter provider | ~1 d |
| Piper TTS with per-language and per-persona voices | ~1–2 d |
| Multi-persona system (three-layer prompts, persona model, voice mapping; remove the single-persona lock) | ~1 wk |
| Gamification changes (conversation-minutes, missions, self-set streaks) | ~1–2 wk |
| **Elo/IRT learner model + "next activity" selector replacing the day-grid** | **~3–5 wk** |
| **Total** | **~6–9 dev-weeks** |

**The big change.** Plan, lessons, competencies and progress are all keyed to a curriculum
unit and a plan day. The pragmatic route is to *keep* FreeLingo's per-language CEFR data
(grammar, vocab sets, assessment bank, ~9.5 MB per target) as a **skill/item graph**. That
graph is the "competence map" research-01 recommended keeping anyway. Then:
- add per-skill ability (θ) and per-template difficulty tables;
- swap the day-grid for an adaptive selector;
- turn the placement staircase into a proper Elo/CAT with a decaying step and a stopping
  rule.

**Upstream vs. fork.** Small, generic pieces could go upstream: the OpenAI-compatible
provider and the Piper backend. That requires signing their CLA, which lets the owner
relicense our code commercially. The move away from a fixed curriculum conflicts with
their product, so expect a **long-lived fork**. Keep our changes modular to ease rebasing.

### Other projects found this pass

| Project | Adoption | Notes |
|---|---|---|
| Echo-Loop | 4.2k★, AGPL, Flutter, on app stores | English only, aimed at Chinese learners. A shadowing/retelling design reference. |
| Mural | 1.7k★, MIT | Native mobile; requires the user's own OpenAI key. Not released yet. |
| Polyglot | 2.6k★ | Aging Electron conversation app. |
| LibreLingo | — | Now archived. |

**Mature parts worth using:**
- **FSRS** instead of SM-2. It has published benchmarks showing it beats SM-2, and both
  repos use SM-2 today.
- Optional Anki/AnkiConnect export.
- `ai-pronunciation-trainer` (525★) as a pronunciation-scoring reference.

### Learning-outcome evidence for AI tutors [E]
- **Meta-analyses of generative AI / chatbots for L2 learning:**
  - Li, Wang & Yang 2025 (*JCAL*): g = 0.58 across 41 studies.
  - Others report g = 0.48 and 0.61.
  - All show large heterogeneity and many small quasi-experiments.
- **Mixed results:** the evidence includes a null result for ChatGPT-3.5 German speaking.
- **No FOSS tutor** has published outcomes.
- **[O]:** Build lightweight outcome measurement in from the start: placement θ over time,
  plus optional FLCAS/WTC questionnaires. That is how *we* would become "measurably good".

---

## 2. Gamification and motivation

### Evidence
- **Gamification works, modestly.** Sailer & Homner 2020 found:
  - cognitive outcomes g = 0.49, which holds in rigorous studies;
  - motivational outcomes g = 0.36 and behavioural outcomes g = 0.25, which are less
    stable.
  - Competition *combined with collaboration* beat competition alone [E].
  - For language subjects specifically, effects are around 0.38–0.5, with publication
    bias [E].
- **Expected, contingent rewards undermine intrinsic motivation.** Deci, Koestner & Ryan
  1999 found d ≈ −0.28 to −0.40. Unexpected, informational feedback does not have this
  effect [E].
  - Hanus & Fox 2015: mandatory badges plus a leaderboard *lowered* motivation and exam
    scores. This is a single study [E].
- **Self-Determination Theory: autonomy, competence, relatedness.**
  - Points, badges and leaderboards (PBL) mostly feed competence.
  - Mandatory PBL hurts autonomy, and competitive PBL hurts relatedness.
- **Duolingo [C]:**
  - A 7-day streak means users are 2.4× more likely to return.
  - Separating streak from daily goal gave +3.3% D14 retention.
  - Letting users set their own streak goal helped.
  - The notification bandit gave +2% new-user retention by *rotating* templates, not by
    sending more [E, KDD 2020].
- **Backlash to learn from:**
  - The 2025 energy system, which caps free practice to sell a subscription.
  - The 2025 "AI-first" memo.
  - Streak anxiety from loss-aversion design.
- **Speaking anxiety is the real enemy for conversation.**
  - Foreign-language anxiety (Horwitz et al. 1986, FLCAS) is driven largely by fear of
    negative evaluation.
  - Willingness to Communicate (MacIntyre et al. 1998) is the right north-star construct
    for us.
  - Small studies, mostly Chinese EFL, show AI chat practice lowers speaking anxiety and
    raises WTC [E, weak–moderate]. AI removes the fear of being judged.
  - **[O]:** Use the AI as a safe on-ramp, then nudge learners towards humans.

### Recommendation [O]

**Adopt:**
1. **Self-set, forgiving rhythm instead of a daily streak.**
   - The learner chooses a target, for example "3 conversations a week".
   - Rest days happen automatically, and repair is free.
   - Any meaningful activity counts.
   - No "you'll lose it" screens.
2. **Primary metric: time spent conversing in the target language** (minutes spoken or turns
   produced).
   - Weight it by stretch relative to θ, e.g. using newly introduced forms, or a turn longer
     than the learner's median.
   - This ties rewards to competence and to the adaptive level, not to tapping.
3. **Missions in role-plays.**
   - Each scenario has 2–3 communicative goals, such as "find out the price" or "complain
     politely".
   - An LLM judge verifies them against a structured rubric.
   - Completing them unlocks the next scene or story beat rather than awarding XP.
4. **Narrative progression with recurring characters.** Relatedness comes from people who
   remember you. Story arcs unlock with level.
5. **Unexpected, informational feedback.** For example: "First time you used the
   subjunctive!"
6. **Cooperative social features** (friend quests, shared goals) rather than competition.
7. **Few, rotating, opt-in notifications** with a cap, avoiding templates used recently
   (cheap counters, no ML needed).

**Avoid:**
- energy/hearts or anything that caps practice;
- default public leagues (opt-in at most, never for teen accounts by default);
- guilt or passive-aggressive tone;
- paid streak repair;
- mandatory badges;
- framing the AI as replacing human contact.

**FreeLingo fit.** It already has XP, streaks and competencies, so these become tweaks
rather than greenfield work: change what XP counts, add missions, add rhythm goals.

---

## 3. Persona cast: how many, which roles

### Evidence
- **Duolingo [C]:** a cast of about 10 diverse characters ("Sesame Street for adults"),
  but **Video Call uses only Lily**. The others appear as scenario NPCs in Roleplay and
  Adventures. That is one hero partner plus a supporting cast.
- **Praktika:** a selectable roster of avatars with accents and backstories.
- **Speak, Loora and Memrise:** essentially one tutor voice playing many roles.
- **Persona effect** (Lester 1997; Schroeder et al. 2013 meta-analysis, 43 studies): a
  lifelike agent mainly improves perception and engagement, with a small learning effect
  that is larger for younger learners [E].
- **Agent roles** (Kim & Baylor) [E]:
  - Expert agents improve how much information learners take in.
  - Motivator agents improve self-efficacy, and mentors do both.
  - *Lower-competence* peers raise self-efficacy.
  - Empathetic peers raise interest.
  - **So separate the explainer from the peer.** The low-anxiety partner should not be
    the chief corrector.
- **Similarity-attraction** [E]: learners respond better to agents they relate to. That
  argues for spreading age, gender and personality across the cast.
- **Choice overload** [E]: near zero on average, but real when preferences are uncertain
  and the task is hard, which describes a new learner. So offer few choices with a smart
  default.
- **Parasocial risk** [E, 2025 OpenAI/MIT studies]:
  - Heavy, emotional, voice-heavy use correlates with loneliness and dependence.
  - Users are upset by silent personality changes.
  - This supports static, versioned personas with announced changes, plus teen guardrails.
- **Accent variety** [E]: high-variability phonetic training is meta-analytically
  supported. Multi-talker exposure helps learners generalise, but transfer across accents
  isn't automatic. **[O]:** start beginners on one clear anchor variety and add more
  varieties as level rises.

### Recommended launch cast [O]

**Four fixed-role characters per target language. Scenario NPCs are generated on top.**

| Role (pedagogical layer) | Spanish | English | Notes |
|---|---|---|---|
| **Guide / explainer** (mentor) | Bilingual, ~35–45, e.g. a Swede living in Valencia | Bilingual Swedish/English speaker | **Only character allowed to use Swedish** for grammar and meta-explanations. Calm. Never examines. |
| **Peer A** (default conversation partner) | es-ES, ~20–28, playful, slightly fallible | en-GB or en-US, ~20–28 | Low-anxiety partner. Recasts and corrects only what blocks understanding; summarises errors at the end. |
| **Peer B** (alternative partner) | es-MX or es-CO, ~40–55, different interests | the other of en-GB/en-US, older | The learner picks A or B (default from age and goals) and can switch any time. Dialect contrasts appear as story content. |
| **Examiner** | Neutral and warm | Neutral and warm | Placement and "checkpoint conversations" only. Keeps testing out of the peers' safe space. |
| **Scenario NPCs** | generated per scenario | generated per scenario | Thin persona instances from a schema'd template, e.g. shopkeeper or landlord. A few *recurring* NPCs carry story arcs. B1+ adds more accents (e.g. Irish, Indian, Australian English; Argentine or Caribbean Spanish). |

**Rules:**
- **Roles are fixed to characters.** This keeps behaviour predictable and the
  role/pedagogy layer clean. The persona layer is still reusable across languages.
- **The learner chooses only between the two peers.** The app rotates NPCs and exposure to
  secondary dialects as θ rises.
- **Spread age (roughly 18–25, 30–45, 55+), gender and personality** across the cast so
  both teens and adults find someone relatable.
- **Don't launch a 10+ roster.** Every persona multiplies prompt, TTS voice, eval and
  safety-review cost. Grow through story NPCs and, later, community "persona packs".
  Versioned YAML plus AGPL makes contributions easy.
- **Safety:**
  - Personas are versioned, and changes are announced, never silent.
  - Characters never claim to be human, never flirt and never guilt-trip.
  - Teen accounts get stricter companion boundaries.
  - Characters nudge learners towards real-world conversation.

**Voices.** 8 core voices (4 roles × 2 languages) plus an NPC pool. Piper has es_ES and
es_MX voices and several en_GB/en_US voices; check per-voice licences and quality, as some
Piper voices carry dataset-specific licences.

---

## 4. Proposed next steps

1. **Fork FreeLingo** into this repo, or as a separate fork that this repo tracks.
   - Run it locally with Ollama and walk through placement, a lesson and the voice tutor
     in sv→en and sv→es.
   - Judge quality hands-on before committing to the 6–9 week plan.
2. **First low-risk changes**, in this order:
   - an OpenAI-compatible provider;
   - Piper TTS with per-language voices;
   - three-layer persona prompts with the 4-role cast.
3. Then the learner-model rewrite: Elo/CAT placement, per-skill θ and an adaptive
   selector over FreeLingo's curriculum graph.
4. Meanwhile, decide how far to diverge from upstream, and whether to ever contribute back
   under their CLA.

---

## 5. Decisions so far (2026-10-21)

- **Provider:** target the **OpenAI-compatible API** first, for chat, `/v1/audio/speech`
  (TTS) and `/v1/audio/transcriptions` (STT). Use hosted OpenAI voices for now.
  - The same API shape is served by local servers, so Piper/Kokoro/Whisper can be swapped
    in later behind the same interface without code changes.
  - Candidate servers to verify: openedai-speech (Piper), Kokoro-FastAPI, Speaches.
- **Model sizing:** route each task to a model size, rather than using one model for
  everything:
  - **Large model, offline/batch:** generates and validates scenario templates, item
    templates and anchor items; runs the persona eval suite; acts as the judge.
  - **Small model, live:** handles conversation turns at the learner's level, within
    constraints prepared by the large model.
  - **Large model, live (escalation):** grammar explanations in Swedish, error correction
    at higher levels, and anything the small model's output fails validation on.
  - Fine-tuning a small model on large-model output is a later option. Check the provider
    terms first: some forbid using outputs to train competing models.
