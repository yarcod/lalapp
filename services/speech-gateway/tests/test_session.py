import asyncio
import functools
import json

import pytest

from gateway.session import FileModeControl, SessionManager, SessionState


class FakeMode:
    """Mimics ninfer-mode: a write is accepted when idle and refused (busy flag) when busy."""

    def __init__(self, mode="full", busy=False):
        self.mode = mode
        self.busy = busy  # actual ninfer load
        self.flag = False  # busy as of the script's last run
        self.state = "ready"
        self.fail = False
        self.requests = []

    def request(self, mode):
        self.requests.append(mode)
        if self.mode == "shared":
            return
        if mode == self.mode:
            self.flag = False
        elif self.busy:
            self.flag = True
        elif self.fail:
            self.flag, self.state = False, "failed"
        else:
            self.mode, self.flag = mode, False

    def read(self):
        return {"mode": self.mode, "state": self.state, "busy": self.flag}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def sync(fn):
    @functools.wraps(fn)
    def wrapper():
        asyncio.run(fn())

    return wrapper


def make(mode="full", busy=False):
    fake, clock = FakeMode(mode, busy), Clock()
    return fake, clock, SessionManager(fake, clock)


@sync
async def test_open_when_idle_switches_to_speech():
    fake, _, mgr = make()
    assert await mgr.open() in (SessionState.SWITCHING, SessionState.READY)
    assert fake.requests == ["speech"]
    await mgr.tick()
    assert mgr.state == SessionState.READY


@sync
async def test_open_when_busy_reports_busy_and_leaves_ninfer_alone():
    fake, _, mgr = make(busy=True)
    assert await mgr.open() == SessionState.BUSY
    assert fake.mode == "full"


@sync
async def test_stale_busy_flag_does_not_block_open():
    fake, _, mgr = make()
    fake.flag = True
    assert await mgr.open() != SessionState.BUSY
    assert fake.mode == "speech"


@sync
async def test_busy_refusal_retries_every_30s_until_idle():
    fake, clock, mgr = make(busy=True)
    await mgr.open()
    clock.now += 29
    await mgr.tick()
    assert fake.requests == ["speech"]
    clock.now += 1
    await mgr.tick()
    assert fake.requests == ["speech", "speech"]
    assert mgr.state == SessionState.BUSY
    fake.busy = False
    clock.now += 30
    await mgr.tick()
    assert fake.requests == ["speech"] * 3
    assert fake.mode == "speech"
    await mgr.tick()
    assert mgr.state == SessionState.READY


@sync
async def test_keepalive_extends_release():
    fake, clock, mgr = make()
    await mgr.open()
    clock.now += 500
    assert await mgr.keepalive() == SessionState.READY
    clock.now += 500
    await mgr.tick()
    assert fake.requests == ["speech"]
    assert mgr.state == SessionState.READY


@sync
async def test_release_after_600s_requests_full():
    fake, clock, mgr = make()
    await mgr.open()
    clock.now += 599
    await mgr.tick()
    assert fake.requests == ["speech"]
    clock.now += 2
    await mgr.tick()
    assert fake.requests == ["speech", "full"]
    assert mgr.state == SessionState.OFF


@sync
async def test_release_retries_until_idle():
    fake, clock, mgr = make()
    await mgr.open()
    clock.now += 700
    fake.busy = True
    await mgr.tick()
    assert fake.requests == ["speech", "full"]
    assert fake.mode == "speech"
    assert mgr.state == SessionState.READY  # voice stays usable
    clock.now += 29
    await mgr.tick()
    assert fake.requests == ["speech", "full"]
    clock.now += 1
    await mgr.tick()
    assert fake.requests == ["speech", "full", "full"]
    fake.busy = False
    clock.now += 30
    await mgr.tick()
    assert fake.requests == ["speech", "full", "full", "full"]
    assert fake.mode == "full"
    assert mgr.state == SessionState.OFF
    clock.now += 100
    await mgr.tick()
    assert len(fake.requests) == 4


@sync
async def test_open_during_pending_release_requests_speech_again():
    fake, clock, mgr = make()
    await mgr.open()
    clock.now += 700
    fake.busy = True
    await mgr.tick()
    fake.busy = False
    assert await mgr.open() == SessionState.SWITCHING
    assert fake.requests == ["speech", "full", "speech"]
    await mgr.tick()
    assert mgr.state == SessionState.READY
    assert fake.mode == "speech"


@sync
async def test_failed_release_keeps_retrying_full():
    fake, clock, mgr = make()
    await mgr.open()
    clock.now += 700
    fake.fail = True
    await mgr.tick()
    assert fake.requests == ["speech", "full"]
    assert fake.mode == "speech" and fake.state == "failed"
    assert mgr.state != SessionState.READY
    clock.now += 29
    await mgr.tick()
    assert fake.requests == ["speech", "full"]
    clock.now += 1
    await mgr.tick()
    assert fake.requests == ["speech", "full", "full"]
    fake.fail, fake.state = False, "ready"
    clock.now += 30
    await mgr.tick()
    assert fake.mode == "full"
    assert mgr.state == SessionState.OFF


@sync
async def test_small_slice_is_shared_and_never_switches():
    fake, clock, mgr = make(mode="shared", busy=True)
    assert await mgr.open() == SessionState.SHARED
    fake.busy = False
    clock.now += 5000
    await mgr.tick()
    assert await mgr.keepalive() == SessionState.SHARED
    assert fake.requests == []


@sync
async def test_abandoned_busy_session_drops():
    fake, clock, mgr = make(busy=True)
    await mgr.open()
    clock.now += 700
    await mgr.tick()
    assert mgr.state == SessionState.OFF
    assert fake.mode == "full"


@sync
async def test_failed_switch_reports_off():
    fake, _, mgr = make()
    fake.fail = True
    await mgr.open()
    await mgr.tick()
    assert mgr.state == SessionState.OFF
    assert fake.mode == "full"


def test_file_mode_control_missing_state_is_full_not_busy(tmp_path):
    ctl = FileModeControl(tmp_path)
    assert ctl.read() == {"mode": "full", "state": "ready", "busy": False}


def test_file_mode_control_roundtrip(tmp_path):
    ctl = FileModeControl(tmp_path)
    ctl.request("speech")
    assert (tmp_path / "desired-mode").read_text().strip() == "speech"
    (tmp_path / "mode-state.json").write_text(
        json.dumps({"mode": "speech", "state": "ready", "busy": True})
    )
    assert ctl.read() == {"mode": "speech", "state": "ready", "busy": True}


def test_file_mode_control_corrupt_state_is_default(tmp_path):
    (tmp_path / "mode-state.json").write_text("{nope")
    assert FileModeControl(tmp_path).read()["busy"] is False


def test_file_mode_control_rejects_bad_mode(tmp_path):
    with pytest.raises(ValueError):
        FileModeControl(tmp_path).request("shared")
