"""The browser test-user waits for the frontend to be READY and SKIPS (ran=False) if it's
unreachable, instead of false-flagging 'unusable' (outlook run-28 v1.2.0, 2026-07-01).

The delivery flow restarts the compose stack per milestone, so the browser walk can fire
while the frontend container is DOWN → every goto raises net::ERR_CONNECTION_REFUSED →
auth_ok=False + all pages blank → a FALSE 'unusable' that escape-ships a healthy app (live:
the run-28 final walk hit ERR_CONNECTION_REFUSED at /login mid container-restart). The
readiness gate polls until it serves; if it never comes up, ran=False → the gate treats it as
'could not run' (skip, never block). ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import _wait_frontend_ready  # noqa: E402
from multi_agent.runtime.test_user_runner import browser_report_unusable  # noqa: E402


class _Resp:
    def __init__(self, status):
        self.status = status


class _FakePage:
    """Fake Playwright page: goto raises ERR_CONNECTION_REFUSED for the first ``fail_n`` calls,
    then returns a response with ``status``."""
    def __init__(self, fail_n, status=200):
        self.calls = 0
        self.fail_n = fail_n
        self.status = status

    async def goto(self, url, **kw):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise Exception("net::ERR_CONNECTION_REFUSED")
        return _Resp(self.status)

    async def wait_for_timeout(self, ms):
        return None


def test_ready_immediately():
    pg = _FakePage(fail_n=0)
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=5, gap_ms=0)) is True
    assert pg.calls == 1


def test_ready_after_a_few_restarts():
    pg = _FakePage(fail_n=3)  # down for 3 polls, then up
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=8, gap_ms=0)) is True
    assert pg.calls == 4


def test_never_ready_returns_false():
    pg = _FakePage(fail_n=99)  # never comes up
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=5, gap_ms=0)) is False
    assert pg.calls == 5


def test_5xx_is_not_ready():
    pg = _FakePage(fail_n=0, status=503)  # container up but app erroring
    assert asyncio.run(_wait_frontend_ready(pg, "http://x", attempts=3, gap_ms=0)) is False


def test_skipped_report_is_not_unusable():
    """A ran=False (skipped) report must never count as unusable → the gate won't block."""
    assert browser_report_unusable({"ran": False, "auth_ok": False,
                                    "blank_pages": ["a", "b", "c"]}) is False
    assert browser_report_unusable(None) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

# ---- #46: API-base readiness (frontend-up/backend-down window, run-35) ----

def test_api_ready_immediately():
    import asyncio
    from multi_agent.runtime.test_user_runner import _wait_api_ready

    class _Pg:
        async def wait_for_timeout(self, ms):
            return None
    ok = asyncio.run(_wait_api_ready(_Pg(), "http://x", attempts=3, gap_ms=0,
                                     probe=lambda u: True))
    assert ok is True


def test_api_comes_up_mid_wait_then_true():
    import asyncio
    from multi_agent.runtime.test_user_runner import _wait_api_ready
    calls = {"n": 0}

    def probe(u):
        calls["n"] += 1
        return calls["n"] >= 3

    class _Pg:
        async def wait_for_timeout(self, ms):
            return None
    assert asyncio.run(_wait_api_ready(_Pg(), "http://x", attempts=6, gap_ms=0,
                                       probe=probe)) is True
    assert calls["n"] == 3


def test_api_never_ready_false_bounded():
    import asyncio
    from multi_agent.runtime.test_user_runner import _wait_api_ready

    class _Pg:
        async def wait_for_timeout(self, ms):
            return None
    assert asyncio.run(_wait_api_ready(_Pg(), "http://x", attempts=4, gap_ms=0,
                                       probe=lambda u: False)) is False
