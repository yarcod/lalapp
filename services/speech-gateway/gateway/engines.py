"""Speech engines. Heavy packages are imported inside the load paths only."""

import base64
import json
import subprocess
import threading

import numpy as np

CPU_TIER_BELOW_GB = 10.0
WHISPER_PYTHON = "/opt/whisper-env/bin/python"
OMNIVOICE_SR = 24000


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


class OmniVoiceEngine:
    def __init__(self) -> None:
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from omnivoice import OmniVoice

        self._model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16
        )

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        import gc

        import torch

        gc.collect()
        torch.cuda.empty_cache()

    def synth(
        self, text: str, language: str, ref_audio: str, ref_text: str
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            self.load()
        import torch

        try:
            out = self._model.generate(
                text=text, language=language, ref_audio=ref_audio, ref_text=ref_text
            )[0]
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            raise EngineOOM from exc
        if hasattr(out, "detach"):
            out = out.detach().float().cpu().numpy()
        return np.asarray(out, dtype=np.float32).reshape(-1), OMNIVOICE_SR


class WhisperEngine:
    """Client for the faster-whisper child process."""

    def __init__(self, python: str = WHISPER_PYTHON) -> None:
        self._cmd = [python, "-m", "gateway.whisper_worker"]
        self._proc: subprocess.Popen | None = None

    def load(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(  # noqa: S603
            self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def unload(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        proc.terminate()  # exiting frees the model and its CUDA context
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _call(self, req: dict) -> dict:
        self.load()
        proc = self._proc
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except OSError as exc:
            self.unload()
            raise EngineError("whisper worker died") from exc
        if not line:
            self.unload()
            raise EngineError("whisper worker exited")
        reply = json.loads(line)
        if "error" in reply:
            raise EngineError(reply["error"])
        return reply

    def transcribe(self, audio: np.ndarray, language: str, model: str, device: str) -> str:
        b64 = base64.b64encode(np.asarray(audio, dtype=np.float32).tobytes()).decode()
        reply = self._call(
            {
                "op": "transcribe",
                "model": model,
                "device": device,
                "language": language,
                "audio": b64,
            }
        )
        return reply["text"]


class Engines:
    def __init__(self) -> None:
        self.parakeet = ParakeetEngine()
        self.tts = OmniVoiceEngine()
        self.whisper = WhisperEngine()
