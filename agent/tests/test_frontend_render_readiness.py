"""FIX #159 (gmrun7 M1) — the browser readiness gate must wait for the SPA to MOUNT,
not merely for the server to respond.

gmrun7 M1 deferred delivery on a FALSE `blank=['login']`: the browser test-user walk fired
while the frontend container was mid Vite-rebuild — the dev server returned the index.html
shell (HTTP 200) but the JS bundle wasn't ready, so the SPA hadn't mounted → `document.body`
was empty → textLen < 12 → login flagged blank → auth_ok=False → a spurious P0 to the
frontend + a wasted deferral cycle. Playwright-verified the SAME /login renders fine once
settled (textLen=41, a real form). `_wait_frontend_ready` returned True on the first
`< 500` response (`wait_until="commit"`), never checking that React actually rendered.

Fix: after the server responds, poll until the SPA appears MOUNTED (React root has children
/ body has text). A genuinely-blank app still proceeds after the budget (so the walk still
catches a real blank — readiness must never SUPPRESS a true defect). A probe error degrades
to "ready" (never block readiness on an un-probeable page). LOCAL-ONLY (agent/tests/).
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import (  # noqa: E402
    _wait_frontend_ready, _frontend_rendered)


class _Resp:
    def __init__(self, status=200):
        self.status = status


class _RenderPage:
    """goto returns 200; the SPA-mount probe (`evaluate`) returns False for the first
    ``unmounted_n`` calls, then True — unless ``ever_mounts`` is False (a genuine blank)."""
    def __init__(self, unmounted_n=0, ever_mounts=True):
        self.goto_calls = 0
        self.eval_calls = 0
        self.unmounted_n = unmounted_n
        self.ever_mounts = ever_mounts

    async def goto(self, url, **kw):
        self.goto_calls += 1
        return _Resp(200)

    async def evaluate(self, fn):
        self.eval_calls += 1
        if not self.ever_mounts:
            return False
        return self.eval_calls > self.unmounted_n

    async def wait_for_timeout(self, ms):
        return None


class _EvalRaisesPage:
    def __init__(self):
        self.goto_calls = 0

    async def goto(self, url, **kw):
        self.goto_calls += 1
        return _Resp(200)

    async def evaluate(self, fn):
        raise RuntimeError("execution context was destroyed")

    async def wait_for_timeout(self, ms):
        return None


# ---------------------------- _frontend_rendered ----------------------------

def test_rendered_true_when_mounted():
    pg = _RenderPage(unmounted_n=0)
    assert asyncio.run(_frontend_rendered(pg)) is True


def test_rendered_false_when_unmounted():
    pg = _RenderPage(unmounted_n=99)  # evaluate returns False
    assert asyncio.run(_frontend_rendered(pg)) is False


def test_rendered_degrades_true_on_probe_error():
    # a page we cannot probe (no evaluate / it raises) must not block readiness
    assert asyncio.run(_frontend_rendered(_EvalRaisesPage())) is True

    class _NoEval:
        pass
    assert asyncio.run(_frontend_rendered(_NoEval())) is True


# --------------------------- _wait_frontend_ready ---------------------------

def test_waits_for_spa_mount_then_ready():
    pg = _RenderPage(unmounted_n=2)  # shell served but unmounted for 2 polls, then mounts
    ok = asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=8, gap_ms=0))
    assert ok is True
    assert pg.goto_calls == 3, "must keep polling the served-but-unmounted shell until it mounts"


def test_genuine_blank_proceeds_after_budget():
    # server up, SPA NEVER mounts (a real blank app): readiness must return True after the
    # budget so the WALK runs and catches the genuine blank — never suppress a true defect.
    pg = _RenderPage(ever_mounts=False)
    ok = asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=5, gap_ms=0))
    assert ok is True
    assert pg.goto_calls == 5, "polled the full budget waiting for a mount that never came"


def test_probe_error_still_ready_on_first_serve():
    # if the render probe can't run, fall back to the old server-responds signal (no regression)
    pg = _EvalRaisesPage()
    ok = asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=5, gap_ms=0))
    assert ok is True
    assert pg.goto_calls == 1


# ------------------------- existing-behavior regression -------------------------

class _ConnRefusedPage:
    def __init__(self, fail_n, status=200):
        self.calls = 0
        self.fail_n = fail_n
        self.status = status

    async def goto(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise Exception("net::ERR_CONNECTION_REFUSED")
        return _Resp(self.status)

    async def evaluate(self, fn):
        return True  # mounted

    async def wait_for_timeout(self, ms):
        return None


def test_connection_refused_never_ready():
    pg = _ConnRefusedPage(fail_n=99)
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=5, gap_ms=0)) is False
    assert pg.calls == 5


def test_5xx_never_sets_served():
    pg = _ConnRefusedPage(fail_n=0, status=503)
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=3, gap_ms=0)) is False


def test_ready_after_restarts_then_mount():
    pg = _ConnRefusedPage(fail_n=3)  # down 3 polls, then up + mounted
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=8, gap_ms=0)) is True
    assert pg.calls == 4
