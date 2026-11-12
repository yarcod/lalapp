"""Speech engines. Heavy packages are imported inside the load paths only."""

import base64
import contextlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

CPU_TIER_BELOW_GB = 10.0
WHISPER_PYTHON = "/opt/whisper-env/bin/python"
WORKER_LOAD_TIMEOUT = 120.0
WORKER_REQUEST_TIMEOUT = 60.0
OMNIVOICE_LOAD_TIMEOUT = 300.0  # weights load from disk into a fresh CUDA context


class EngineOOM(Exception):
    """The GPU ran out of memory while generating."""


class EngineError(Exception):
    """An engine failed in a way that is not a retryable out-of-memory."""


def detect_vram_gb() -> float:
    """Total VRAM of the first GPU in GB, or 0 when nvidia-smi is unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return int(out.splitlines()[0].strip()) / 1024
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return 0.0


def whisper_choice(plan_language: str, vram_gb: float) -> tuple[str, str]:
    """Return (model, device) for a plan language such as "en" or "es"."""
    english = plan_language.split("-")[0].lower() == "en"
    if vram_gb < CPU_TIER_BELOW_GB:
        return ("kbsmall" if english else "small"), "cpu"
    return ("kbmedium" if english else "medium"), "cuda"


class ParakeetEngine:
    """Always loaded: Parakeet runs on the CPU."""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def transcribe(self, audio: np.ndarray) -> str:
        with self._lock:
            if self._model is None:
                import onnx_asr

                self._model = onnx_asr.load_model(
                    "nemo-parakeet-tdt-0.6b-v3",
                    quantization="int8",
                    providers=["CPUExecutionProvider"],
                )
            return str(self._model.recognize(audio, sample_rate=16000)).strip()


def worker_env(python: str) -> dict[str, str]:
    """Environment for the worker alone: the CUDA 12 libraries installed in its venv.

    Set only here because they would shadow torch's own CUDA in the gateway process."""
    venv = Path(python).parent.parent  # not resolved: bin/python is a symlink out of the venv
    lib_dirs = sorted(str(d) for d in venv.glob("lib/python*/site-packages/nvidia/*/lib"))
    current = os.environ.get("LD_LIBRARY_PATH")
    return {
        **os.environ,
        "LD_LIBRARY_PATH": os.pathsep.join([*lib_dirs, *([current] if current else [])]),
    }


class WorkerClient:
    """A child process answering one JSON line per request line. Unloading ends the process,
    which is the only way to hand its CUDA context back to the GPU."""

    name = "worker"

    def __init__(self, cmd: list[str], env: dict[str, str] | None = None) -> None:
        self._cmd = cmd
        self._env = env
        self._proc: subprocess.Popen | None = None

    @property
    def loaded(self) -> bool:
        """True while a worker process exists, including one still loading its model."""
        return self._proc is not None and self._proc.poll() is None

    def _forget(self) -> None:
        """Drop what the client knows about the worker's model."""

    def start(self) -> None:
        if self.loaded:
            return
        self._forget()
        self._proc = subprocess.Popen(  # noqa: S603
            self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._env,
        )

    def unload(self) -> None:
        proc, self._proc = self._proc, None
        self._forget()
        if proc is None:
            return
        proc.terminate()  # exiting frees the model and its CUDA context
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)

    def _kill(self) -> None:
        """A hung worker ignores SIGTERM, so unload's polite wait would only waste time."""
        proc, self._proc = self._proc, None
        self._forget()
        if proc is None:
            return
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)

    def _readline(self, proc: subprocess.Popen, timeout: float) -> str:
        lines: list[str] = []
        reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout)
        if reader.is_alive():  # the reader ends once the kill closes the pipe
            self._kill()
            raise EngineError(f"{self.name} worker timed out after {timeout:g} s")
        return lines[0]

    def _call(self, req: dict, timeout: float) -> dict:
        self.start()
        proc = self._proc
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            line = self._readline(proc, timeout)
        except OSError as exc:
            self.unload()
            raise EngineError(f"{self.name} worker died") from exc
        if not line:
            self.unload()
            raise EngineError(f"{self.name} worker exited")
        reply = json.loads(line)
        if reply.get("oom"):
            raise EngineOOM(reply.get("error", "out of GPU memory"))
        if "error" in reply:
            raise EngineError(reply["error"])
        return reply


class OmniVoiceEngine(WorkerClient):
    """Client for the OmniVoice child process, which runs in the gateway's own Python env."""

    name = "omnivoice"

    def __init__(self, python: str = sys.executable) -> None:
        super().__init__([python, "-m", "gateway.omnivoice_worker"])
        self._ready = False  # the worker holds the model

    def _forget(self) -> None:
        self._ready = False

    def load(self) -> None:
        self.start()
        if not self._ready:
            self._call({"op": "load"}, OMNIVOICE_LOAD_TIMEOUT)
            self._ready = True

    def synth(
        self, text: str, language: str, ref_audio: str, ref_text: str
    ) -> tuple[np.ndarray, int]:
        self.load()
        reply = self._call(
            {
                "op": "synth",
                "text": text,
                "language": language,
                "ref_audio": ref_audio,
                "ref_text": ref_text,
            },
            WORKER_REQUEST_TIMEOUT,
        )
        audio = np.frombuffer(base64.b64decode(reply["audio"]), dtype=np.float32).copy()
        return audio, int(reply["sample_rate"])


class WhisperEngine(WorkerClient):
    """Client for the faster-whisper child process."""

    name = "whisper"

    def __init__(self, python: str = WHISPER_PYTHON) -> None:
        super().__init__([python, "-m", "gateway.whisper_worker"])
        self._python = python
        self._loaded: tuple[str, str] | None = None  # the model the worker holds

    def _forget(self) -> None:
        self._loaded = None

    def start(self) -> None:
        self._env = worker_env(self._python)
        super().start()

    load = start

    @property
    def held_model(self) -> tuple[str, str] | None:
        """The (model, device) the worker holds, or None when nothing is loaded."""
        return self._loaded

    def preload(self, model: str, device: str) -> None:
        """Start the worker and load a model now, so the first request does not wait for it."""
        self.start()
        if self._loaded != (model, device):
            self._call({"op": "load", "model": model, "device": device}, WORKER_LOAD_TIMEOUT)
            self._loaded = (model, device)

    def transcribe(self, audio: np.ndarray, language: str, model: str, device: str) -> str:
        b64 = base64.b64encode(np.asarray(audio, dtype=np.float32).tobytes()).decode()
        key = (model, device)
        reply = self._call(
            {
                "op": "transcribe",
                "model": model,
                "device": device,
                "language": language,
                "audio": b64,
            },
            WORKER_REQUEST_TIMEOUT if self._loaded == key else WORKER_LOAD_TIMEOUT,
        )
        self._loaded = key
        return reply["text"]


class Engines:
    def __init__(self) -> None:
        self.parakeet = ParakeetEngine()
        self.tts = OmniVoiceEngine()
        self.whisper = WhisperEngine()
