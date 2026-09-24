r"""#1198: a dead shared browser driver is rebuilt instead of poisoning the rest of the run.

`ensure_browser` asked one question — `self.state.browser is None` — and a driver that has
DIED leaves a perfectly non-None object behind. So the check passed forever and every later
call failed instantly against a dead pipe. Nothing in the module recovered: `is_connected`
and `is_closed` appeared nowhere, and `state.browser` was never reset outside the explicit
`close()`.

Measured on r26, where all 12 browser_test_user lanes share this one manager:

    Navigation failed: Page.goto: Connection closed while reading from the driver   214
    Navigation failed: Page.goto: net::ERR_ABORTED                                   10
    Navigation to "<url>" is interrupted by another navigation                        5
    Navigation failed: Page.goto: net::ERR_CONNECTION_REFUSED                         3

214 of 232 are one line. The first one comes back in **7ms**, right after asyncio logs
`pipe closed by peer` — the pipe was already gone, so this is not a timeout and no navigation
budget (#1189) can help. From that moment every UI gate in the run is blind, and the lanes
spend ticks debating evidence that no longer exists: r26's final three login failures read
`browser_navigate closed the driver before login_pa...` — the product was fine.

Why the check is a round-trip, not just `is_connected()`: the flag can still report True over
a pipe whose peer is gone. One `page.title()` is what comes back instantly when it is.

Same class as #234, one step later in the lifecycle: #234 healed a MISSING browser binary and
returned; a browser that STARTED and then died had no path at all. Bounded at
_MAX_RELAUNCH_1198 — a death is a flake worth one retry, a crash loop is not.
"""

import asyncio

import pytest

from env_generator.llm_generator.tools.browser import _manager as bm


class _FakePage:
    def __init__(self, alive=True):
        self.alive = alive
        self.closed = False

    def is_closed(self):
        return self.closed

    async def title(self):
        if not self.alive:
            raise Exception("Connection closed while reading from the driver")
        return "ok"

    async def close(self):
        self.closed = True

    def on(self, *_a, **_k):
        pass


class _FakeBrowser:
    def __init__(self, alive=True):
        self.alive = alive
        self.closed = False

    def is_connected(self):
        return self.alive

    async def new_context(self, **_k):
        return _FakeContext()

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, alive=True):
        self.alive = alive

    async def new_page(self):
        return _FakePage()

    async def cookies(self):
        # #1199c: the liveness probe asks the CONTEXT, not the page — both raise on a dead
        # driver, but cookies() costs 2.1ms against title()'s 17.3ms and this runs on every
        # browser tool call.
        if not self.alive:
            raise Exception("Target page, context or browser has been closed")
        return []

    async def close(self):
        pass


class _FakePlaywright:
    def __init__(self, counter):
        self.counter = counter
        self.chromium = self
        self.stopped = False

    async def launch(self, **_k):
        self.counter.append(1)
        return _FakeBrowser()

    async def stop(self):
        self.stopped = True


def _install_fake(monkeypatch):
    """Replace the real playwright entry point; returns the list of launches."""
    launches = []

    class _Starter:
        async def start(self):
            return _FakePlaywright(launches)

    monkeypatch.setattr(bm, "async_playwright", lambda: _Starter())
    monkeypatch.setattr(bm, "PLAYWRIGHT_AVAILABLE", True)
    return launches


def _manager(tmp_path):
    m = bm.BrowserManager(workspace_root=tmp_path)
    return m


# ------------------------------------------------------------------- the recovery itself

def test_a_dead_driver_is_discarded_and_relaunched(monkeypatch, tmp_path):
    launches = _install_fake(monkeypatch)
    m = _manager(tmp_path)
    dead = _FakeBrowser(alive=False)
    m.state.browser = dead
    m.state.page = _FakePage(alive=False)
    m.state.context = _FakeContext(alive=False)

    assert asyncio.run(m.ensure_browser()) is True
    assert len(launches) == 1                 # rebuilt, not reused
    assert m.state.browser is not dead
    assert m.state.browser.is_connected()


def test_a_pipe_that_died_under_a_still_connected_flag_is_caught(monkeypatch, tmp_path):
    """`is_connected()` can report True over a dead pipe — the round-trip is the real test."""
    launches = _install_fake(monkeypatch)
    m = _manager(tmp_path)
    m.state.browser = _FakeBrowser(alive=True)      # flag lies
    m.state.page = _FakePage(alive=True)
    m.state.context = _FakeContext(alive=False)     # round-trip tells the truth

    assert asyncio.run(m._driver_is_live_1198()) is False
    assert asyncio.run(m.ensure_browser()) is True
    assert len(launches) == 1


def test_a_live_driver_is_left_alone(monkeypatch, tmp_path):
    launches = _install_fake(monkeypatch)
    m = _manager(tmp_path)
    live = _FakeBrowser(alive=True)
    m.state.browser = live
    m.state.page = _FakePage(alive=True)
    m.state.context = _FakeContext(alive=True)

    assert asyncio.run(m.ensure_browser()) is True
    assert launches == []                      # no relaunch
    assert m.state.browser is live             # same session, same cookies


def test_a_first_start_is_unchanged(monkeypatch, tmp_path):
    launches = _install_fake(monkeypatch)
    m = _manager(tmp_path)
    assert asyncio.run(m.ensure_browser()) is True
    assert len(launches) == 1


# ---------------------------------------------------------------------------- the bound

def test_a_crash_loop_stops_instead_of_relaunching_forever(monkeypatch, tmp_path):
    """Relaunching into a crash loop would burn the run's ticks re-dying instead of saying so."""
    _install_fake(monkeypatch)
    m = _manager(tmp_path)
    for _ in range(bm._MAX_RELAUNCH_1198):
        m.state.browser = _FakeBrowser(alive=False)
        m.state.page = _FakePage(alive=False)
        m.state.context = _FakeContext(alive=False)
        assert asyncio.run(m.ensure_browser()) is True

    m.state.browser = _FakeBrowser(alive=False)
    m.state.page = _FakePage(alive=False)
    m.state.context = _FakeContext(alive=False)
    assert asyncio.run(m.ensure_browser()) is False


# ------------------------------------------------------------------------ never raises

def test_discarding_a_driver_whose_handles_raise_is_survivable(monkeypatch, tmp_path):
    """The handles belong to a process that is already gone; closing them routinely raises."""
    _install_fake(monkeypatch)
    m = _manager(tmp_path)

    class _Hostile:
        def is_connected(self):
            raise Exception("Connection closed while reading from the driver")

        async def close(self):
            raise Exception("Target closed")

    m.state.browser = _Hostile()
    m.state.page = _Hostile()
    asyncio.run(m._discard_dead_driver_1198())
    assert m.state.browser is None
    assert m.state.page is None
