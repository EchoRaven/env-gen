"""#326 — no circuit breaker on a TERMINAL provider error (my LLM-client finding, confirmed by
the orchestrator trajectory reviewer as Orch-F5).

When the metagen key hit its $10k spend cap, every LLM call returned HTTP 400
``{"detail":"Spend exceeded. Budget for mg key ... Spend 10005 >= Budget 10000"}``. The retry
wrapper correctly does NOT treat a 400 as a rate limit, but nothing classified it as TERMINAL:
each call still burned its bounded retries, and — worse — the RUN had no abort signal, so all
four lanes kept issuing fresh calls that were instantly rejected (~4500 agent-level / 6861
LLM-level failed attempts in r93) until the wall-clock cap hours later.

Fix: classify spend/budget/quota-exhaustion + hard-auth (401/403) as terminal → fail the call
immediately (no pointless retries) AND latch a module-level reason a run loop can poll to abort.
A 429 rate limit and an ordinary 400 request error are NOT terminal (still bounded-retry).
"""
import asyncio
import sys
from pathlib import Path

THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS.parent))

import utils.llm as L  # noqa: E402
from utils.config import LLMConfig  # noqa: E402


class _FakeErr(Exception):
    def __init__(self, msg, status_code=None):
        super().__init__(msg)
        if status_code is not None:
            self.status_code = status_code


def test_classifier_terminal_vs_transient():
    T = L._is_terminal_llm_error
    # terminal: billing / quota exhaustion (metagen returns it as a 400)
    assert T(_FakeErr("Spend exceeded. Budget for mg key mg-api-71b4 Spend 10005 >= 10000", 400))
    assert T(_FakeErr("insufficient_quota: you exceeded your current quota", 400))
    assert T(_FakeErr("Payment Required", 402))
    # terminal: hard auth rejection (a bad key won't fix itself)
    assert T(_FakeErr("invalid api key", 401))
    assert T(_FakeErr("forbidden", 403))
    # NOT terminal: 429 rate limit is transient even when it says "exhausted"/"quota"
    assert not T(_FakeErr("Rate limit reached", 429))
    assert not T(_FakeErr("resource_exhausted", 429))
    # NOT terminal: an ordinary 400 request error (bounded-retry handles it)
    assert not T(_FakeErr("400: messages.5 text content must be non-empty", 400))
    assert not T(_FakeErr("connection reset"))


class _Client(L.BaseLLMClient):
    async def chat(self, *a, **k):
        raise NotImplementedError

    async def chat_stream(self, *a, **k):
        raise NotImplementedError
        yield  # pragma: no cover


def _reset():
    L._TERMINAL_LLM_ERROR["reason"] = None


def test_terminal_error_fails_fast_and_latches():
    _reset()
    c = _Client(LLMConfig(retry_attempts=3))
    calls = {"n": 0}

    async def boom():
        calls["n"] += 1
        raise _FakeErr("Spend exceeded. Budget for mg key mg-api-71b41b05af9a", 400)

    try:
        asyncio.run(c._retry_with_backoff(boom))
        assert False, "should have raised"
    except Exception:
        pass
    assert calls["n"] == 1, f"terminal error must NOT be retried, got {calls['n']} calls"
    assert L.terminal_llm_error() is not None
    assert "spend exceeded" in L.terminal_llm_error().lower()
    _reset()


def test_transient_error_still_retried():
    _reset()
    c = _Client(LLMConfig(retry_attempts=3, retry_delay=0.0))
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        raise _FakeErr("connection reset")

    try:
        asyncio.run(c._retry_with_backoff(flaky))
    except Exception:
        pass
    assert calls["n"] == 3, f"a transient error must exhaust retries, got {calls['n']}"
    assert L.terminal_llm_error() is None
    _reset()
