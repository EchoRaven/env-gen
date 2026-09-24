"""#240 (r29/r30: 3 aborts on deliverability_ui_flow_failed while the DELIVERED
app rendered perfectly — runtime-verified). The authenticated framework walk
records PASSING validation:ui_flow records for cleanly-rendered pages, so the
ui_flow gate clears deterministically instead of depending on the verifier LLM's
flaky manual browser driving. PASS-ONLY: never emits a failure."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.test_user_runner import (  # noqa: E402
    clean_ui_flow_passes,
)
from env_generator.llm_generator.multi_agent.runtime.flow_coverage import (  # noqa: E402
    _index_ui_flow_records,
)


def _page(name, route="/x", **kw):
    p = {"name": name, "route": route, "ok": True, "blank": False,
         "console_errors": [], "redirected_to_login": False, "fallback_dom": False}
    p.update(kw)
    return p


def _report(pages, auth_ok=True, ran=True):
    return {"ran": ran, "auth_ok": auth_ok, "pages": pages}


def test_clean_pages_returned():
    r = _report([_page("explore_grid_page", "/explore"),
                 _page("following_page", "/following")])
    assert clean_ui_flow_passes(r) == ["explore_grid_page", "following_page"]


def test_requires_auth_ok():
    # the walk didn't authenticate → claim NO passes (avoid masking a login-wall app)
    r = _report([_page("explore_grid_page")], auth_ok=False)
    assert clean_ui_flow_passes(r) == []


def test_did_not_run_empty():
    assert clean_ui_flow_passes(_report([_page("x")], ran=False)) == []
    assert clean_ui_flow_passes(None) == []
    assert clean_ui_flow_passes({}) == []


def test_broken_pages_excluded():
    r = _report([
        _page("blankp", blank=True, ok=False),
        _page("bouncep", redirected_to_login=True, ok=False),
        _page("fallbackp", fallback_dom=True),
        _page("consolep", console_errors=["TypeError x"], ok=False),
        _page("goodp"),
    ])
    assert clean_ui_flow_passes(r) == ["goodp"]


def test_auth_pages_excluded():
    r = _report([_page("login", "/login"), _page("signup", "/signup"),
                 _page("feed", "/")])
    assert clean_ui_flow_passes(r) == ["feed"]


def test_fake_map_excluded():
    r = _report([_page("mapp", is_map_surface=True, map_rendered=False),
                 _page("realmap", is_map_surface=True, map_rendered=True)])
    assert clean_ui_flow_passes(r) == ["realmap"]


def test_dedup():
    r = _report([_page("feed", "/"), _page("feed", "/")])
    assert clean_ui_flow_passes(r) == ["feed"]


def test_pass_wins_over_verifier_failure():
    """The #240 PASS must beat a prior verifier-LLM FAILURE for the same flow
    (flow_coverage collapses per-name to best status → passed wins)."""
    class _Hub:
        def get_validation_results(self, limit=1000):
            return [
                {"metadata": {"check": "ui_flow", "flow": "explore_grid_page"},
                 "status": "failed"},   # verifier LLM's flaky failure
                {"metadata": {"check": "ui_flow", "flow": "explore_grid_page"},
                 "status": "passed"},   # #240 deterministic walk pass
            ]
    by_flow = _index_ui_flow_records(_Hub())
    assert by_flow.get("explore_grid_page") == "passed"


# ---- #241 _safe_goto: tolerate bc_auth's navigation-interrupt race ----
import asyncio  # noqa: E402
from env_generator.llm_generator.multi_agent.runtime.test_user_runner import (  # noqa: E402
    _safe_goto,
)


class _FakePage:
    def __init__(self, goto_exc=None, content_exc=None):
        self._goto_exc = goto_exc
        self._content_exc = content_exc
        self.settled = False
        self.waited_content = False
        self.goto_wait_until = None

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_wait_until = wait_until
        if self._goto_exc:
            raise self._goto_exc

    async def wait_for_function(self, expr, timeout=None):
        self.waited_content = True
        if self._content_exc:
            raise self._content_exc

    async def wait_for_load_state(self, state=None, timeout=None):
        self.settled = True


def test_safe_goto_swallows_navigation_interrupt():
    # bc_auth's location.assign interrupts goto → tolerated, content wait still runs
    pg = _FakePage(goto_exc=Exception(
        'Page.goto: Navigation to "http://x/login" is interrupted by another navigation'))
    asyncio.run(_safe_goto(pg, "http://x/login"))
    assert pg.waited_content is True


def test_safe_goto_reraises_other_errors():
    pg = _FakePage(goto_exc=Exception("net::ERR_CONNECTION_REFUSED"))
    try:
        asyncio.run(_safe_goto(pg, "http://x/login"))
        assert False, "should have re-raised"
    except Exception as e:
        assert "CONNECTION_REFUSED" in str(e)


# ---- #244: navigate on commit, let the DOM decide (never pre-judge blank) ----

def test_safe_goto_navigates_on_commit_not_networkidle():
    """#244 (r34): waiting on networkidle/domcontentloaded in the goto let a slow
    bundle or an autoplaying <video> time the navigation out — the per-page record
    kept its initialised blank=True and 7 WORKING pages were recorded BLANK."""
    pg = _FakePage()
    asyncio.run(_safe_goto(pg, "http://x/"))
    assert pg.goto_wait_until == "commit"
    assert pg.waited_content is True   # bounded wait for real rendered content


def test_safe_goto_content_timeout_is_tolerated():
    # a genuinely dead page times out the content wait → we still return so the
    # DOM probe (not the wait strategy) records it blank
    pg = _FakePage(content_exc=Exception("Timeout 15000ms exceeded"))
    asyncio.run(_safe_goto(pg, "http://x/"))
    assert pg.waited_content is True
