# Research 01: Landscape, Tutor Personas, Adaptive Levelling

*Status: research notes, 2026-10-21. Not a spec. Claims are marked where they come from
company sources vs. our own inference. Some sources were only seen as search snippets.
Verify a source before it drives a hard decision.*

## TL;DR

1. **Are we reinventing the wheel?** Partly. Several FOSS LLM language tutors exist, and they
   are young (most created in 2026). **None combines** a converging placement test, a real
   learner model, fully procedural lessons, and a Swedish L1. The plumbing (LLM adapters,
   Whisper/TTS, SRS, auth) is already solved and can be borrowed. The core we want (learner
   model, generator, persona system) is not.
2. **Personas: use a hybrid, not "static" vs. "generated".** Every serious product we found
   (Duolingo Lily/Roleplay, Babbel, Praktika, Memrise) uses **hand-authored, curated persona
   "bibles" with a fixed conversation structure and runtime slots** (level, topic, memories).
   None generates its tutor personas on the fly. Recommendation: split the prompt into three
   layers.
   - **Persona** (voice/character): static, version-controlled.
   - **Role** (pedagogical behaviour): static, version-controlled.
   - **Learner state** (dynamic): injected each turn from the DB.

   Use generation only for *flavour*, such as role-play NPCs instantiated from a schema'd
   template.
3. **The "PID curve" placement idea is sound.** Formally it is an Elo/IRT adaptive test
   with a decaying step size (Robbins–Monro / Glicko). P ≈ the Elo update, gain decay ≈ the
   damping, I ≈ the Bayesian prior, D is unnecessary. Duolingo's own models (Birdbrain v1,
   Duolingo English Test) are exactly this family.
4. **"No static lessons" needs one static thing: a level scale.** Duolingo, Babbel and
   FreeLingo all generate *within* a curated skeleton. We can avoid static *lessons*. We
   should still keep a static, small **competence map**: CEFR can-do descriptors plus
   grammar/vocab inventories per level, and ~20–40 human-checked anchor items per level.
   Without it, LLM difficulty estimates drift. They are noisy, biased toward the middle
   levels, and weak at A1/C2.

---

## 1. Existing apps: how they do it

### 1.1 Duolingo (best documented)

**Video Call with Lily** (https://blog.duolingo.com/ai-and-video-call/)
- Prompt roles:
  - "System" = instructions written by Learning Designers ("Lily's coach").
  - "Assistant" = Lily.
  - "User" = the learner.
- The System prompt contains:
  - Lily's personality and backstory;
  - how to help a struggling learner;
  - how to speak at the learner's level;
  - a fixed **conversation blueprint**: a CEFR-level greeting picked from a set, then a
    topic-setting "First Question", then more sections.
- Duolingo explicitly does not let the model "roam freely".
- **Memory:** after the call, the transcript is sent back to the LLM with "what was important?"
  The extracted facts are stored per user and injected next call. GPT-4o, no fine-tuning
  ([heise](https://www.heise.de/en/news/Duolingo-expands-offering-with-AI-video-calls-with-Lillie-and-more-9951940.html)).
- **Persona design principles** (Zan Gilani, Pendomonium 2024): authentic, entertaining,
  "don't break the metaphor", stress-free.
  - Lily corrects only errors that block understanding.
  - Her sarcasm was tuned through user testing.
  - Her sarcasm *increases with learner level*, i.e. the persona has level-dependent
    parameters.

**Roleplay / Explain My Answer (Max, 2023)**
- Human experts author each scenario, its opening message, and where the AI should steer
  the conversation.
- After the session, the learner gets feedback on the accuracy and complexity of what they
  said.

**Lesson generation** (https://blog.duolingo.com/large-language-model-duolingo-lessons)
- "Mad Lib" prompts with fixed rules, e.g. *"Write an exercise containing the word GO…
  Rules: 1. two answer options 2. max 75 characters"*.
- Code fills some slots (language, CEFR, theme); designers fill others (exercise type,
  grammar focus).
- Experts review and select from the output.

**Learner model**
- **Birdbrain v1:** IRT-inspired logistic regression. Learner ability and item difficulty
  are both updated after every exercise, Elo-like.
  - Sources: [blog](https://blog.duolingo.com/learning-how-to-help-you-learn-introducing-birdbrain/),
    [IEEE Spectrum](https://spectrum.ieee.org/duolingo).
- **Birdbrain now:** an RNN.
- **Session generator:** takes about 200 candidate exercises and picks about 14 that are
  "not too easy, not too hard".
- **Half-life regression** (Settles & Meeder, ACL 2016): p = 2^(−Δ/h). Used for spacing.
  Code: github.com/duolingo/halflife-regression.
- **Duolingo English Test:** computer-adaptive testing with IRT. Cold-start item difficulty
  is predicted from text features and mapped to CEFR, so no pilot testing is needed.
  - Sources: [Settles et al. TACL 2020](https://research.duolingo.com/papers/settles.tacl20.pdf),
    [McCarthy et al. EMNLP 2021](https://research.duolingo.com/papers/mccarthy.emnlp21.pdf).

### 1.2 Others

| App | Persona | Level / adaptivity | Source |
|---|---|---|---|
| **Praktika** | Avatars with accents and backstories. A "Lesson Agent" combines tutor personality, lesson context, goals and recent chats. | A separate "Student Progress Agent" tracks fluency, accuracy, vocabulary and recurring mistakes, and feeds the Lesson Agent. Memory layer. | [OpenAI case study](https://openai.com/index/praktika) |
| **Speak** | GPT-4-based tutor; Whisper plus in-house speech recognition | A knowledge graph of what the learner can do drives their path. Agent pipelines generate lessons on a curriculum scaffold. | [Latent Space](https://www.latent.space/p/personalized-ai-language-education) |
| **Babbel Speak** | "human-crafted content… brought to life by AI" | Curated scenarios with learning objectives | [babbel.com](https://www.babbel.com/babbel-conversation-practice) |
| **Memrise MemBot** | Mission and role prompts (bartender, interviewer…) | Tied to the course | [memrise blog](https://www.memrise.com/blog/introducing-membot) |
| **Loora** | — | Placement is a free conversation scored by a rubric (fluency, pronunciation, grammar, range…) and mapped to CEFR | [loora.com](https://www.loora.com/english-level-test) |
| **Busuu** | — | Adaptive CEFR placement test, about 10 minutes | business.busuu.com |
| Talkpal, Gliglish, Jumpspeak, ELSA, Langua | Marketing claims only | — | — |

### 1.3 Patterns across the industry (our inference)

1. **Personas are hand-written and curated.** None of the products we found generates them.
   Consistency comes from a fixed structure plus runtime slots, not fine-tuning.
2. **Memory is a separate LLM pass after the session.** It extracts facts and injects them
   into later prompts.
3. **Level estimation has two layers.**
   - Item-based ability estimation (IRT/Elo/RNN), plus spacing (HLR).
   - LLM rubric scoring for free conversation.
   - The resulting CEFR level is passed into prompts as a parameter.
4. **Content is a curated skeleton with LLM fill-ins** and human or rule-based review.
5. **Guardrails** are prompt constraints, review, and user reporting.

---

## 2. FOSS landscape: fork, contribute, or build?

Activity figures are approximate (GitHub `updated_at`).

### Tier 1: real candidates

**FreeLingo** (https://github.com/artcc/freelingo)
- **Licence:** AGPL-3.0 with a CLA. Open-core: a hosted paid tier exists.
- **Activity:** about 196★, created 2026-04, very active.
- **Stack:** Next.js + FastAPI + Postgres. LLM providers: Ollama (default), OpenAI,
  Anthropic, DeepSeek.
- **Placement:** free-write plus a level test, giving CEFR A1–C2.
- **Lessons:** the plan is a deterministic week/day grid built from a **hand-authored
  curriculum**. The LLM fills unit content.
- **Persona:** one tutor, "Lingu", hard-coded.
- **Voice:** real-time (faster-whisper/Kokoro or OpenAI).
- **Swedish:** the UI already ships a Swedish (`sv`) catalog. en-GB/en-US and es-ES are
  targets, with explanations in the learner's native language.
- **Fit:** closest feature-wise, but its lessons are curriculum-bound.

**OpenLingo** (https://github.com/pretzelai/openlingo)
- **Licence:** MIT. About 90★, created 2026-02.
- **Stack:** Next.js + Vercel AI SDK 6.
- **LLM:** OpenAI, Anthropic, Google, or an OpenAI-compatible proxy.
- **Lessons:** the closest to "no static lessons". A tool-calling tutor
  (`createUnit`, `presentExercise`, `srs`, `addMemory`) generates units on demand.
- **Gaps:**
  - no placement test and no explicit learner model;
  - TTS and STT are OpenAI only;
  - no Swedish.

**Polyglot Swarm** (https://github.com/NiravRVaghasiya/Polyglot-Swarm)
- **Licence:** MIT. Single author, 1★.
- **Design:** architecturally the best reference.
  - a per-skill learner model with uncertainty;
  - a multidimensional CEFR profile;
  - a next-best-action planner;
  - FSRS scheduling;
  - a correction verifier that suppresses low-confidence corrections;
  - a cognate and false-friend module.
- **Use:** borrow ideas, don't build on it.

### Tier 2: inspiration only

| Project | Licence | Notes |
|---|---|---|
| **Sotto** (affromero/Sotto) | PolyForm **Noncommercial** (not open source) | CEFR placement, mastery gates, regenerates the exercise on failure, i+1 listening, offline Ollama/Whisper/Kokoro. Use as idea source only. |
| **tutor-gpt / Bloom** (plastic-labs) | GPL-3.0 | A general tutor. Its **Honcho** "theory of mind" user-modelling layer is worth studying for learner memory. |
| Kaiwa | AGPL-3.0 | Japanese only. Good offline-first desktop pattern. |
| Speakeasy | MIT/Apache (inconsistent) | English only. Builds a profile, keeps memory, deliberately makes no corrections. |
| Polyglot (liou666) | GPL-3.0 | 2.6k★ but stale. Conversation only, no adaptivity. |
| BabelDuck | Custom licence (not FOSS yet) | Conversation practice, no levels. |
| LibreLingo | — | Static courses, no LLM, mostly dead. |

### Verdict

- Nothing fits as-is. Mature projects are curriculum-bound; the procedural ones are thin.
- **No FOSS project generates personas.** They all use one hard-coded tutor or a fixed
  scenario list.
- Building our own **core** (learner model, procedural generator, persona system) is
  justified.
- We should **borrow plumbing**:
  - FreeLingo's (AGPL) or OpenLingo's (MIT) LLM and voice adapters;
  - FSRS for spacing;
  - Polyglot Swarm's learner-model design.
- Licence: Lalapp is AGPL-3.0 (see `LICENSE`). MIT (OpenLingo), GPL-3.0 (Piper) and
  AGPL-3.0 (FreeLingo) code can all be combined into it. Hosting it obliges us to offer
  the source to users (AGPL network clause).

---

## 3. Persona design: recommendation

### 3.1 Three layers, assembled per turn

```
┌────────────────────────────────────────────────────────────┐
│ PERSONA  (static, versioned, reviewed via PR)               │  who is speaking
│   name, backstory, personality, humour, dialect (es-ES/MX,  │
│   en-GB/US), register, sample lines, level-dependent knobs  │
├────────────────────────────────────────────────────────────┤
│ ROLE / MODE  (static, versioned)                            │  how to teach
│   conversation partner | drill coach | explainer | examiner │
│   explicit pedagogical rules (LearnLM-style)               │
├────────────────────────────────────────────────────────────┤
│ SCENARIO  (template static; instance generated + validated) │  what's happening
│   "ordering at a tapas bar", NPC traits, goals             │
├────────────────────────────────────────────────────────────┤
│ LEARNER STATE  (dynamic, from DB, never from LLM memory)    │  who is listening
│   θ per skill, CEFR band, i+1 targets (vocab/grammar),      │
│   known error patterns, extracted memories, L1 = sv         │
├────────────────────────────────────────────────────────────┤
│ POST-HISTORY REMINDER  (compact persona+role+level recap)   │  anti-drift
└────────────────────────────────────────────────────────────┘
```

Why the layers are split:
- **Persona ≠ pedagogy.** Any persona can play any role. Lily-the-sarcastic-friend can be a
  conversation partner *or* a drill coach. Pedagogy can then be tested and improved without
  touching characters, and characters can be added without risking pedagogy. LearnLM
  (https://arxiv.org/abs/2412.16429) frames pedagogy as instruction-following on explicit
  system rules, which matches this split.
- **Static plus versioned for the parts that define quality and safety.** Persona and role
  prompts *are* product code. They need diffs, review, rollback, and **evals in CI**
  (promptfoo-style). The eval matrix is persona × role × CEFR band, judged by an LLM against
  a rubric covering:
  - level adherence;
  - staying in the target language;
  - correction behaviour;
  - character consistency.
- **Generated where it adds variety, never where it adds risk.**
  - The LLM may instantiate *scenario NPCs* (a grumpy Madrid taxi driver) from a JSON
    schema with bounded fields.
  - The LLM may vary greetings and topics.
  - It must not author pedagogical rules.
  - Generated instances that test well can be "promoted" into the versioned library.
- **Drift is real.** Persona stability drops noticeably within about 8–18 turns:
  - Li et al. 2024, https://arxiv.org/html/2402.10962v1;
  - Gonnermann-Müller et al. 2026, https://arxiv.org/abs/2601.22812.

  Countermeasures:
  - a post-history reminder;
  - summarising old turns into learner state;
  - a cheap judge model every N turns that checks CEFR level and language of the tutor's
    output.

  Anthropic's "keep Claude in character" guide recommends the same defined-role, scripted
  scenarios and reinforcement approach. It is a provider guide, but the advice transfers.

### 3.2 File format sketch

Use a superset of the community **Character Card V2** fields (`name`, `description`,
`personality`, `scenario`, `first_mes`, `mes_example`, `post_history_instructions`) so
community cards can be imported. Add our own fields:

```yaml
# personas/lucia.yaml
id: lucia
version: 3
name: Lucía
target_languages: [es]
dialect: es-ES
backstory: >-
  28, grew up in Valencia, works at a bike-repair co-op, obsessed with paella arguments.
personality: [warm, teasing, curious]
knobs:            # numeric, interpolated by learner CEFR band
  humour:        {A1: 0.2, B1: 0.5, C1: 0.8}
  speech_rate:   {A1: slow, B2: natural}
  swedish_allowed: {A1: hints_only, A2: hints_only, B1: never}
sample_lines:
  - "¡Venga ya! ¿Paella con chorizo? Eso no es paella, eso es arroz con cosas."
safety_notes: "Never flirtatious. Never discuss learner's real-world location."
```

```yaml
# roles/conversation_partner.yaml
id: conversation_partner
version: 5
rules:
  - Stay in the target language; switch to Swedish only per persona.knobs.swedish_allowed.
  - Correct only errors that block understanding; otherwise recast naturally.
  - Use only vocabulary at or below {{learner.cefr}} plus {{session.new_words}}.
  - Ask one question at a time; keep turns ≤ {{limits.turn_words}} words.
outputs:
  sidecar_schema: turn_assessment.v2   # structured eval emitted alongside the reply
```

Also store **examples and expected behaviours** next to each file. These become the eval
suite.

### 3.3 Memory

Copy Duolingo's pattern:
- After each session, run an extraction pass that turns the transcript into structured
  facts (interests, names, recurring errors).
- Store them in the DB and inject the top-k into the next session.
- Honcho (Plastic Labs) is an option if we want something richer later.

---

## 4. Adaptive levelling: the "PID" placement and lessons

### 4.1 Mapping the intuition

| PID intuition | Formal equivalent |
|---|---|
| Error signal | Observed − expected correctness (`1 − P(correct)`) |
| P term | Elo/Rasch update: θ ← θ + K·(obs − exp) |
| Damping / settling | **Decay K** as evidence grows (K ∝ 1/√n, or K from posterior SD = Glicko) |
| I term | The Bayesian prior/posterior over θ (accumulated evidence) |
| D term | Not needed. Use a **stopping rule** (posterior SD < ε, or 15–25 items) |
| Setpoint | Target success rate: about 50–60% in placement (most information), about 75–85% in lessons (motivation) |

Notes on the evidence:
- The "85% rule" (Wilson et al. 2019) was derived for machine learners. Treat it as a
  heuristic for people.
- A 1-up/2-down staircase converges to about 71% correct, a simple fallback.
- Elo as an online IRT for adaptive practice: Pelánek 2016,
  https://www.fi.muni.cz/~xpelanek/publications/CAE-elo.pdf.

### 4.2 Multidimensional, not one number

Keep θ per skill: vocabulary, grammar, listening, reading, speaking, writing.
- Placement starts from the learner's self-report (CEFR can-do statements in Swedish), then
  runs CAT.
- Placement needs a short **free production** task, LLM-rubric scored like Loora. Item
  tests miss speaking ability.
- Use FSRS (open, as in Anki) or HLR for per-item retention, separate from θ.

### 4.3 Calibrating LLM-generated items without an item bank

1. **Generate to a spec, not "make a B1 sentence".** Each request carries a CEFR target,
   allowed vocabulary bands, a grammar point and length limits.
   - English vocabulary bands: English Vocabulary Profile.
   - Spanish inventories: Plan Curricular del Instituto Cervantes.
   - Check the EVP/EGP licences before bundling.
2. **Prior difficulty** comes from cheap features (word-frequency band, highest-level word,
   grammar-point level) plus an LLM *pairwise* comparison against anchors. Give this prior
   a wide SD.
   - Pairwise beats absolute rating (https://www.alphaxiv.org/abs/2605.18562).
   - Zero-shot CEFR classification is noisy and biased toward the middle levels
     (https://arxiv.org/abs/2506.01419).
3. **Anchor set:** about 20–40 human-checked items per level per language. These pin the
   scale.
4. **Online Elo/Glicko on learners *and* item templates.** Pool difficulty per template or
   skill, since generated instances are one-offs. Refit the feature model as data grows.
   This is Duolingo's cold-start approach (McCarthy 2021), done online.
5. **Lesson loop:** pick the next skill (lowest mastery × importance, or due for review).
   Then generate N candidates to spec, validate them (schema, language ID, vocabulary
   band), and choose the one with predicted P(correct) closest to the target. This is
   Duolingo's "200 → 14" idea, scaled down.

---

## 5. Provider-agnostic stack (initial opinion)

**LLM**
- Use a thin internal interface (`chat`, `structured<T>`, `stream`, `embed`).
- Build it on the **Vercel AI SDK** if we use TypeScript. Its v6 API moved structured
  output to `output: Output.object(...)`; verify against the docs.
- Make **"OpenAI-compatible base URL + key"** the universal fallback. That covers
  OpenRouter, Ollama, llama.cpp, LM Studio, vLLM and Groq.
- Validate every structured output with Zod/JSON Schema, and retry or repair on failure.
  Keep schemas flat, because small local models struggle with deep nesting.
- Keep a capability matrix per model and route cheap tasks (grading, item generation) to
  cheap models.
- **LiteLLM caution:** PyPI versions 1.82.7 and 1.82.8 were backdoored (March 2026). If we
  use it, pin versions and verify hashes.

**Speech**
- Define a `SpeechProvider` interface with three backends: browser-local, self-hosted
  server, and cloud.
- STT: Whisper / whisper.cpp, which handles sv, en and es.
- TTS: **Piper is the preferred choice** (has sv_SE, es_ES and es_MX; GPL-3.0, which is
  compatible with our AGPL). Kokoro (en and es, no Swedish) is an alternative.
- Use the Web Speech API as a fallback only.
- Realtime speech-to-speech (OpenAI or Gemini) should be an optional add-on, not the core.

**Client**
- Build a **PWA first** (React/TS + Vite).
- Wrap it with **Tauri 2** for desktop/mobile with a local llama.cpp/whisper sidecar.
- Use Expo only if native mobile audio becomes the bottleneck.

**Prompt management and evals**
- Prompts live in the repo as YAML, with a promptfoo-style eval suite in CI.
- Optional: self-hosted Langfuse for tracing.

---

## 6. Open questions for the next step

- Should we prototype quickly on top of OpenLingo or FreeLingo, or go greenfield with the
  three-layer persona system and Elo engine from day one?
- How many personas at launch? Suggested: 2 per target language (one peer/buddy, one
  teacher), plus a shared "examiner" role for placement.
- Gamification and motivation layer (streaks, XP, quests). Not researched yet.
