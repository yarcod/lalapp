"""Speech session lifecycle: switch ninfer to speech mode on demand, release when idle."""

import json
import os
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

DEFAULT_STATE_DIR = Path("/var/lib/speech-gateway")
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


class FileModeControl:
    """Host contract: write desired-mode, read mode-state.json."""

    def __init__(self, directory: str | Path = DEFAULT_STATE_DIR) -> None:
        self._dir = Path(directory)

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
            return dict(_DEFAULT_READ)
        return {**_DEFAULT_READ, **data}


class SessionManager:
    def __init__(
        self,
        mode: ModeControl,
        clock: Callable[[], float],
        release_after: float = 600.0,
    ) -> None:
        self._mode = mode
        self._clock = clock
        self._release_after = release_after
        self._active = False
        self._requested = False
        self._last_seen = 0.0
        self.state = SessionState.OFF

    async def open(self) -> SessionState:
        self._active = True
        self._last_seen = self._clock()
        self._sync()
        return self.state

    async def keepalive(self) -> SessionState:
        if self._active:
            self._last_seen = self._clock()
        self._sync()
        return self.state

    async def tick(self) -> None:
        self._sync()

    def _sync(self) -> None:
        info = self._mode.read()
        if info.get("mode") == "shared":
            self._requested = False
            self.state = SessionState.SHARED
            return
        busy = bool(info.get("busy"))
        expired = self._clock() - self._last_seen >= self._release_after

        if not self._active:
            self.state = SessionState.OFF
            return

        if expired:
            if busy and self._requested:
                return  # never switch back while busy; try again next tick
            if self._requested:
                self._mode.request("full")
            self._active = self._requested = False
            self.state = SessionState.OFF
            return

        if info.get("mode") == "speech" and info.get("state") == "ready":
            self._requested = True
            self.state = SessionState.READY
        elif self._requested:
            self.state = SessionState.SWITCHING
        elif busy:
            self.state = SessionState.BUSY
        else:
            self._mode.request("speech")
            self._requested = True
            self.state = SessionState.SWITCHING
