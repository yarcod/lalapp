"""Speech session lifecycle: switch ninfer to speech mode on demand, release when idle."""

import json
import os
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

DEFAULT_STATE_DIR = Path("/var/lib/speech-gateway")
DEFAULT_TIER_FILE = "/run/llm-tier"
_DEFAULT_READ = {"mode": "full", "state": "ready", "busy": False}


class SessionState(StrEnum):
    OFF = "off"
    SWITCHING = "switching"
    READY = "ready"
    BUSY = "busy"
    SHARED = "shared"


class ModeControl(Protocol):
    def request(self, mode: str) -> None: ...

    def read(self) -> dict: ...


def read_tier(path: Path) -> str:
    """`full` (ninfer) or `shared` (Ollama); a missing or odd file means `full`."""
    try:
        tier = path.read_text().strip()
    except OSError:
        return "full"
    return tier if tier == "shared" else "full"


class FileModeControl:
    """Host contract: write desired-mode, read mode-state.json. The tier file wins: a shared
    tier is `shared` before any session opens, when mode-state.json may not exist yet."""

    def __init__(
        self,
        directory: str | Path = DEFAULT_STATE_DIR,
        tier_file: str | Path = DEFAULT_TIER_FILE,
    ) -> None:
        self._dir = Path(directory)
        self._tier_file = Path(tier_file)

    def request(self, mode: str) -> None:
        if mode not in ("speech", "full"):
            raise ValueError(f"cannot request mode {mode!r}")
        tmp = self._dir / "desired-mode.tmp"
        tmp.write_text(mode + "\n")
        os.replace(tmp, self._dir / "desired-mode")

    def read(self) -> dict:
        try:
            data = json.loads((self._dir / "mode-state.json").read_text())
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError):
            data = {}
        result = {**_DEFAULT_READ, **data}
        if read_tier(self._tier_file) == "shared":
            result["mode"] = "shared"
        return result


RETRY_EVERY = 30.0


class SessionManager:
    """The host script is the only authority on busy: every desired mode is written and the
    script accepts or refuses it. A refusal reads as mode != desired with busy and state ready;
    the write is repeated at most every 30 s until accepted.

    Releasing stops serving speech at once (SWITCHING), and `full` is written only once
    `gpu_idle` reports the GPU engines unloaded: full ninfer needs the memory they hold."""

    def __init__(
        self,
        mode: ModeControl,
        clock: Callable[[], float],
        release_after: float = 600.0,
        gpu_idle: Callable[[], bool] = lambda: True,
    ) -> None:
        self._mode = mode
        self._clock = clock
        self._release_after = release_after
        self._gpu_idle = gpu_idle
        self._active = False
        self._wrote_speech = False  # a speech write may still take effect
        self._written: str | None = None
        self._force = False
        self._last_write = 0.0
        self._last_seen = 0.0
        shared = mode.read().get("mode") == "shared"
        self.state = SessionState.SHARED if shared else SessionState.OFF

    async def open(self) -> SessionState:
        if self._mode.read().get("mode") == "shared":
            self.state = SessionState.SHARED
            return self.state
        self._active = True
        self._last_seen = self._clock()
        self._force = True  # open always writes
        self._sync(trust_failed=False)
        return self.state

    async def keepalive(self) -> SessionState:
        if self._active:
            self._last_seen = self._clock()
        self._sync()
        return self.state

    async def tick(self) -> None:
        self._sync()

    def _write(self, mode: str) -> None:
        self._mode.request(mode)
        self._written = mode
        self._force = False
        self._last_write = self._clock()
        if mode == "speech":
            self._wrote_speech = True

    def _sync(self, trust_failed: bool = True) -> None:
        info = self._mode.read()
        if info.get("mode") == "shared":
            self._active = self._wrote_speech = False
            self.state = SessionState.SHARED
            return
        now = self._clock()
        if self._active and now - self._last_seen >= self._release_after:
            self._active = False
        if trust_failed and self._active and info.get("state") == "failed":
            self._active = self._wrote_speech = False
            self._written = None
            self.state = SessionState.OFF
            return
        if not self._active and not self._wrote_speech:
            self.state = SessionState.OFF
            return

        desired = "speech" if self._active else "full"
        if desired == "full" and not self._gpu_idle():
            self.state = SessionState.SWITCHING  # reconcile unloads; `full` waits for it
            return
        mode, status = info.get("mode"), info.get("state")
        reopened = False  # speech re-requested while a full write is outstanding
        if self._force or self._written != desired or (
            mode != desired and status != "switching" and now - self._last_write >= RETRY_EVERY
        ):
            reopened = desired == "speech" and self._written == "full"
            self._write(desired)
            info = self._mode.read()
            mode, status = info.get("mode"), info.get("state")

        refused = bool(info.get("busy")) and status == "ready" and mode != desired
        if desired == "full":
            if mode == "full" and status == "ready":
                self._wrote_speech = False
                self._written = None
                self.state = SessionState.OFF
            else:
                self.state = SessionState.SWITCHING
        elif refused:
            self.state = SessionState.BUSY
        elif mode == "speech" and status == "ready" and not reopened:
            self.state = SessionState.READY
        else:
            self.state = SessionState.SWITCHING
