import asyncio
import functools
import json

import pytest

from gateway.session import FileModeControl, SessionManager, SessionState


class FakeMode:
    def __init__(self, mode="full", busy=False):
        self.mode = mode
        self.busy = busy
        self.requests = []

    def request(self, mode):
        self.requests.append(mode)
        if not self.busy and self.mode != "shared":
            self.mode = mode

    def read(self):
        return {"mode": self.mode, "state": "ready", "busy": self.busy}


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
async def test_open_when_busy_reports_busy_and_does_not_request():
    fake, _, mgr = make(busy=True)
    assert await mgr.open() == SessionState.BUSY
    assert fake.requests == []


@sync
async def test_busy_retries_when_idle_on_tick():
    fake, _, mgr = make(busy=True)
    await mgr.open()
    await mgr.tick()
    assert fake.requests == []
    fake.busy = False
    await mgr.tick()
    assert fake.requests == ["speech"]
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
async def test_release_waits_while_busy():
    fake, clock, mgr = make()
    await mgr.open()
    clock.now += 700
    fake.busy = True
    await mgr.tick()
    assert fake.requests == ["speech"]
    fake.busy = False
    await mgr.tick()
    assert fake.requests == ["speech", "full"]
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
async def test_abandoned_busy_session_drops_without_request():
    fake, clock, mgr = make(busy=True)
    await mgr.open()
    clock.now += 700
    await mgr.tick()
    fake.busy = False
    await mgr.tick()
    assert fake.requests == []
    assert mgr.state == SessionState.OFF


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
