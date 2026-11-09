"""faster-whisper child process: one JSON request per stdin line, one JSON reply per stdout line.

Runs in /opt/whisper-env, which holds CUDA 12 libraries that clash with torch's in one process.
Only the standard library, numpy and faster_whisper are imported here.
"""

import base64
import json
import sys

import numpy as np

HF_REPOS = {"kbmedium": "KBLab/kb-whisper-medium", "kbsmall": "KBLab/kb-whisper-small"}


def load_model(model: str, device: str):
    from faster_whisper import WhisperModel

    path = model
    if model in HF_REPOS:
        from huggingface_hub import snapshot_download

        path = snapshot_download(HF_REPOS[model], allow_patterns=["model.bin", "*.json", "*.txt"])
    compute = "int8_float16" if device == "cuda" else "int8"
    return WhisperModel(path, device=device, compute_type=compute)


def ensure_model(req: dict, state: dict, loader) -> None:
    key = (req["model"], req["device"])
    if state.get("key") != key:
        state.clear()  # free the old model before loading the next
        state["model"] = loader(*key)
        state["key"] = key


def handle(req: dict, state: dict, loader=load_model) -> dict:
    op = req.get("op")
    if op == "unload":
        state.clear()
        return {"ok": True}
    if op == "load":
        ensure_model(req, state, loader)
        return {"ok": True}
    if op != "transcribe":
        return {"error": f"unknown op {op!r}"}
    ensure_model(req, state, loader)
    audio = np.frombuffer(base64.b64decode(req["audio"]), dtype=np.float32)
    segments, _ = state["model"].transcribe(
        audio, language=req["language"], beam_size=5, condition_on_previous_text=False
    )
    return {"text": " ".join(s.text.strip() for s in segments).strip()}


def main() -> None:
    out = sys.stdout
    sys.stdout = sys.stderr  # library prints must not corrupt the protocol
    state: dict = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line), state)
        except Exception as exc:  # noqa: BLE001
            reply = {"error": f"{type(exc).__name__}: {exc}"}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
