"""Fix #68 — the browser test-user re-polls a would-be-blank page before
flagging it (outlook run-56, live 2026-07-03).

run-56 shipped SUCCESS but the browser gate reported 9 FALSE 'blank' pages — the
list was INCONSISTENT between two consecutive walks (outlook_landing blank in one
but not the other), the tell of a render RACE — while a manual 1500ms capture of
the SAME routes (as the seeded admin@example.com user) rendered full content
(inbox rows, calendar grid July 2026). A React page under nested routing + a data
fetch can still be mounting at the gate's 900ms measure. A false blank wastes the
whole 30-min deferral budget, escapes ('loudly'), and files bogus P0 tasks. The
per-page check now re-polls up to ~3.6s more before declaring blank. LOCAL-ONLY
(agent/tests/ gitignored).
"""

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.test_user_runner as tur  # noqa: E402


class _FakeLocator:
    def __init__(self, n=1):
        self._n = n

    async def count(self):
        return self._n


class _FakePage:
    """Scripted page: evaluate() returns textLen from a per-route sequence, so a
    route can be 'blank then content' (slow render) or 'always blank'."""

    def __init__(self, textlen_by_route):
        self._seq = {r: list(v) for r, v in textlen_by_route.items()}
        self.url = "http://app/login"
        self._route = "/login"

    def on(self, *a, **k):
        pass

    async def goto(self, url, **k):
        self._route = url.split("http://app", 1)[-1] or "/"
        self.url = url
        return types.SimpleNamespace(status=200)

    async def wait_for_timeout(self, *a, **k):
        return None

    async def evaluate(self, *a, **k):
        seq = self._seq.get(self._route, [200])
        tl = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"textLen": tl, "sample": "x" * tl, "buttons": 1, "inputs": 1,
                "pw": False, "signin": False}

    def locator(self, *a, **k):
        return _FakeLocator(1)

    async def screenshot(self, **k):
        return b""


class _FakeCtx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_context(self, **k):
        return _FakeCtx(self._page)

    async def close(self):
        pass


class _FakePW:
    def __init__(self, page):
        self.chromium = types.SimpleNamespace(launch=self._launch)
        self._page = page

    async def _launch(self, **k):
        return _FakeBrowser(self._page)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _run(tmp_path, pages, textlen_by_route, monkeypatch):
    page = _FakePage(textlen_by_route)
    monkeypatch.setattr(tur, "async_playwright", lambda: _FakePW(page), raising=False)
    # the function imports async_playwright lazily inside; patch the module the
    # import resolves to
    import playwright.async_api as _pa
    monkeypatch.setattr(_pa, "async_playwright", lambda: _FakePW(page))
    monkeypatch.setattr(tur, "_wait_frontend_ready",
                        lambda *a, **k: _coro(True))
    monkeypatch.setattr(tur, "_wait_api_ready", lambda *a, **k: _coro(True))
    monkeypatch.setattr(tur, "_api_register", lambda *a, **k: True)
    monkeypatch.setattr(tur, "_drive_auth_form", lambda *a, **k: _coro("tok"))
    return asyncio.run(tur.run_browser_test_user(
        "http://app", pages, tmp_path, register=False, api_base_url=None))


def _coro(v):
    async def _c(*a, **k):
        return v
    return _c()


def test_slow_render_page_not_flagged_blank(tmp_path, monkeypatch):
    """A page blank at first measure but content shortly after → NOT blank."""
    pages = [{"name": "inbox", "route": "/mail/inbox", "auth": True}]
    rep = _run(tmp_path, pages, {"/mail/inbox": [5, 5, 200]}, monkeypatch)
    assert rep["ran"]
    inbox = next(p for p in rep["pages"] if p["name"] == "inbox")
    assert inbox["blank"] is False, inbox


def test_genuinely_blank_page_still_flagged(tmp_path, monkeypatch):
    """A page that never renders content stays blank (retry doesn't hide a real
    blank)."""
    pages = [{"name": "stub", "route": "/stub", "auth": True}]
    rep = _run(tmp_path, pages, {"/stub": [3]}, monkeypatch)
    stub = next(p for p in rep["pages"] if p["name"] == "stub")
    assert stub["blank"] is True, stub


def test_immediately_rendered_page_no_retry_needed(tmp_path, monkeypatch):
    pages = [{"name": "cal", "route": "/calendar", "auth": True}]
    rep = _run(tmp_path, pages, {"/calendar": [371]}, monkeypatch)
    cal = next(p for p in rep["pages"] if p["name"] == "cal")
    assert cal["blank"] is False


def test_source_has_retry_loop():
    src = (LLM / "multi_agent" / "runtime" / "test_user_runner.py").read_text(encoding="utf-8")
    assert "#68" in src and "_MIN_TEXT" in src
    # the retry re-polls in a loop after a would-be-blank first read
    i = src.index("_tl = probe.get(\"textLen\", 0)")
    assert "for _ in range(3)" in src[i:i + 400]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
