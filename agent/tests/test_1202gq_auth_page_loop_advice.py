"""#1202gq — the projection-loop task gives auth pages advice that cannot work.

`#1202at` tells the frontend lane why its page keeps vanishing and how to keep it:

    "the projector KEEPS a page that imports from `../components/` and REPLACES one that
     does not (#914/#1020). Move the page body into a component under `src/components/`..."

That is `_imports_own_components` — literally `"../components/" in src`. But an AUTH page is
not governed by it. `scaffold_pages_from_contract`'s auth branch asks
`_lane_auth_page_is_live_1197`, which is `wired and drivable and persists`, evaluated over the
page's whole depth-2 import bundle. So for a login/signup page the stated rule is neither
sufficient (a component-based login that never calls /auth/* is still replaced) nor necessary
(a self-contained login that is wired, drivable and persists is kept).

The live cost: r97 filed "Keep N page(s) the projector keeps overwriting" naming `LoginPage`
SEVEN times, and #1197's own comment records r26 clobbering LoginPage 87 times and SignupPage
58. The lane follows the advice it was given and loses the page again — the framework holds
the fact that this page is an auth page, and reports the generic category anyway.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.scaffolder import _loop_page_advice_1202gq  # noqa: E402


def test_an_auth_page_is_told_the_rule_that_actually_governs_it():
    text = _loop_page_advice_1202gq(["LoginPage"], {})
    low = text.lower()
    assert "login" in low
    for word in ("wired", "drivable", "persist"):
        assert word in low, "the auth rule's %r condition is missing:\n%s" % (word, text)
    assert "/auth/" in text, "the lane is not told which endpoints count as wired:\n%s" % text


def test_the_component_rule_is_not_offered_as_the_way_to_keep_an_auth_page():
    """The whole defect: `../components/` is not what the auth branch asks."""
    text = _loop_page_advice_1202gq(["LoginPage"], {})
    head, _, tail = text.partition("LoginPage")
    assert "../components/" not in head, (
        "the component rule is still stated as the way to keep an auth page:\n%s" % text)


def test_a_non_auth_page_keeps_the_advice_that_was_already_correct():
    text = _loop_page_advice_1202gq(["GenresPage"], {})
    assert "../components/" in text, "the #914/#1020 rule was lost for ordinary pages:\n%s" % text
    assert "914" in text or "1020" in text


def test_a_mixed_loop_gets_both_rules_and_says_which_page_takes_which():
    text = _loop_page_advice_1202gq(["GenresPage", "SignupPage"], {})
    assert "../components/" in text and "wired" in text.lower()
    assert "GenresPage" in text and "SignupPage" in text


def test_the_page_record_decides_when_the_name_does_not():
    """A page named `AccessPage` on route /login is still an auth page (#_is_auth_page)."""
    text = _loop_page_advice_1202gq(["AccessPage"], {"AccessPage": {"route": "/login"}})
    assert "wired" in text.lower(), "route-derived auth pages fall back to the wrong rule:\n%s" % text


def test_the_helper_is_the_one_the_task_actually_uses():
    """#1202gp's neighbours died as dead mechanisms; this one has to be wired."""
    src = (LLM / "multi_agent" / "runtime" / "scaffolder.py").read_text(encoding="utf-8")
    at = src.index("Keep %d page(s) the projector keeps overwriting")
    block_start = src.rindex("try:", 0, at)
    block = src[block_start:src.index("assignee=\"frontend\"", at)]
    assert "_loop_page_advice_1202gq(" in block, (
        "the task still builds its own description — the helper is dead code")
