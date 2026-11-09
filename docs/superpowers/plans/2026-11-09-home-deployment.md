# FreeLingo home deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run FreeLingo at home for the owner's kids, with a same-voice Swedish and target-language tutor, one-button speech, GPU sharing with games, and a pre-generated game stock.

**Architecture:** A new `speech-gateway` service on `ai-vm` keeps the Whisper and Kokoro HTTP contracts, so the backend stays thin and gains no speech dependencies. The app runs in a new LXC on the `proxmox` host. `gpu-manager` shares the card with games, and a host-level control unit switches ninfer between 131072 and 32768 context for speech sessions.

**Tech Stack:** Python 3.14 FastAPI backend, Next.js 16 frontend, Python 3.12 gateway (FastAPI, OmniVoice, faster-whisper, onnx-asr, Lingua), Go 1.25 `gpu-manager`, OpenTofu and Ansible in `terranse`.

**Spec:** `docs/superpowers/specs/2026-11-05-home-deployment-design.md`

## Global Constraints

- Commit once per reviewed task on the local branch `feature/home-deployment` in each repo touched (`lalapp`, `terranse`, `gpu-manager`). Never push. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run only the targeted tests each task names. Never launch full suites. Fix failures in the task's own new code. If a pre-existing test breaks, stop and report it.
- No new backend or frontend dependencies. Gateway dependencies live only in `services/speech-gateway/`.
- No local Docker. Gateway images and tests run on `ai-vm`.
- Every schema change has an Alembic revision following `0057_flashcard_review_receipts`. Never apply migrations to a deployed database by hand.
- Target languages are exactly `["en-GB","es-ES"]`. Swedish is a native language only, never a target.
- Children's audio never leaves home hardware.
- Ninfer runs at 131072 context outside a speech session, 32768 during one, and is never restarted while busy.
- Do not touch the GPU, `ai-vm`, or Workstation while the `gaming` VM is running a game. A game start always wins.
- `tofu apply` touches the whole home infrastructure. Implementers stop after `tofu plan`. The controller reviews the plan and runs the apply.
- Visual work follows the Visual conventions in `AGENTS.md`. All new UI text goes through `messages/*.json`.

## Review Focus

- Silent or empty audio sent to `/asr` returns empty text quickly, without crashing and without routing to Swedish. Test in Task 3.
- OmniVoice running out of memory mid-sentence returns an error after one retry rather than hanging, and the turn continues with text. Tests in Tasks 3 and 5.
- A learner opening the app while ninfer is working leaves ninfer untouched, and a session expiring mid-reply waits for idle. Tests in Task 2.
- A reply whose lines are all `[screen]` is still shown and doesn't hang waiting for audio. Test in Task 5.
- A game taking the card mid-conversation makes the gateway unreachable, and the app says Lingu is away rather than showing a generic error. Test in Task 7.

---

## Phase 1: Running app

### Task 1: Gateway routing and audio polish

**Files:**
- Create: `services/speech-gateway/gateway/__init__.py`, `gateway/routing.py`, `gateway/polish.py`, `requirements.txt`, `requirements-whisper.txt`
- Test: `services/speech-gateway/tests/test_routing.py`, `tests/test_polish.py`

**Interfaces:**
- Produces: `decide_language(transcript: str, target: str) -> str` returning `"sv"` or `target`; `polish(audio: np.ndarray, sr: int) -> np.ndarray`; `room_tone(sr: int, seconds: float = 0.45) -> np.ndarray`.

- [ ] **Step 1: Write failing tests.** `test_empty_transcript_is_target` (`""`, `"..."` give the target); `test_swedish_sentence` (`"Jag vet inte vad det heter"`, `"en"` gives `"sv"`); `test_learner_english_stays_target` (`"He have two cats"`, `"My dog are big"` give `"en"`); `test_swedish_question_with_english_word` (`"Vad heter hund på engelska"`, `"en"` gives `"sv"`). `test_polish_trims_and_fades` (first and last samples near 0, voiced RMS within 5% of 0.08); `test_polish_peak_cap` (abs max at most 0.95); `test_polish_silent_input_unchanged` (all zeros returned, no exception); `test_room_tone_length_and_level` (`int(sr*0.45)` samples, abs max below 0.002).
- [ ] **Step 2: Implement.** Lingua detector built once per target with `from_languages(SWEDISH, target)`. Polish uses the exact values in the spec's speech synthesis measurements: 10 ms frames, threshold 3% of max RMS, 40 ms pad before, 120 ms after, 15 ms and 120 ms raised-cosine fades.
- [ ] **Step 3: Run on `ai-vm`.** Command: `docker run --rm -v /root/speech-gateway:/app -w /app python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && pytest tests/test_routing.py tests/test_polish.py -v"`. Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 2: Speech session manager and ninfer mode control

**Files:**
- Create: `services/speech-gateway/gateway/session.py`, `services/speech-gateway/deploy/ninfer-mode`
- Test: `services/speech-gateway/tests/test_session.py`, `tests/test_ninfer_mode.sh`

**Interfaces:**
- Produces: `class SessionManager(mode: ModeControl, clock: Callable[[], float], release_after: float = 600.0)` with `async open() -> SessionState`, `async keepalive() -> SessionState`, `async tick() -> None`, `state: SessionState`. `SessionState` is a string enum: `off`, `switching`, `ready`, `busy`, `shared`. `ModeControl` Protocol: `request(mode: str) -> None`, `read() -> dict` returning `{"mode", "state", "busy"}`.
- The host contract: the gateway writes `speech` or `full` to `/var/lib/speech-gateway/desired-mode`, and reads `/var/lib/speech-gateway/mode-state.json`.

- [ ] **Step 1: Write failing tests.** `test_open_when_idle_switches_to_speech`; `test_open_when_busy_reports_busy_and_does_not_request`; `test_busy_retries_when_idle_on_tick`; `test_keepalive_extends_release`; `test_release_after_600s_requests_full`; `test_release_waits_while_busy`; `test_small_slice_is_shared_and_never_switches`.
- [ ] **Step 2: Implement `SessionManager`.** A `shared` tier comes from `ModeControl.read()["mode"] == "shared"`.
- [ ] **Step 3: Implement `deploy/ninfer-mode`.** A bash script run by a systemd path unit on writes to `desired-mode`. Busy means any `throughput` line in `docker logs --since 15s ninfer` has `running`, `prefilling`, `decode_ready` or `waiting` above 0, because ninfer has no status endpoint. If busy, write `{"busy":true}` and exit with no change. Otherwise stop one of `ninfer.service` and `ninfer-speech.service`, start the other, wait for `http://127.0.0.1:8080/health`, and write the state.
- [ ] **Step 4: Run tests on `ai-vm`.** Pytest as in Task 1, plus `bash tests/test_ninfer_mode.sh`, which feeds fixture log lines to the busy check and asserts `running=1` is busy and `running=0 waiting=0` is idle.
- [ ] **Step 5: Commit after review.**

### Task 3: Gateway engines, HTTP API, and image

**Files:**
- Create: `services/speech-gateway/gateway/engines.py`, `gateway/whisper_worker.py`, `gateway/app.py`, `Dockerfile`
- Test: `services/speech-gateway/tests/test_app.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces, HTTP on port 8090:
  - `POST /asr?language=<iso>&output=json&task=transcribe`, multipart `audio_file`, returns `{"text","spoken_language"}`. `language` is the plan's target language.
  - `POST /v1/audio/speech`, JSON `{"input","language","response_format"}`, returns MP3. `language` is `sv`, `en` or `es`; `voice` and `model` are accepted and ignored.
  - `GET /v1/models`, `GET /` for health.
  - `POST /session/open`, `POST /session/keepalive`, `GET /session/status`, returning `{"state"}`.

- [ ] **Step 1: Write failing tests with fake engines.** `test_asr_silence_returns_empty_without_routing`; `test_asr_english_uses_parakeet_text`; `test_asr_swedish_uses_whisper_sv`; `test_asr_spanish_target_uses_whisper_es`; `test_speech_uses_reference_for_language`; `test_speech_unknown_language_is_400`; `test_speech_oom_retries_once_then_503`; `test_speech_when_session_not_ready_is_503`.
- [ ] **Step 2: Implement.** The API follows the spec's listening order. `faster-whisper` runs as a child process using a separate virtual environment at `/opt/whisper-env` with `nvidia-cublas-cu12` and `nvidia-cudnn-cu12==9.*`, because it clashes with torch's CUDA 13 libraries in one process. Communicate with it over stdin and stdout, one JSON line per request. Model choice: `kbmedium` for Swedish on English plans, `medium` for both Swedish and Spanish on Spanish plans, one loaded at a time, `kbsmall` on the CPU on Q-8C. Reference clips and their transcripts are read from `/models/refs/{sv,en,es}.wav` and `refs.json`. Set `TORCHDYNAMO_DISABLE=1`. The Dockerfile uses `python:3.12`, because ffmpeg and a compiler simplify audio dependencies.
- [ ] **Step 3: Run tests on `ai-vm` inside the built image.** Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 4: Deploy the gateway on `ai-vm`

**Files (in `/home/daniele/Repos/terranse`):**
- Create: `ansible/roles/llm/tasks/speech_gateway.yaml`, `templates/ninfer-speech.service.j2`, `templates/ninfer-mode.path.j2`, `templates/ninfer-mode.service.j2`, `templates/speech-gateway.service.j2`
- Modify: `tofu/deployments/edholm/configurations.tfvars:345-348` (`ai-vm` disk 150G to 220G, memory 24576 to 16384), `ansible/roles/llm/templates/ninfer.service.j2`

**Interfaces:**
- Consumes: the image from Task 3, and on `ai-vm` the reference clips at `/root/speechtest/refs/el_{sv,en,es}_75.wav` with their transcripts in `/root/speechtest/eltext.json`.

- [ ] **Step 1:** Add `ninfer-speech.service`, identical to `ninfer.service` but `--max-context 32768 --kv-capacity 32768`, with mutual `Conflicts=`. The role installs the path unit, gateway unit, and script, and copies the reference clips to `/opt/speech-gateway/refs`.
- [ ] **Step 2:** Implementer runs `tofu plan` and stops. Controller reviews that only `ai-vm` disk and memory change, then applies, and grows the guest partition.
- [ ] **Step 3:** Build the image on `ai-vm`, then `just setup ai-vm`.
- [ ] **Step 4: Smoke test on real hardware.** `POST /session/open`; wait for `ready`; send one Swedish clip and one English clip from `/root/speechtest/sttdata`; synthesize one sentence in each language; confirm transcripts match and `nvidia-smi` peak stays below 23.8 GB; let the session expire with a shortened `release_after`; confirm ninfer returns at 131072 and reads 22604 MiB.
- [ ] **Step 5: Commit in `terranse` after review.**

### Task 5: Spoken lines and per-language speech in the backend

**Files:**
- Create: `backend/app/services/spoken_lines.py`
- Modify: `backend/app/services/tts_service.py:14-40`, `backend/app/services/conversation_pipeline.py:272-300,335-410,560-700`, `backend/app/core/config.py:30-38`
- Test: `backend/tests/test_spoken_lines.py`, `backend/tests/test_tts_service.py`, `backend/tests/test_conversation_pipeline_service.py`

**Interfaces:**
- Produces: `@dataclass SpokenLine(language: str, text: str, spoken: bool)`; `parse_reply(text: str, target_code: str) -> list[SpokenLine]`; `invalid_swedish_lines(lines: list[SpokenLine]) -> list[SpokenLine]`; `display_text(lines: list[SpokenLine]) -> str`.
- `KokoroTTSService.synthesize` sends `language` in the JSON body.

- [ ] **Step 1: Write failing tests.** `test_parse_tags`; `test_untagged_line_treated_as_swedish_at_low_level`; `test_screen_lines_not_spoken`; `test_display_text_strips_tags`; `test_quoted_target_word_in_swedish_is_invalid`; `test_pipeline_rewrites_once_then_moves_to_screen`; `test_pipeline_all_screen_reply_completes_without_audio`; `test_tts_failure_on_one_line_still_sends_transcript`; `test_tts_sends_language`.
- [ ] **Step 2: Implement** within the existing pipeline, keeping sequential sending. Validation applies only when the native language is Swedish and the level is A1 or A2.
- [ ] **Step 3: Run.** `./scripts/local.sh backend python -m pytest tests/test_spoken_lines.py tests/test_tts_service.py tests/test_conversation_pipeline_service.py -v --no-cov`. Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 6: Child setting and Swedish teaching prompts

**Files:**
- Create: `backend/alembic/versions/0058_user_is_child.py`
- Modify: `backend/app/models/user.py:40`, `backend/app/schemas/auth.py:140,190`, `backend/app/routers/auth.py:335-387`, `backend/app/services/prompts/common.py:108`, `prompts/tutor.py:18,86`, `prompts/lesson.py:518`, `prompts/games.py:7,41,79`, `backend/app/routers/chat.py:335,348`, `conversation_pipeline.py:132`, `lesson_generator.py:172`, `frontend/src/lib/mappers.ts:27`, `frontend/src/store/auth.ts:28`, `frontend/src/components/settings/ProfileSection.tsx`, `messages/*.json`
- Test: `backend/tests/test_prompts.py`, `backend/tests/test_auth.py`, `frontend/tests/components/ProfileSection.test.tsx`

**Interfaces:**
- Produces: `User.is_child: bool` (default false); `child_instruction() -> str` and `instruction_language_rules(level: str, native_code: str, target_code: str) -> str` in `common.py`; keyword argument `is_child: bool = False` on each prompt builder.

- [ ] **Step 1: Write failing tests.** `test_a1_swedish_native_requests_tags`; `test_b1_keeps_target_language_only`; `test_non_swedish_native_has_no_rules`; `test_child_instruction_present_when_child`; `test_patch_me_sets_is_child`; `test_profile_section_toggles_child`.
- [ ] **Step 2: Implement.** Games read the flag through a new `GameSession` path added in Task 13; here, only the builders accept it.
- [ ] **Step 3: Run** the three test files by their targeted commands. Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 7: Speech session and heard-text in the app

**Files:**
- Create: `backend/app/routers/speech_session.py`, `frontend/src/hooks/useSpeechSession.ts`
- Modify: `backend/app/main.py`, `frontend/src/app/(app)/layout.tsx`, `frontend/src/components/conversation/ConversationMode.tsx`, `messages/*.json`
- Test: `backend/tests/test_speech_session.py`, `frontend/tests/hooks/useSpeechSession.test.tsx`, `frontend/tests/components/ConversationMode.test.tsx`

**Interfaces:**
- Produces: authenticated `POST /api/speech-session/open` and `/keepalive`, and `GET /api/speech-session/status`, returning `{"state": "off|switching|ready|busy|shared|away"}`. `away` means the gateway is unreachable.

- [ ] **Step 1: Write failing tests.** `test_open_proxies_state`; `test_gateway_unreachable_is_away_not_error`; `test_hook_keeps_alive_every_60s_while_visible`; `test_conversation_shows_heard_text_with_redo`; `test_away_state_shows_lingu_away_message`.
- [ ] **Step 2: Implement.** Open on app load, keep alive while the page is visible. The conversation screen shows what Lingu heard, with a redo action that discards the turn.
- [ ] **Step 3: Run** the targeted commands. Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 8: App LXC

**Files (in `terranse` unless noted):**
- Create: `ansible/roles/docker/templates/freelingo.yaml.j2`
- Modify: `tofu/deployments/edholm/configurations.tfvars`
- Modify in `lalapp`: `docker-compose.yml:32,120` so images come from `${FREELINGO_BACKEND_IMAGE:-ghcr.io/artcc/freelingo-backend:latest}` and the frontend equivalent.

- [ ] **Step 1:** Define the LXC with `docker_services=[{name="freelingo"}]`, with the frontend marked `# caddy:expose`, `/ws/*` forwarded to the backend, and the `.env` values listed in the spec, with `TTS_BASE_URL` and `STT_BASE_URL` at `http://ai-vm.edholm.cc:8090`.
- [ ] **Step 2:** Implementer runs `tofu plan` and stops. Controller reviews that only the new LXC, DNS host, and Caddy drop-in change, then applies.
- [ ] **Step 3:** Build the backend and frontend images on the LXC from the working tree copy. Alembic runs at backend start.
- [ ] **Step 4: Smoke test.** The site loads over HTTPS from the LAN with a trusted certificate and does not answer from outside. Create the owner's account first, then `ALLOW_REGISTRATION=false`.
- [ ] **Step 5: Commit after review.** Kids' accounts and the owner's recordings are the owner's to do.

## Phase 2: Sharing the card

### Task 9: Boot-time LLM tier and stable address

**Files:**
- Create: `services/speech-gateway/gateway/llm_proxy.py`, `terranse/ansible/roles/llm/templates/llm-tier.service.j2`, `terranse/ansible/roles/llm/files/llm-tier`
- Modify: `gateway/app.py`, `terranse/ansible/roles/llm/tasks/backend.yaml:38-50`
- Test: `services/speech-gateway/tests/test_llm_proxy.py`

**Interfaces:**
- Produces: `POST /v1/chat/completions` on the gateway, streaming pass-through, rewriting `model` to the live backend's name. `/run/llm-tier` contains `full` or `shared`.

- [ ] **Step 1: Write failing tests.** `test_rewrites_model_for_ninfer`; `test_rewrites_model_for_ollama`; `test_streams_chunks_unchanged`; `test_backend_down_is_503`.
- [ ] **Step 2: Implement.** At boot, 20 GB VRAM or more starts ninfer; less starts Ollama with `gemma4:e4b-it-qat` and `OLLAMA_CONTEXT_LENGTH=8192`. `ninfer.service` is no longer enabled directly. Hermes and pi keep pointing at ninfer.
- [ ] **Step 3: Run tests, deploy, and verify on a real Q-12C boot, only while no game is running.**
- [ ] **Step 4: Commit after review.**

### Task 10: `gpu-manager` sharing and health

**Files (in `/home/daniele/Repos/gpu-manager`):**
- Modify: `internal/reconcile/loop.go:190,207-231,303-310,333`, `internal/reconcile/solver.go`
- Test: `internal/reconcile/loop_test.go`

**Interfaces:**
- Behaviour: when a game claim sets a Q-8C or Q-12C layout with a free slot, `ai-vm` receives a slot at that profile with no explicit claim. When the game ends, `ai-vm` returns to Q-24C. A Q-24C game takes the card alone.

- [ ] **Step 1: Write failing tests.** `TestDefaultTenantFollowsSharedLayout`; `TestDefaultTenantReturnsToFullAfterGame`; `TestFullCardGameStopsDefaultTenant`; `TestSatisfiedFalseWhenVMDied`; `TestBootHealthResetsAfterTwoMinutes`.
- [ ] **Step 2: Implement.** A claim reads satisfied only when its VM is running. If the guest agent doesn't answer within 2 minutes of start, hard-reset once and log it.
- [ ] **Step 3: Run** `go test ./internal/reconcile/ -v`. Expected: all pass.
- [ ] **Step 4:** Deploy with `just setup workstation` only while no game is running, then verify one Q-12C game start and return.
- [ ] **Step 5: Commit after review.**

## Phase 3: Interactive voice

### Task 11: Reasoning effort and streamed replies

**Files:**
- Modify: `backend/app/services/llm_adapter.py:685,757,785-809`, `backend/app/services/conversation_pipeline.py:680-688,362-410`
- Test: `backend/tests/test_llm_adapter.py`, `backend/tests/test_conversation_pipeline_service.py`

**Interfaces:**
- Produces: keyword `reasoning_effort: str | None = None` on `chat` and `_do_chat`, sent only for the Ollama provider. The pipeline feeds complete tagged lines to TTS as they stream.

- [ ] **Step 1: Write failing tests.** `test_reasoning_effort_sent_for_local`; `test_reasoning_effort_absent_by_default`; `test_first_line_audio_before_stream_ends`; `test_stream_splits_long_sentence`.
- [ ] **Step 2: Implement.** Line validation runs per line as it completes. A failing line goes to `[screen]` without a rewrite during streaming, because the earlier audio has already played.
- [ ] **Step 3: Run the two targeted files.** Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 12: Provisional turns and opener

**Files:**
- Create: `backend/app/services/provisional_turn.py`
- Modify: `conversation_pipeline.py:556-700`, `routers/conversation.py`, `frontend/src/components/conversation/ConversationMode.tsx:431-539,576`, `frontend/src/lib/conversation-ws.ts:83`
- Test: `backend/tests/test_provisional_turn.py`, `frontend/tests/components/ConversationMode.test.tsx`, `frontend/tests/lib/conversation-ws.test.ts`

**Interfaces:**
- Client to server: binary audio preceded by `{"type":"provisional"}`, then `{"type":"confirm"}` or `{"type":"abort"}`.

- [ ] **Step 1: Write failing tests.** `test_provisional_has_no_side_effects_until_confirmed`; `test_memory_calls_held_until_confirm`; `test_abort_cancels_llm_and_tts`; `test_confirm_plays_opener_first`; `test_e4b_tier_skips_opener`; `test_vad_sends_provisional_at_800ms_and_confirms_at_redemption`; `test_short_user_pause_skips_provisional`.
- [ ] **Step 2: Implement** following the spec's timeline and rules. The opener uses `reasoning_effort: none` and the reply continues it as a prefilled assistant message at `low`.
- [ ] **Step 3: Run the targeted commands, then verify on Chrome for Android.** Expected: all pass.
- [ ] **Step 4: Commit after review.**

## Phase 4: Games

### Task 13: New game format and salvage

**Files:**
- Modify: `backend/app/services/prompts/games.py:7,41,79`, `backend/app/schemas/games.py:61,102`, `backend/app/services/games.py:392-439`
- Test: `backend/tests/test_games.py`, `backend/tests/test_sentence_order.py`

**Interfaces:**
- Produces: `DetectiveDraft` (`sentence`, `wrong_part`, `correct_part`, `wrong_options`, `explanation`, `source_id`); `build_challenge(draft: DetectiveDraft) -> DetectiveChallenge`; `salvage_challenges(drafts: list, needed: int = 5) -> list`.

- [ ] **Step 1: Write failing tests.** `test_build_challenge_splits_and_shuffles`; `test_wrong_part_not_in_sentence_is_dropped`; `test_salvage_keeps_valid_when_some_fail`; `test_too_few_valid_raises`; `test_prompt_requests_eight`; `test_child_flag_reaches_prompt`.
- [ ] **Step 2: Implement.** Request 8 challenges and keep 5 valid ones. Add `is_child` to `GameSession` in Task 14's migration, and read it in `generate_content`.
- [ ] **Step 3: Run the targeted files.** Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 14: Game stock

**Files:**
- Create: `backend/alembic/versions/0059_game_stock.py`, `backend/app/services/game_stock.py`
- Modify: `backend/app/models/game.py`, `backend/app/main.py`
- Test: `backend/tests/test_game_stock.py`

**Interfaces:**
- Produces: model `GameStock` (plan, mode, game type, content, created at, stale flag); `async refill_once(db) -> int`; `take_from_stock(db, plan, mode, game_type) -> GameStock | None`; constants `STOCK_TARGET = 3`, `DAILY_NEW_GAMES_PER_PLAN = 3`.

- [ ] **Step 1: Write failing tests.** `test_refill_fills_to_target`; `test_daily_cap_holds`; `test_stale_replacement_not_capped`; `test_new_plan_filled_first`; `test_refill_skips_when_not_full_tier`; `test_refill_yields_during_speech_session`; `test_recent_sentences_rejected_on_serve`.
- [ ] **Step 2: Implement** as a background task that checks `/session/status` and `/run/llm-tier` through the gateway.
- [ ] **Step 3: Run the targeted file.** Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 15: Serving, happy note, and replay

**Files:**
- Modify: `backend/app/services/games.py:263-324`, `backend/app/routers/games.py:89`, `frontend/src/components/games/GameCatalog.tsx:107,225`, `messages/*.json`
- Test: `backend/tests/test_games.py`, `frontend/tests/app/detective.test.tsx`

**Interfaces:**
- `POST /api/games/{game_type}` returns a session from stock, or 200 with `{"status":"empty","replayable":[...],"first_games_pending":bool}`. `POST /api/games/sessions/{id}/replay` creates a new session from a finished game's content.

- [ ] **Step 1: Write failing tests.** `test_serves_from_stock_without_llm`; `test_empty_stock_returns_happy_status`; `test_new_plan_empty_is_first_games_pending`; `test_replay_creates_new_session_no_xp_change_beyond_cap`; `test_catalog_shows_happy_note_and_replay`; `test_stock_game_playable_when_llm_away`.
- [ ] **Step 2: Implement.** The on-demand generation path is no longer reached by learners.
- [ ] **Step 3: Run the targeted commands.** Expected: all pass.
- [ ] **Step 4: Commit after review.**

### Task 16: Project documentation

**Files:** `specs/speech-services.instructions.md`, `specs/voice-conversation.instructions.md`, `specs/prompts.instructions.md`, `specs/games.instructions.md`, `specs/database-models.instructions.md`, `specs/services.instructions.md`, `specs/docker.instructions.md`, `specs/api-endpoints.instructions.md`, `specs/architecture-backend.instructions.md`

- [ ] **Step 1:** Update each file to describe current behaviour only, using lists rather than tables. The owner approved these edits. Do not touch `CHANGELOG.md`.
- [ ] **Step 2: Commit after review.**
