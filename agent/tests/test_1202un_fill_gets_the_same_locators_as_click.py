r"""#1202un: the framework told the agent CSS selectors are the fallback, then gave fill only the fallback.

`browser_click`'s description ranks locators for the model in so many words --
"PREFERRED locators (stable, recommended): testid, aria_label, role + name" and
"FALLBACK locators: selector, text". `browser_fill` accepted `selector` and `value` and
nothing else, so every form field in every run had to be reached by the locator the framework
itself calls a fallback.

MEASURED across 151 run logs:

    browser_fill   3169 calls   685 failed (21%)   1 locator kind    no retry
    browser_click  2346 calls   545 failed (23%)   5 locator kinds   3 retries

Filling is the MORE used of the two and was given the least. r134's login flow died on
exactly this shape: `browser_fill(input[type='email'], input[name='email'])` -- two CSS
guesses in one call, because there was no way to ask for the field by its label or test id.
Verified live against a running generated app, same field, all six forms:

    testid=auth-email / aria-label=Email / placeholder=Email / label=Email /
    role=textbox name=Email / selector=input[name='email']   -- all filled

THE BUILDER IS SHARED, not copied. Two copies of one rule drift, and this codebase already
carries that scar: #1032 records a duplicated validation normaliser that lost one key and
collapsed six failing flows to "?" in the delivery gate. `_build_locator_1202un` is the single
emitter, asserted below by exercising both tools through it.

RETRY IS DELIBERATELY UNCHANGED. fill retries zero times and click three; that asymmetry is
real, but nothing in the corpus says fill failures are transient, and #647 does not let a
retry count be picked from symmetry alone.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.browser.interaction import (  # noqa: E402
    BrowserClickTool,
    BrowserFillTool,
    _build_locator_1202un,
)


class _Loc:
    def __init__(self, rec):
        self._rec = rec

    @property
    def first(self):
        self._rec["took_first"] = True
        return self

    async def wait_for(self, **kw):
        return None

    async def click(self, **kw):
        self._rec["via"] = "locator"

    async def fill(self, value, **kw):
        self._rec["via"] = "locator"
        self._rec["filled"] = value


class _Page:
    def __init__(self, rec):
        self._rec = rec

    def get_by_role(self, role, name=None):
        self._rec.setdefault("get_by_role", []).append((role, name))
        return _Loc(self._rec)

    def get_by_label(self, label):
        self._rec.setdefault("get_by_label", []).append(label)
        return _Loc(self._rec)

    async def fill(self, sel, value, **kw):
        self._rec["via"] = "selector"
        self._rec.setdefault("fill_selector", []).append(sel)
        self._rec["filled"] = value

    async def click(self, sel, **kw):
        self._rec["via"] = "selector"
        self._rec.setdefault("click_selector", []).append(sel)

    async def wait_for_selector(self, sel, **kw):
        return None

    async def evaluate(self, *a, **k):
        return None

    async def query_selector_all(self, *a, **k):
        return []


class _Browser:
    def __init__(self, page):
        self.state = type("S", (), {"page": page})()


def _fill(rec, **kw):
    tool = BrowserFillTool(_Browser(_Page(rec)))
    return asyncio.run(tool.execute(value="v", **kw))


def test_fill_accepts_every_preferred_locator():
    """★ The defect: the only way in was the one the framework calls a fallback."""
    for kw, expect in (
        ({"testid": "auth-email"}, '[data-testid="auth-email"]'),
        ({"aria_label": "Email"}, '[aria-label="Email"]'),
        ({"placeholder": "Email"}, '[placeholder="Email"]'),
    ):
        rec = {}
        res = _fill(rec, **kw)
        assert rec.get("fill_selector") == [expect], (kw, rec)
        assert rec.get("filled") == "v", (kw, rec)
        assert getattr(res, "success", True), (kw, res)


def test_fill_by_label_uses_the_public_api():
    """★ `label` goes through `get_by_label`, not the undocumented `internal:label=` selector
    string. A locator the framework depends on must not rest on a Playwright internal."""
    rec = {}
    _fill(rec, label="Email")
    assert rec.get("get_by_label") == ["Email"], rec
    assert rec.get("via") == "locator", rec


def test_fill_with_role_and_name_uses_the_api():
    """★ #1202ul's rule reaches fill too: a quoted name in the selector string is an EXACT
    match, and generated apps label fields "Email address"."""
    rec = {}
    _fill(rec, role="textbox", name="Email")
    assert rec.get("get_by_role") == [("textbox", "Email")], rec
    assert rec.get("via") == "locator" and rec.get("took_first") is True, rec


def test_a_css_selector_still_works_and_is_still_unescaped():
    """★ The property this could most easily have cost: every existing caller passes
    `selector`, and #581's unescaping has to survive."""
    rec = {}
    _fill(rec, selector="input[name='email']")
    assert rec.get("fill_selector") == ["input[name='email']"], rec
    # #581 unescapes the quote forms a model emits, not CSS's own bracket escapes -- checked
    # against the real helper rather than assumed.
    rec = {}
    _fill(rec, selector="input\\'a\\'")
    assert rec.get("fill_selector") == ["input'a'"], rec


def test_no_locator_at_all_is_a_clear_failure():
    """Not a crash, and not a silent success on some default."""
    rec = {}
    res = _fill(rec)
    assert getattr(res, "success", True) is False, res
    assert "testid" in str(getattr(res, "error_message", "") or ""), res


def test_click_and_fill_share_one_builder():
    """★ THE STRUCTURAL PROPERTY, asserted rather than trusted. Two copies of one rule drift;
    #1032 in this codebase is a duplicated normaliser that lost one key and blanked six
    records in the delivery gate. Both tools must resolve the same input identically."""
    for kw in ({"testid": "x"}, {"aria_label": "Go"}, {"selector": "#a"}):
        rec_c, rec_f = {}, {}
        asyncio.run(BrowserClickTool(_Browser(_Page(rec_c))).execute(retry=1, timeout=20, **kw))
        _fill(rec_f, **kw)
        assert rec_c.get("click_selector") == rec_f.get("fill_selector"), (kw, rec_c, rec_f)


def test_the_builder_order_is_preferred_before_fallback():
    """When several are passed, the stable one wins -- otherwise the ranking in the tool's own
    description is advice the code does not follow."""
    sel, _, _ = _build_locator_1202un(testid="t", aria_label="a", selector="#s", text="x")
    assert sel == '[data-testid="t"]', sel
    sel, _, _ = _build_locator_1202un(aria_label="a", selector="#s")
    assert sel == '[aria-label="a"]', sel


def test_it_is_domain_agnostic():
    """★ The user's iron rule: every value is embedded verbatim, never interpreted."""
    sel, typ, rq = _build_locator_1202un(role="tok1", name="tok2 tok3")
    assert rq == ("role", "tok1", "tok2 tok3") and "tok2 tok3" in sel, (sel, rq)
    sel, _, q = _build_locator_1202un(label="tok4")
    assert q == ("label", "tok4") and "tok4" in sel, (sel, q)


def test_nothing_passed_returns_the_empty_triple():
    assert _build_locator_1202un() == (None, None, None)
