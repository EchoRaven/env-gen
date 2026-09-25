r"""#1202ul: `role + name` was built into a selector string that matches the name EXACTLY.

The role branch of `browser_click` built `role=button[name="Like"]`. That is Playwright's
selector-engine form, where a quoted `name` is an EXACT match. The API the tool's own
description advertises -- "role + name: ARIA role with accessible name" -- is
`page.get_by_role("button", name="Like")`, which defaults to a case-insensitive SUBSTRING.
The two disagree on exactly the labels generated apps produce.

MEASURED on a live generated app (r132), one page, one button:

    role=button[name="Like"]              -> 0 matches
    get_by_role("button", name="Like")    -> 1   (the control is labelled "Like video")
    get_by_role("button", name="Comment") -> 1   (the control is labelled "Open comments")
    get_by_role("button", name="Toggle")  -> 1   (the control is labelled "Toggle sound")

ACROSS THE CORPUS: 2287 `aria-label`s in generated frontends, 927 of them (40%) multi-word
verb-object labels -- "Previous video", "Close comments", "Add to My List", "Email address",
"Forward 10 seconds", "Rewind 10 seconds" -- across TikTok, Netflix and the rest. And 814 of
2337 `browser_click` calls (34%), over 60 runs, pass role+name.

THE COST, in r134: eight delivery-blocking `ui_flow` checks reading "cannot locate accessible
Like/Comment/Follow control", while the control was on screen in the check's own saved
screenshot and carried the label in source. The frontend was sent P0s to add labels that were
already there, reported them fixed, and the rerun read the same miss.

`.first` is deliberate: `page.click(selector)` was never strict, and `get_by_role` returns a
strict Locator whose `.click()` RAISES on two matches. Taking the first keeps the semantics
every other branch already had instead of trading a miss for a new class of failure.

DOMAIN-AGNOSTIC: the branch passes the agent's own role and name through untouched. It reads
nothing about what a control means, asserted below with opaque tokens.

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

from tools.browser.interaction import BrowserClickTool  # noqa: E402


class _Loc:
    def __init__(self, rec, ok=True):
        self._rec, self._ok = rec, ok

    @property
    def first(self):
        self._rec["took_first"] = True
        return self

    async def wait_for(self, **kw):
        return None

    async def click(self, **kw):
        if not self._ok:
            raise TimeoutError("Timeout 5000ms exceeded")
        self._rec["clicked_via"] = "locator"


class _Page:
    def __init__(self, rec, role_ok=True, role_raises=False):
        self._rec, self._role_ok, self._role_raises = rec, role_ok, role_raises

    def get_by_role(self, role, name=None):
        self._rec.setdefault("get_by_role", []).append((role, name))
        if self._role_raises:
            raise ValueError("unknown role")
        return _Loc(self._rec, ok=self._role_ok)

    async def wait_for_selector(self, sel, **kw):
        self._rec.setdefault("wait_selector", []).append(sel)

    async def click(self, sel, **kw):
        self._rec.setdefault("click_selector", []).append(sel)
        self._rec["clicked_via"] = "selector"

    async def evaluate(self, *a, **k):
        return None

    async def query_selector_all(self, *a, **k):
        return []


class _State:
    def __init__(self, page):
        self.page = page


class _Browser:
    def __init__(self, page):
        self.state = _State(page)


def _click(rec, page, **kw):
    tool = BrowserClickTool(_Browser(page))
    return asyncio.run(tool.execute(retry=1, timeout=50, **kw))


def test_role_and_name_go_through_get_by_role():
    """★ The defect: the exact-match string is what made r134's eight flows unreachable."""
    rec = {}
    res = _click(rec, _Page(rec), role="button", name="Like")
    assert rec.get("get_by_role") == [("button", "Like")], rec
    assert rec.get("clicked_via") == "locator", rec
    assert getattr(res, "success", True), res


def test_it_takes_the_first_match():
    """★ The property the change could most easily have cost: `page.click` was never strict,
    and a strict Locator turns two matches into a raise."""
    rec = {}
    _click(rec, _Page(rec), role="button", name="Like")
    assert rec.get("took_first") is True, rec


def test_role_without_a_name_still_works():
    rec = {}
    _click(rec, _Page(rec), role="button")
    assert rec.get("get_by_role") == [("button", None)], rec


def test_an_unknown_role_falls_back_to_the_string_form():
    """A construction failure must cost the widening, not the attempt."""
    rec = {}
    _click(rec, _Page(rec, role_raises=True), role="nonsense", name="Like")
    assert rec.get("clicked_via") == "selector", rec
    assert rec.get("click_selector") == ['role=nonsense[name="Like"]'], rec


def test_the_other_branches_are_untouched():
    """★ testid, aria_label, selector and text must behave exactly as before -- only the role
    branch changed."""
    for kw, expect in (
        ({"testid": "like-button"}, '[data-testid="like-button"]'),
        ({"aria_label": "Like"}, '[aria-label="Like"]'),
        ({"selector": "#go"}, "#go"),
        ({"text": "Log in"}, "text=Log in"),
    ):
        rec = {}
        _click(rec, _Page(rec), **kw)
        assert rec.get("clicked_via") == "selector", (kw, rec)
        assert rec.get("click_selector") == [expect], (kw, rec)
        assert "get_by_role" not in rec, (kw, rec)


def test_it_is_domain_agnostic():
    """★ The user's iron rule: role and name are passed through, never interpreted."""
    rec = {}
    _click(rec, _Page(rec), role="tok1", name="tok2 tok3")
    assert rec.get("get_by_role") == [("tok1", "tok2 tok3")], rec


def test_a_miss_still_reports_a_failure():
    """The fallback must not turn a genuine miss into a silent success."""
    rec = {}
    res = _click(rec, _Page(rec, role_ok=False), role="button", name="Nope")
    assert getattr(res, "success", True) is False, res
