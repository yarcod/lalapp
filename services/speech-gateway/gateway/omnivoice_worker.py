"""OmniVoice child process: one JSON request per stdin line, one JSON reply per stdout line.

Runs in the gateway's own Python env. The model lives here and not in the gateway process
because only a process exit returns its CUDA context to the GPU; torch and omnivoice are
imported only when the model loads.
"""

import base64
import json
import sys

import numpy as np

SAMPLE_RATE = 24000


def load_model():
    import torch
    from omnivoice import OmniVoice

    return OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)


def is_oom(exc: BaseException) -> bool:
    """torch.cuda.OutOfMemoryError, matched by name so torch is never imported for it."""
    return type(exc).__name__ == "OutOfMemoryError"


def free_cache() -> None:
    torch = sys.modules.get("torch")
    if torch is not None:
        torch.cuda.empty_cache()


def handle(req: dict, state: dict, loader=load_model) -> dict:
    op = req.get("op")
    if op not in ("load", "synth"):
        return {"error": f"unknown op {op!r}"}
    if "model" not in state:
        state["model"] = loader()
    if op == "load":
        return {"ok": True}
    try:
        out = state["model"].generate(
            text=req["text"],
            language=req["language"],
            ref_audio=req["ref_audio"],
            ref_text=req["ref_text"],
        )[0]
    except Exception as exc:
        if not is_oom(exc):
            raise
        free_cache()
        return {"error": f"out of GPU memory: {exc}", "oom": True}
    if hasattr(out, "detach"):
        out = out.detach().float().cpu().numpy()
    audio = np.asarray(out, dtype=np.float32).reshape(-1)
    return {"audio": base64.b64encode(audio.tobytes()).decode(), "sample_rate": SAMPLE_RATE}


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
            if is_oom(exc):  # e.g. while loading the model
                free_cache()
                reply["oom"] = True
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
