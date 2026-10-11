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


# ------------------------------- #1203hn: the count is of CONSECUTIVE deaths ------------
#
# #1198's own distinction is "a flake, not a crash loop", but the count it kept was for the
# whole process, so a run was penalised for doing browser work. MEASURED over every log on
# disk: 78 rebuilds across 42 runs, dominated by the Playwright driver exhausting Node's
# heap -- 36 occurrences across 29 runs, and the driver's own GC report gives its uptime at
# death: MINIMUM 693 seconds, median 4588, longest 10479. Of the 35 gaps between consecutive
# rebuilds, 10 are under 60 seconds; those are the crash loops. r119, r120 and r171 all
# reached the cap, r171 one death short of losing every browser gate in a run that cut 5
# releases. Projected with the reset: consecutive peak 3, no run reaches the cap.


class _Clock1203hn:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def advance(self, s):
        self.t += s


def _kill(m):
    m.state.browser = _FakeBrowser(alive=False)
    m.state.page = _FakePage(alive=False)
    m.state.context = _FakeContext(alive=False)


def _install_clock_1203hn(monkeypatch):
    clock = _Clock1203hn()
    monkeypatch.setattr(bm, "_time1203hn", clock)
    return clock


def test_deaths_spaced_further_apart_than_the_reset_never_reach_the_cap(monkeypatch, tmp_path):
    """The r171 case: three heap deaths, each after an hour of work, are three incidents."""
    _install_fake(monkeypatch)
    clock = _install_clock_1203hn(monkeypatch)
    m = _manager(tmp_path)
    for _ in range(bm._MAX_RELAUNCH_1198 * 3):
        clock.advance(bm._RELAUNCH_RESET_AFTER_SEC_1203HN + 1)
        _kill(m)
        assert asyncio.run(m.ensure_browser()) is True
    assert m._relaunch_count_1198 == 1, m._relaunch_count_1198


def test_a_crash_loop_inside_the_window_still_stops(monkeypatch, tmp_path):
    """The guard must keep every case it was built for."""
    _install_fake(monkeypatch)
    clock = _install_clock_1203hn(monkeypatch)
    m = _manager(tmp_path)
    for _ in range(bm._MAX_RELAUNCH_1198):
        clock.advance(bm._RELAUNCH_RESET_AFTER_SEC_1203HN / 10.0)
        _kill(m)
        assert asyncio.run(m.ensure_browser()) is True
    clock.advance(bm._RELAUNCH_RESET_AFTER_SEC_1203HN / 10.0)
    _kill(m)
    assert asyncio.run(m.ensure_browser()) is False


def test_one_long_gap_does_not_forgive_a_loop_that_follows_it(monkeypatch, tmp_path):
    """The reset compares against the LAST rebuild, not the first: a quiet hour then a loop
    is still a loop."""
    _install_fake(monkeypatch)
    clock = _install_clock_1203hn(monkeypatch)
    m = _manager(tmp_path)
    clock.advance(3600)
    _kill(m)
    assert asyncio.run(m.ensure_browser()) is True
    for _ in range(bm._MAX_RELAUNCH_1198 - 1):
        clock.advance(1.0)
        _kill(m)
        assert asyncio.run(m.ensure_browser()) is True
    clock.advance(1.0)
    _kill(m)
    assert asyncio.run(m.ensure_browser()) is False


def test_a_gap_exactly_at_the_threshold_is_still_the_same_incident(monkeypatch, tmp_path):
    """`>` not `>=`: the boundary belongs to the loop, so the guard stays the stricter one."""
    _install_fake(monkeypatch)
    clock = _install_clock_1203hn(monkeypatch)
    m = _manager(tmp_path)
    for _ in range(bm._MAX_RELAUNCH_1198):
        clock.advance(bm._RELAUNCH_RESET_AFTER_SEC_1203HN)
        _kill(m)
        assert asyncio.run(m.ensure_browser()) is True
    clock.advance(bm._RELAUNCH_RESET_AFTER_SEC_1203HN)
    _kill(m)
    assert asyncio.run(m.ensure_browser()) is False


def test_the_reset_reads_the_constant(monkeypatch, tmp_path):
    """Structural: a hardcoded 60 would pass every assertion above. Move the constant and
    the behaviour must move with it."""
    import inspect
    src = inspect.getsource(bm.BrowserManager.ensure_browser)
    assert "_RELAUNCH_RESET_AFTER_SEC_1203HN" in src, src[:400]

    _install_fake(monkeypatch)
    clock = _install_clock_1203hn(monkeypatch)
    monkeypatch.setattr(bm, "_RELAUNCH_RESET_AFTER_SEC_1203HN", 5.0)
    m = _manager(tmp_path)
    for _ in range(bm._MAX_RELAUNCH_1198 * 2):
        clock.advance(6.0)                      # > the moved threshold
        _kill(m)
        assert asyncio.run(m.ensure_browser()) is True
    assert m._relaunch_count_1198 == 1


def test_the_first_death_of_a_process_is_not_a_reset_candidate(monkeypatch, tmp_path):
    """No previous rebuild to compare against; the count must start at 1, not 0."""
    _install_fake(monkeypatch)
    _install_clock_1203hn(monkeypatch)
    m = _manager(tmp_path)
    _kill(m)
    assert asyncio.run(m.ensure_browser()) is True
    assert m._relaunch_count_1198 == 1
