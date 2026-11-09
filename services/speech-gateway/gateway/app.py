"""HTTP API of the speech gateway."""

import asyncio
import contextlib
import io
import json
import os
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from gateway.engines import (
    Engines,
    EngineOOM,
    detect_vram_gb,
    whisper_choice,
)
from gateway.llm_proxy import DEFAULT_TIER_FILE, make_handler
from gateway.polish import polish, room_tone
from gateway.routing import decide_language
from gateway.session import FileModeControl, SessionManager, SessionState

os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

SILENCE_RMS = 0.003
ASR_RATE = 16000
LANGUAGES = ("sv", "en", "es")
GPU_STATES = (SessionState.READY, SessionState.SHARED)
TICK_EVERY = 5.0
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class SpeechRequest(BaseModel):
    input: str
    language: str
    response_format: str = "mp3"
    voice: str | None = None
    model: str | None = None


def to_mono_16k(data: bytes) -> np.ndarray:
    audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if rate != ASR_RATE and len(audio):
        if rate > ASR_RATE:  # crude low-pass to limit aliasing
            width = max(int(round(rate / ASR_RATE)), 1)
            audio = np.convolve(audio, np.ones(width, dtype=np.float32) / width, mode="same")
        n = int(round(len(audio) * ASR_RATE / rate))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    return audio.astype(np.float32)


def encode_mp3(audio: np.ndarray, sr: int) -> bytes:
    proc = subprocess.run(  # noqa: S603
        ["ffmpeg", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
         "-f", "mp3", "-b:a", "96k", "-"],  # fmt: skip
        input=np.asarray(audio, dtype=np.float32).tobytes(),
        capture_output=True,
        check=True,
    )
    return proc.stdout


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def reconcile(engines, session) -> None:
    """Hold the GPU engines exactly while the session is ready or shared."""
    if session.state in GPU_STATES:
        engines.tts.load()
        engines.whisper.load()
    else:
        engines.tts.unload()
        engines.whisper.unload()


def create_app(
    engines=None,
    session=None,
    refs_dir=None,
    vram_gb: float | None = None,
    encoder=encode_mp3,
    background: bool = True,
    llm_tier_file=None,
    llm_transport=None,
) -> FastAPI:
    engines = engines or Engines()
    session = session or SessionManager(FileModeControl(), time.monotonic)
    refs_dir = Path(refs_dir or os.environ.get("REFS_DIR", "/models/refs"))
    vram = detect_vram_gb() if vram_gb is None else vram_gb
    gpu_lock = asyncio.Lock()

    async def loop() -> None:
        while True:
            try:
                await session.tick()
                async with gpu_lock:
                    await asyncio.to_thread(reconcile, engines, session)
            except Exception:  # noqa: BLE001 - keep the loop alive
                pass
            await asyncio.sleep(TICK_EVERY)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(loop()) if background else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models() -> dict:
        return {"object": "list", "data": [{"id": "omnivoice", "object": "model"}]}

    @app.post("/session/open")
    async def session_open() -> dict:
        return {"state": (await session.open()).value}

    @app.post("/session/keepalive")
    async def session_keepalive() -> dict:
        return {"state": (await session.keepalive()).value}

    @app.get("/session/status")
    async def session_status() -> dict:
        return {"state": session.state.value}

    @app.post("/asr")
    async def asr(
        language: str,
        output: str = "json",
        task: str = "transcribe",
        audio_file: UploadFile = File(...),  # noqa: B008
    ) -> dict:
        target = language.split("-")[0].lower()
        if target not in ("en", "es"):
            raise HTTPException(400, "unsupported language")
        try:
            audio = to_mono_16k(await audio_file.read())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, "unreadable audio") from exc
        if len(audio) == 0 or float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) < SILENCE_RMS:
            return {"text": "", "spoken_language": target}

        text = await asyncio.to_thread(engines.parakeet.transcribe, audio)
        spoken = decide_language(text, target)
        if spoken == "en":
            return {"text": text, "spoken_language": spoken}

        model, device = whisper_choice(target, vram)
        if device == "cuda" and session.state not in GPU_STATES:
            raise HTTPException(503, "speech session not ready")
        async with gpu_lock:
            text = await asyncio.to_thread(
                engines.whisper.transcribe, audio, spoken, model, device
            )
        return {"text": text, "spoken_language": spoken}

    @app.post("/v1/audio/speech")
    async def speech(req: SpeechRequest) -> Response:
        if req.language not in LANGUAGES:
            raise HTTPException(400, "language must be sv, en or es")
        if session.state not in GPU_STATES:
            raise HTTPException(503, "speech session not ready")
        try:
            ref_text = json.loads((refs_dir / "refs.json").read_text())[req.language]
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(503, "reference voice missing") from exc
        ref_audio = str(refs_dir / f"{req.language}.wav")
        sentences = split_sentences(req.input)
        if not sentences:
            raise HTTPException(400, "empty input")

        def render() -> bytes:
            parts: list[np.ndarray] = []
            sr = 0
            for sentence in sentences:
                for attempt in (1, 2):
                    try:
                        audio, sr = engines.tts.synth(sentence, req.language, ref_audio, ref_text)
                        break
                    except EngineOOM:
                        if attempt == 2:
                            raise
                if parts:
                    parts.append(room_tone(sr))
                parts.append(polish(audio, sr))
            return encoder(np.concatenate(parts), sr)

        async with gpu_lock:
            try:
                mp3 = await asyncio.to_thread(render)
            except EngineOOM as exc:
                raise HTTPException(503, "out of GPU memory") from exc
        return Response(mp3, media_type="audio/mpeg")

    tier_file = Path(llm_tier_file or os.environ.get("LLM_TIER_FILE", DEFAULT_TIER_FILE))
    app.post("/v1/chat/completions")(make_handler(tier_file, llm_transport))

    return app


def build() -> FastAPI:
    return create_app()
