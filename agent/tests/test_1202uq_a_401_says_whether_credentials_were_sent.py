r"""#1202uq: a 401 that says nothing about credentials cannot be diagnosed, so it gets guessed.

`_on_response` recorded `{url, status, method, type}`. r135's verifier wrote

    "Flow rendered but failed due unexpected ANONYMOUS GET /auth/me 401"

onto ELEVEN of its fifteen delivery-blocking UI flows -- and "anonymous" was an INFERENCE it
had no way to check. Reading the generated client shows it is very likely wrong:

    getMe()   calls /auth/me ONLY when localStorage holds a decodable, unexpired JWT
    request() attaches `Authorization: Bearer <t>` whenever a token exists

so a genuinely anonymous page cannot issue that request at all. The likelier story is a token
left by an earlier flow in the SAME browser context -- and `getStoredUser` checks `exp` but not
the signature, so a token minted by a PREVIOUS run's backend decodes fine and is then rejected
here. The verifier's context is created once per run and never reset (`test_user_runner`,
`visual_fidelity` and `test_user_validation` each open their own; the interactive browser does
not).

THIS IS THE MISSING FACT, NOT A MISSING CAPABILITY -- a correction to my own first reading. I
said no browser tool could clear state; `browser_eval` is called 13,673 times across the corpus
and can run `localStorage.clear()`. It never has: ZERO occurrences in 151 run logs. The agent
had the means all along and no reason to suspect there was anything to clear.

Verified live through the real handler, same page, two fetches:

    GET ... 405  authorization_sent=True     (fetch sent `Authorization: Bearer stale`)
    GET ... 405  authorization_sent=False    (same fetch without it)

NOT COVERED, deliberately: a cookie-borne session. The browser appends `Cookie` after this
header view is taken, and calling a cookie an auth credential would be a guess. Generated
clients use bearer tokens, which is what this sees.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.browser._manager import (  # noqa: E402
    BrowserManager,
    _authorization_sent_1202uq,
)


class _Req:
    def __init__(self, headers, method="GET"):
        self.headers = headers
        self.method = method


class _Resp:
    def __init__(self, status, headers=None, url="http://localhost:8009/auth/me"):
        self.status = status
        self.url = url
        self.request = _Req(headers if headers is not None else {})


class _State:
    def __init__(self):
        self.network_errors = []


class _M:
    def __init__(self):
        self.state = _State()

    _on_response = BrowserManager._on_response


def _record(*responses):
    m = _M()
    for r in responses:
        m._on_response(r)
    return m.state.network_errors


def test_a_401_carrying_a_token_is_distinguishable_from_an_anonymous_one():
    """★ The defect: both were recorded identically, and the verifier guessed."""
    rows = _record(_Resp(401, {"authorization": "Bearer stale"}), _Resp(401, {}))
    assert [r["authorization_sent"] for r in rows] == [True, False], rows


def test_the_header_lookup_is_case_insensitive():
    """Playwright lowercases header names; a capitalised one must not read as absent."""
    assert _authorization_sent_1202uq(_Resp(401, {"authorization": "Bearer x"})) is True


def test_an_empty_authorization_header_is_not_a_credential():
    assert _authorization_sent_1202uq(_Resp(401, {"authorization": ""})) is False


def test_the_existing_fields_are_untouched():
    """★ The property this could most easily have cost: two tools pass these dicts straight
    through to the model, and #362's shape is what they read."""
    rows = _record(_Resp(500, {}, url="http://localhost:8009/api/x"))
    assert set(rows[0]) == {"url", "status", "method", "type", "authorization_sent"}, rows[0]
    assert rows[0]["status"] == 500 and rows[0]["type"] == "http_error"


def test_a_2xx_is_still_not_recorded():
    assert _record(_Resp(204, {"authorization": "Bearer x"})) == []


def test_it_never_raises_inside_the_event_handler():
    """★ It runs in a response callback. A diagnostic that can throw costs the capture it was
    added to improve."""

    class _Hostile:
        status = 401
        url = "http://localhost/x"

        @property
        def request(self):
            raise RuntimeError("detached")

    rows = _record(_Hostile())
    assert rows and rows[0]["authorization_sent"] is False, rows

    class _NoHeaders:
        status = 401
        url = "http://localhost/x"
        request = _Req(None)

    assert _authorization_sent_1202uq(_NoHeaders()) is False


def test_the_tool_description_tells_the_agent_what_to_do_with_it():
    """★ #947's rule, and the reason this ticket is a FACT rather than a new tool: the means
    to act (`browser_eval` -> `localStorage.clear()`) already exists and was never used in
    151 run logs. A field the model cannot interpret changes nothing."""
    import inspect

    from tools.browser.core import BrowserGetNetworkErrorsTool as BrowserNetworkErrorsTool

    desc = str(BrowserNetworkErrorsTool.tool_definition.fget(
        BrowserNetworkErrorsTool.__new__(BrowserNetworkErrorsTool)))
    assert "authorization_sent" in desc, desc[:400]
    assert "localStorage.clear" in desc, desc[:400]
    assert inspect.getsource(BrowserNetworkErrorsTool)  # the class still parses


def test_it_is_domain_agnostic():
    """★ The user's iron rule: it reads one HTTP header and nothing about the app."""
    for url in ("http://localhost:1/auth/me", "http://localhost:2/api/tok1/tok2"):
        assert _authorization_sent_1202uq(_Resp(403, {"authorization": "Bearer x"}, url)) is True
