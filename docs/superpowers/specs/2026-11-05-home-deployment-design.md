# FreeLingo home deployment and interactive voice

Date: 2026-11-05, voice and recognition revised 2026-11-09. Status: approved by the owner.

## Intent

FreeLingo is for the owner's kids to learn and play with languages. Nobody else uses it for now. It
runs entirely on hardware at home, with no paid external models, no tiers, and no limits on the kids.
Talking to Lingu has to feel like a conversation, and it must not teach them anything wrong.

## Learners

- All learners have Swedish as their mother tongue.
- The main learner is 11, very keen, uses words here and there, and rarely gets even basic sentences
  right. A 9-year-old sibling may join from time to time, at about the same level.
- The owner may try Spanish too, so not every learner is a child or a beginner.
- So: mostly one learner, occasionally two or three, and possibly two at once.
- Use is at home for now, on an Android phone or tablet, and possibly a Linux laptop.

## Goals

- Some voice agent is available at all times, except when a game holds the whole GPU (Q-24C).
- The best model that fits is used: Qwen3.8-27B with the whole card, a smaller model when sharing.
- One voice, the same person, speaks every language.
- A child can press one button and talk, in Swedish or the target language, without choosing which.
- A game and the AI can share the card on equal slices without either being killed.
- Lingu reacts about 2 s after a child stops talking, and the real reply follows soon after.
- Each learner's level is assessed per language, not assumed.
- A beginner can understand Lingu, which means Swedish explanations spoken in a Swedish voice.
- Games work on any slice, because good ones are generated ahead of time and kept in stock.

## Non-goals

- Billing, plans, freemium, or public registration.
- Paid or cloud LLM, TTS, or STT providers.
- Access from outside the home. It comes later, and needs its own look at login and exposure.
- Target languages other than British English and Spanish for now. Each one needs its own same-voice
  reference clip and a recognition check.
- Pre-generating Listening and Reading exercises (not evaluated; see "Left to the builder").

## Anti-goals

These would make it a failure even if it technically worked:

- Teaching a child something wrong in order to reply faster. The owner chose accuracy over speed.
- Fixed canned phrases in conversation. The owner expects them to get boring and feel out of place.
- Cutting a hesitant child off mid-sentence, or losing what they already said.
- Shrinking ninfer's context outside a speech session. Hermes and pi keep the full 131072 tokens the rest
  of the time, and a speech session never interrupts ninfer while it is working.
- Sending a child's voice to any cloud service.
- Host out-of-memory kills, which take down VMs and can reach the containers.

## Constraints

- Workstation is a Proxmox host, `root@workstation.netbird.cloud`, with one RTX A5000 (24 GB) and
  62 GB of RAM. VMs are `ai-vm` (114) and `gaming` (111). `gpu-manager` decides who holds the card.
- vGPU slices on the card must all be the same size. Q-8C allows 3, Q-12C allows 2, Q-24C allows 1.
- A slice only changes while the VM is stopped, so `ai-vm` reboots whenever the layout changes.
- Passed-through GPU memory is pinned, so each VM holds its full RAM from boot. Ballooning cannot help.
- Project rules in `AGENTS.md` apply: approval before editing specs, an Alembic revision for schema
  changes, no local Docker, and asking before running tests.

## Measurements behind this design

Taken 2026-11-04 and 2026-11-05 on the real hardware. Speech input was Kokoro audio, not real
children, and turn latencies are sums of separately measured steps unless stated.

GPU and RAM:

- Ninfer at 131072 context uses 22604 MiB. With Whisper `small` int8 beside it: 23470 MiB, with ninfer
  still healthy. Whisper `base` used 23028 MiB and `tiny` 22978 MiB.
- Ollama at 8k context: E4B QAT about 4.3 GB, Qwen3.8-27B about 17 GB, Gemma 12B QAT 7.7 GB. E4B plus
  Whisper `small` float16 used 5970 MiB.
- 32 GB + 32 GB VMs caused host out-of-memory kills. `ai-vm` at 16 GB beside a 32 GB `gaming` ran with
  no kills and about 4 GB available. `ai-vm` uses about 3 GB with ninfer. Kokoro uses 1.9 GB of RAM.

Latency:

- Whisper `small`: about 1.7 s on CPU, 0.12 s on GPU. `large-v3-turbo`: about 7 s on CPU, 0.19 s on GPU.
- Kokoro on CPU: 0.4-0.7 s for a normal first sentence, 2.9 s for a very long one.
- Ninfer first token: 4-13 s at default thinking, about 2-2.8 s at `reasoning_effort: low`, 0.4 s at
  `none`. Thinking-off replies from 27B were accurate. E4B with thinking off made teaching errors.
- E4B first token with thinking on: about 3.5-5 s.
- Generated opener on 27B: about 0.6 s. Opener, then prefilled continuation at `low`, across 9 prompts:
  continuation first token median 3.0 s, worst 5.8 s, and every student mistake was addressed.
- Aborting ninfer streams costs almost nothing: the next first token stayed at about 1.8-2.4 s.
- With The Witness on `gaming` at about 30-38% GPU, 8Q voice stayed at 0.64-1.1 s (one 3.5 s outlier
  from a long sentence), measured with thinking off. Game frame rate was not measured.

Speech synthesis, judged by the owner by ear, 2026-11-05 to 2026-11-07:

- Piper, Chatterbox, and OpenVoice conversion were rejected. Mixing languages inside one sentence sounded
  terrible with every local voice, so every spoken sentence is in one language.
- OmniVoice was chosen: about 1-1.4 s per sentence on the GPU, unusable on the CPU, about 2.4 GB of torch
  memory and 2.6 GB of VRAM in practice. Accent carries over from the reference clip.
- VoxCPM2 needs about 6 GB and cannot sit beside 27B. MOSS-TTS-Nano runs on the CPU at about real time.
- Clicks at sentence edges came from joining the audio, not the models. Each sentence is trimmed to voiced
  audio, padded 40 ms before and 120 ms after, faded 15 ms in and 120 ms out, normalised to a voiced RMS of
  0.08 with a 0.95 peak cap, and separated by 0.45 s of faint room noise rather than digital silence.
- Same-voice references were generated once with ElevenLabs ("Adam") for Swedish, British English, and
  Spanish. The clips are stored locally and no text from learners goes to ElevenLabs.

Speech recognition, 2026-11-08 and 2026-11-09, on FLEURS real speech (50 clips per language, GPU unless
noted) and on synthetic Swedish-accented learner clips:

- Swedish word errors: KB-Whisper large 4.6%, KB-Whisper medium 5.9%, OpenAI large-v3 6.75%, KB-Whisper small
  7.35%, turbo 7.45%, OpenAI medium 10.2%, Qwen3-ASR 1.7B 16.7%, OpenAI small 17.6%, Parakeet v3 19%.
- English: Qwen 1.7B 3.1%, OpenAI medium 3.95%, turbo and large-v3 4.1%, Parakeet 7.1%. Spanish: large-v3 2.7%,
  turbo 2.9%, Qwen 1.7B 3.3%, Parakeet 3.4%, OpenAI medium 3.5%.
- VRAM at peak: KB-Whisper medium 1.4 GB, small 0.9 GB, large 4.3 GB, Qwen 1.7B 4.8 GB. KB-Whisper is
  Swedish-only.
- Parakeet v3 (ONNX int8) on the CPU takes 0.2-0.4 s per clip and uses no VRAM. Whisper-family models on the
  CPU are too slow for conversation, except `small` at about 1.5 s per sentence.
- No model reliably keeps learner mistakes. Exact transcription of English learner clips: Qwen 1.7B 14 of 24,
  Parakeet 13, Whisper 6-10. "I goed" was never kept.
- Language decision between Swedish and the target language: Lingua text classification of Parakeet's
  transcript got 264 of 272 right, in 0.1 ms. Accented English 24 of 24, accented Spanish 8 of 16. Audio
  language ID (SpeechBrain) scored 240 of 272 because it hears a Swedish accent as Swedish. Whisper's own
  detection also failed on accented Spanish.

Memory fit on the full card, with 27B, OmniVoice, and KB-Whisper medium under simultaneous load:

- 32768 context passes, peaking at 23.3 GB with every sentence generated, about 3 s per sentence under that
  worst-case load. 49152 and 65536 run out of memory.
- A second GPU recogniser fails even at 16384 context.
- Ninfer takes about 26 s to restart at a new context size and stops in 0.5 s.
- Q-8C: E4B and OmniVoice use about 7.1 GB, leaving no room for GPU recognition. Q-12C: E4B and OmniVoice leave
  room for KB-Whisper medium.

Other observations:

- Slice changes took 36-47 s until the guest agent answered. Ninfer crash-loops on 8Q. One boot hung
  early after a slice change while `gpu-manager` reported it as fine, and the next 8 changes were clean.
- A `gpu-manager` claim stays "satisfied" after its VM has died.
- Whisper corrects some mistakes: every model heard "I goed" as "I go". It kept "childs" and "tener".

## What the owner decided

- Prefer accuracy over speed: E4B keeps thinking on in voice.
- There must be a Swedish voice. An A1 learner cannot be expected to understand a tutor speaking only the
  target language.
- Every learner's level is tested per profile and language, and the app works from the result. A1 is
  likely for the kids but must not be assumed.
- Ninfer keeps its full 131072 context, except during a speech session, when it runs at 32768 so the voice and
  recognition fit. Stock is generated between sessions.
- 27B plus OmniVoice on the full card, using the ElevenLabs same-voice references.
- British English is preferred over American.
- One microphone button. The app works out which language was spoken.
- Children's voices stay on local hardware. Cloud speech is not used for the kids.
- On small slices a smaller model is accepted. If OmniVoice cannot run there, a clearly different, more robotic
  voice is acceptable, so it is obvious which mode is active.
- `ai-vm` does not need 32 GB and should be reduced.
- Pre-generate games with the better model, and always keep a few in stock.
- Have the app, not the model, split game sentences.
- Keep the child's 1.8 s pause, but start work earlier and abort if the child continues.
- Keep the generated opener on 27B, accepting that it occasionally repeats a child's mistake.
- Games have a limit: nobody waits for a game to generate. When stock runs out, a happy note tells the
  learner to come back another day while stock slowly refills. Doing a little every day beats a lot at once.
- A replay offer goes alongside that note. No progress bar for generation, because that's scope creep.
- E4B does not generate games.
- Home use only for now, with remote access added later.
- The owner is building a separate evaluator that starts each game on the smallest slice its system
  requirements allow, falling back to Q-24C. All AI work is suspended during a Q-24C game.
- Priorities: a game start beats conversation and coding. Voice beats coding on ninfer.

## Deployment by location

### New `proxmox` host LXC (the app)

- A Docker LXC defined in terranse, following the `docker_services` pattern, running Postgres, Redis,
  backend, and frontend. It is outside Workstation because `ai-vm` reboots on every layout change.
- HTTPS is required for the microphone. Expose through the existing Caddy setup (the `# caddy:expose`
  label pattern) with the ACME wildcard certificate, so Android trusts it without installing a CA, and
  forward `/ws/*` to the backend.
- Reachable on the home network only. Check that the name doesn't answer from outside. Terranse doesn't
  yet create the DNS record or deploy the Caddy drop-in, so those are either wired up or done by hand.
- Create accounts with Swedish as the native language, and mark the kids' profiles as children.
- `.env` values:
  - `STRIPE_ENABLED=false`, `EMAIL_ENABLED=false`, `COOKIE_SECURE=true`.
  - `DEFAULT_CONVERSATION_DAILY_MINUTES=0`, `DEFAULT_CONVERSATION_WEEKLY_MINUTES=0`,
    `DEFAULT_CONVERSATION_WEEKLY_SESSIONS=0`, `DEFAULT_MONTHLY_TOKENS_LIMIT=0`, all set before accounts
    exist, because values are copied to each user at creation.
  - `AVAILABLE_TARGET_LANGUAGES=["en-GB","es-ES"]`.
- Create the owner's account first so it becomes admin, then the kids', then set
  `ALLOW_REGISTRATION=false`.
- App changes need our own images, because `docker-compose.yml` pulls `ghcr.io/artcc/freelingo-*`.

### `ai-vm` (terranse `llm` role)

- Add the speech gateway (below), always on, in every tier.
- Reduce RAM to 12 GB if a test run holds up, otherwise the tested 16 GB.
- Grow the disk from 150 GB; the pool has 2.9 TB free. The official Whisper GPU image did not fit in
  19 GB. Existing images, models, and build cache are left alone.
- Choose the LLM at boot from VRAM, replacing the fixed `llm_backend` choice:
  - 20 GB or more: ninfer as configured today.
  - Less: Ollama with `gemma4:e4b-it-qat` and `OLLAMA_CONTEXT_LENGTH=8192`.
- Give the app one stable LLM address and model name, and a way to tell which tier is live. Ninfer
  rejects any model name but its own, so a thin router such as LiteLLM is the expected approach.
- The speech gateway serves both recognition and speech, reachable from the app host on the LAN.
- The gateway starts on every boot, in every tier.
- The router and tier logic serve FreeLingo only. Hermes and pi keep pointing straight at ninfer, so on a
  small slice they fail visibly rather than silently running on E4B with a truncated context.
- ComfyUI stays off on small slices.

**Speech gateway.** One Python service on `ai-vm` that the app uses for all speech. It keeps the existing
HTTP contracts the backend speaks to Whisper and Kokoro, so the backend stays thin.

- Recognition: on the full card and Q-12C, Parakeet on the CPU and KB-Whisper medium on the GPU. On Q-8C, Parakeet
  and KB-Whisper small, both on the CPU.
- Speech: OmniVoice on the GPU with one reference clip per language. Per-sentence audio goes through the
  polish steps measured above.
- Speech session on the full card: the app calls the gateway when a learner opens it. If ninfer has no request
  running or queued, the gateway restarts ninfer at 32768 context and loads OmniVoice and KB-Whisper. Otherwise it
  reports `busy`, voice stays unavailable, and it tries again when ninfer goes idle. After 10 minutes with no
  session keep-alive it unloads them and restarts ninfer at 131072.
- On a small slice nothing is switched, because the slice is already running E4B and the speech models stay
  loaded.

### Workstation (`gpu-manager` and terranse config)

- `ai-vm` must take a slice in whatever Q-8C or Q-12C layout a game asks for, and return to Q-24C after
  the game ends. A Q-24C game still takes the card alone, and the AI is off until it ends.
- The owner's game evaluator picks the slice and is not part of this work. This work only has to accept
  any layout it chooses, including its Q-24C fallback.
- A game start wins as it does today, even if that reboots `ai-vm` during a conversation or coding turn.
- Add a boot health check: if `ai-vm`'s guest agent does not answer within about 2 minutes of start,
  hard-reset it and log it.
- Fix the claim status so that a claim whose VM has died does not read as "satisfied".
- Update the terranse comments that say the A5000 allows only one slice.

### `lalapp` code

Voice, games, child-suitable content, and the provider changes below.

## Level and language of instruction

**Placement.** The app already has what's needed, so this is mostly about using it:

- Each learner takes the existing placement test per language, and the plan follows from the result. It
  uses no LLM, so it works in every tier. The quiz starts at A2, has at most 15 questions, and has a "don't
  know" button.
- Its questions are written in the target language ("Elige la forma correcta"). A beginner may not be able
  to read the instructions. That should still land on A1, but watch whether it's discouraging.
- The existing "complete beginner" shortcut stays, and the kids are set up through the test instead.

**Swedish in Lingu's replies.** The rule depends on the plan's level and only applies when the native
language is Swedish, in both voice and text tutoring:

- A1-A2: explain mostly in simple Swedish, with short target-language phrases to copy. The exact level
  boundary and how the balance shifts are the builder's to tune.
- B1 and up: today's behaviour, staying in the target language.
- Every spoken sentence is in one language. Lines are tagged `[sv]` for Swedish, `[en]` or `[es]` for a full
  target-language sentence, and `[screen]` for correction text that is shown but not spoken.
- Swedish lines contain no target-language words. The app validates this, including quoted words, and asks the
  model for one rewrite. If the rewrite still fails, the offending line is moved to `[screen]`.
- Tags are removed from anything shown or saved.
- An empty reply is retried, not spoken or shown.

**Listening.** One button, no language choice. The explicit-language rule in `AGENTS.md` still holds, because the
backend always sends the plan's target language and the gateway decides from there.

1. Parakeet transcribes the audio on the CPU.
2. Lingua decides between Swedish and the target language from that transcript, in about 0.1 ms.
3. Target language: English uses Parakeet's transcript directly. Spanish is re-transcribed with OpenAI medium
   forced to Spanish, which replaces KB-Whisper on the GPU for Spanish plans, at about the same size.
4. Swedish: the same audio is transcribed by KB-Whisper, or by OpenAI medium on a Spanish plan.

Lingu shows what it heard, with a quick way to redo it, because no recogniser reliably keeps learner mistakes
and accented Spanish can be misrouted. Corrections must not treat the transcript as proof of what was said. The
owner records about 10 sentences per kid in Swedish, English, and a mix early in step 1, to check routing and
recognition on real children's voices.

**Content for children.** Prompts know a language level today, but nothing says the student is a child. They
may produce adult scenarios and explanations too hard for a 9-year-old.

- Add a child setting per profile, because the owner may learn on an adult profile. It needs an Alembic
  revision.
- With it on, tutor, voice, lesson, and game prompts say the student is a child of about 9-11: simple words,
  warm tone, and everyday topics such as school, friends, pets, and games.
- Swedish explanations must be easy for a child to understand, including in stocked games.

## Voice conversation

The browser keeps its own copy of the utterance's audio, using the VAD's `onFrameProcessed` frames.
The timeline after a child stops talking on 27B:

1. **At about 0.8 s of silence:** send the whole utterance so far as provisional. The backend
   transcribes it, generates the opener, then generates the reply. Nothing is shown, played, or saved.
2. **If the child speaks again before 1.8 s:** abort everything. The next pause sends the whole,
   longer utterance again.
3. **At 1.8 s of silence (the existing level-based `redemptionMs`):** confirm the turn. The opener plays
   as soon as it is ready, about 1.9 s after the child stopped.
4. **Reply:** streamed into TTS sentence by sentence as generated, typically starting about 5 s after
   the child stopped. Long sentences are split so a first fragment never takes seconds to synthesize.

Rules:

- A provisional turn has no side effects until confirmed: no transcript, no history, no quota, no
  persistence, and no memory writes. Memory-tool calls run during generation today, so they must be held.
- The frontend currently ignores speech while a tutor turn is active (`ConversationMode.tsx`). That
  must change for the provisional window only. Behaviour after confirmation stays as it is today.
- A user-chosen `conversation_speech_pause` keeps working. If it is too short for a useful head start,
  skip the provisional step.
- The reply continues the opener as a prefilled assistant message, the same message list for both, so
  they read as one answer. Telling the model what was already said separately was tested and rejected:
  thinking grew to 46 s and a correction was lost.
- Opener prompt: 2-5 words reacting to the topic, with no judgement, praise, correction, or teaching,
  using `reasoning_effort: none` and a small `max_tokens`.

By tier:

- **27B:** generated opener, reply at `reasoning_effort: low`. The opener follows the same language rule, so
  it's in Swedish at A1-A2.
- **E4B:** no generated opener, because its openers started teaching or ran on. Thinking stays on. The
  child waits about 5-6 s, so Lingu visibly shows thinking in the UI. Stay within the Visual conventions.
- **No LLM (Q-24C game, or `ai-vm` restarting):** the app stays up and says plainly that Lingu is away,
  rather than showing a generic error. Non-AI features keep working.

Provider and TTS changes:

- Pass `reasoning_effort` for the local provider per call. It is not sent today.
- The backend sends each tagged line to the gateway with its language, and the gateway picks the reference clip.
- Keep app-side context trimming at 8192 for this provider in both tiers.

## Games

**Format.** For Error Detective, the model returns `sentence`, `wrong_part`, `correct_part`, two
`wrong_options`, `explanation`, and `source_id`. The app splits the sentence into fragments, builds the
corrected sentence, and shuffles the options. Ninfer has no structured output, so the app keeps validating
the result as it does today. The other two game types get whatever equivalent makes sense.

**Who generates.** Only 27B generates games, and only in the background. On E4B, 3 of 12 games fully passed
with this format (English 3 of 6, Spanish 0 of 6), its Swedish explanations were clumsy, and its LLM review
step was unreliable.

**Yield on 27B.** The new format is untested on 27B. If whole games often fail on a single bad challenge,
request more challenges than needed and keep the valid ones.

**Stock.**

- 27B generates games in the background whenever it has the card, keeping "a few" ready for each study
  plan, mode, and game type. Stock is per plan because `review` and `prepare` games are built from that
  plan's completed lessons, mistakes, and recent sentences, and a plan fixes the language and level.
- Stock is refreshed when lesson progress makes it stale, and checked against recent sentences when served.
- Refilling is deliberately slow: a few new games per plan per day, so games don't reappear while the child
  keeps playing and the limit stays real. Replacing a stale game doesn't count toward that.
- A new plan gets its first games generated right away when 27B has the card.
- With only a few learners this stays a small number of buckets, which is why a shared pool isn't needed.
- Generation yields to voice and to Hermes or pi.
- Answers are checked against stored content with no LLM call, so stocked games stay playable while Lingu
  is away, including during a Q-24C game.
- This needs a schema change with an Alembic revision.

**When a learner asks for a game:**

1. Serve one from stock. Nobody ever waits for one to generate, in any tier.
2. If stock is empty, show a happy note: "wow, you've learnt so much already, come back another day". It must
   feel like a win, not an error or a paywall.
3. The note also offers to replay a finished game, if there is one. History can resume unfinished games today,
   but replaying a finished one is new work.
4. A learner who has played nothing yet can't be told they've learnt a lot, so a new plan with no stock
   gets a friendly "your first games are on the way, come back soon".

The existing on-demand generation path goes out of use for learners. The existing quota is for free accounts
and is bypassed with Stripe disabled, so this limit is the stock itself.

## Delivery order

1. **Running app:** LXC, HTTPS, `.env`, RAM, disk, and speech services on `ai-vm`, using 27B through the
   existing `ollama` provider setting with a stable address. The speech gateway, line tagging,
   language routing, and child-suitable prompts all ship here, because a beginner can't use it without
   them. The kids can use it after this step, slowly.
2. **Sharing the card:** boot-time LLM choice, `gpu-manager` changes, and the health check.
3. **Interactive voice:** streaming, `reasoning_effort`, provisional turns, opener.
4. **Games:** new format, salvage, stock.

## Known risks to measure during the build

- **Ninfer contention:** Hermes and pi share ninfer's two lanes and one context pool. A child could
  queue behind a coding session, for up to the 5-minute pending timeout. Measure this early. If it hurts,
  voice takes priority over coding (the builder chooses how; this is my call, not the owner's).
- **Two children at once:** this is rare but possible, and takes both of ninfer's lanes, leaving coding
  queued. Include it in the contention test. It is untested on E4B too.
- **Real children:** all learner-speech tests used synthetic adult audio. Children's voices are untested for
  recognition and for the language decision.
- **Swedish mixed into speech:** this learner is likely to drop Swedish words into a sentence, and the
  mixed sentences tested were garbled in either language, and the language decision is untested on them. Lingu may hear nonsense and reply to it. This is
  the speech risk most likely to matter, and is why real recordings come early.
- **Swedish on E4B:** on a shared slice, a beginner depends on E4B's Swedish, which was clumsy earlier and
  hasn't been tested with this prompt. If it teaches badly, that tier needs a rethink. Test this early in
  step 2.
- **Swedish from 27B:** it occasionally writes a nonsense sentence. Accepted for now, as with openers, but
  check it in the first real sessions.
- **Hidden mistakes:** every recogniser sometimes changes what a child said ("I goed" became "I go"), so Lingu
  cannot address it. Showing what Lingu heard is the mitigation. Accept for now.
- **Speech session contention:** Hermes or pi starting during a speech session runs at 32768 context. A session
  ending mid-reply would be disruptive, which is why release waits for idle.
- **Reference voice:** the ElevenLabs free plan is personal use only and OmniVoice weights are non-commercial,
  both fine for a home deployment and both blockers if this ever stops being one.
- **Heavier games:** The Witness was a light load, and frame rate wasn't measured. The owner's evaluator
  picks each game's slice, so check that a demanding game on a shared slice doesn't slow voice badly.
- **Aborts on Ollama:** only ninfer was tested.
- **Untested combinations:** provisional turns in the real app, streaming over the real WebSocket, 12 GB
  of RAM, and 27B on the new game format. Test audio on Chrome on Android first, then the Linux laptop.
- **Quality rough edges:** openers occasionally repeat a mistake, praise can double up ("¡Qué bien! ¡Muy
  bien!"), and one reply had a stray "SVENSKA:" label.

## Left to the builder

- Hostname, LXC sizing, how the speech services are packaged, and the router choice.
- Exact provisional-turn protocol over the WebSocket, within the rules above.
- The 0.8 s window can be tuned, since aborts are cheap.
- Sentence-split rules, opener prompt wording, and voice choice for en-US.
- Stock size and storage schema, within "a few" per study plan, mode, and game type.
- The happy note's wording and look, within the Visual conventions, and whether a replay earns XP.
- The number of new games per day, and when in the day refilling happens.
- How the speech gateway is packaged, within "one always-on service on `ai-vm`".
- How the child setting appears in the profile and in the prompts.
- When `ai-vm` returns to Q-24C after a game ends, so it doesn't interrupt a conversation if avoidable.
- Whether Listening and Reading need similar treatment on E4B. Check generation time and success there.

## Calls made without the owner's explicit input

- The app runs in a new LXC on the `proxmox` host, not on Workstation.
- Q-12C uses E4B, the same as Q-8C. Gemma 12B was ruled out on measurements.
- Grow `ai-vm`'s disk rather than delete anything.
- Voice takes priority over coding on ninfer, if measurement shows a conflict.
- The target language list is British English and Spanish, the two with reference clips.
- Game stock is per study plan, mode, and game type, rather than a shared pool.
- Swedish explanations apply up to A2, with B1 and up staying in the target language.
- Parakeet plus text classification decides the spoken language. Spanish plans use OpenAI medium on the GPU.
- A speech session ends after 10 minutes with no keep-alive.
- OmniVoice is the voice in every tier, unless it proves unstable on Q-8C.
- The child setting is per profile rather than for the whole app.
- Refilling is capped per day, so the limit holds even when 27B is free.
- The replay offer stays beside the happy note.
- Hermes and pi are not routed to E4B on small slices. They fail visibly until the card returns.
- A game start takes priority over a conversation or coding turn in progress.
