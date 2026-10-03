r"""#1203c8: the LLM test-user names the app's user-visible defects, and nobody was told.

`_ui_test_user` drives an LLM through the running app with screenshots and asks, per screen, what
WORKS and what the PROBLEMS are, plus "the 3-5 frictions to fix first". The answers were stored in
`report["ui"]`, written to `test_user_reports/<version>.json`, and read by nothing.

MEASURED: `top_issues` and the per-screen `problems` key each have exactly TWO occurrences in the
tree — the prompt that asks and the line that stores. ZERO readers. The report's consumers are two
`_logger.warning` calls, and both print `describe_non_pass_1038(summary, mcp)`, which reads
`summary.broken` / `summary.missing` / mcp — so these findings did not even reach the log.

Corpus: 969 screen records carry `problems` (967 non-empty) and 690 ranked frictions appear in 151
of 198 reports (76%), across 107 runs. The entries are specific, and some are not cosmetic at all:
googlemaps' "the core map component is broken across the entire app, displaying only a blue grid
instead of actual map tiles"; instagram's "missing Forgot Password — users have no way to recover
their account"; r146's "content grid is horizontally cut off on the right".

★ P1, NEVER A BLOCKER — deliberately. A run's delivery must not hinge on an LLM's aesthetic
judgement, and #1202z4/#1202z0 settled that when the framework cannot show a finding is
objectively wrong, the right change is the AUDIENCE, not the verdict. The browser walk's objective
P0 path (blank/error/auth-redirect pages) is untouched, and one test here pins that.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.heal_pipeline as HP  # noqa: E402


def _lines(ui):
    fn = getattr(HP, "_ui_friction_lines_1203c8", None)
    assert fn is not None, "_ui_friction_lines_1203c8 is not defined"
    return fn(ui)


def _file(orch, ui, version=""):
    fn = getattr(HP, "_file_ui_friction_task_1203c8", None)
    assert fn is not None, "_file_ui_friction_task_1203c8 is not defined"
    return fn(orch, ui, version)


class _WH:
    def __init__(self, existing=None, list_raises=False):
        self.tasks = list(existing or [])
        self.created = []
        self.list_raises = list_raises

    def list_tasks(self):
        if self.list_raises:
            raise RuntimeError("hub down")
        return self.tasks

    def create_task(self, **kw):
        self.created.append(kw)
        return {"id": "t1", **kw}


class _Orch:
    def __init__(self, wh):
        import logging

        class _H:
            workhub = wh
        self.hubs = _H()
        self._logger = logging.getLogger("t1203c8")


# r146's own words, verbatim from its v1.1.0 report — the entries a lane has to act on.
_R146_UI = {
    "ran": True,
    "screens": [
        {"name": "explore_grid",
         "works": "A logged-out user can browse a TikTok-style Explore grid.",
         "problems": [
             "Content grid is horizontally cut off on the right; several cards extend beyond "
             "the viewport.",
             "Top category navigation starts partially off-screen, making the first category "
             "text clipped.",
         ]},
        {"name": "fyp_feed_comments_panel",
         "works": "The For You feed can play a video and open a comments panel.",
         "problems": [
             "The comments panel header is partly covered by the top utility/login bar.",
         ]},
        {"name": "login_modal",
         "works": "The login modal opens over the feed.",
         "problems": []},
    ],
    "top_issues": [
        "Fix layout overflow/cropping: Explore cards, suggested creator cards, category tabs, "
        "and comments header are clipped or overlapped.",
        "Add clear logged-out and empty-state messaging.",
    ],
}


def test_the_test_users_own_words_reach_the_body():
    """★ Verbatim, not paraphrased — the actionable part IS the wording ("cut off on the
    right", "partly covered by the top utility/login bar")."""
    wh = _WH()
    _file(_Orch(wh), _R146_UI, "1.1.0")
    assert len(wh.created) == 1, wh.created
    body = wh.created[0]["description"]
    assert "horizontally cut off on the right" in body, body
    assert "partly covered by the top utility/login bar" in body, body


def test_the_screens_are_named():
    wh = _WH()
    _file(_Orch(wh), _R146_UI)
    body = wh.created[0]["description"]
    for name in ("explore_grid", "fyp_feed_comments_panel"):
        assert name in body, body


def test_a_screen_with_no_problems_is_not_named():
    """`login_modal` reported only what works; naming it would send a lane to a healthy page."""
    lines, screens, _dropped = _lines(_R146_UI)
    assert "login_modal" not in screens, screens
    assert not any("login_modal" in l for l in lines), lines


def test_the_ranking_is_carried_separately():
    """`top_issues` is the test-user's OWN priority order and is not derivable from the
    per-screen lists — it spans screens ("Explore cards, suggested creator cards, category
    tabs, and comments header")."""
    body = _filed(_R146_UI)["description"]
    assert "fix FIRST" in body, body
    assert "1. Fix layout overflow/cropping" in body, body


def _filed(ui, existing=None):
    wh = _WH(existing)
    _file(_Orch(wh), ui)
    assert wh.created, "nothing was filed"
    return wh.created[0]


def test_it_is_a_p1_for_the_frontend():
    """★ Not P0 and not a blocker: delivery must not hinge on an LLM's taste."""
    t = _filed(_R146_UI)
    assert t["priority"] == "P1", t.get("priority")
    assert t["assignee"] == "frontend", t.get("assignee")


def test_it_says_it_is_not_a_blocker():
    body = _filed(_R146_UI)["description"]
    assert "NOT a delivery blocker" in body, body


def test_it_tells_the_lane_what_to_do_with_a_matter_of_taste():
    """★ The failure mode of routing an LLM's opinion: a lane silences the complaint by
    deleting the thing complained about. The user's standing rule, one layer up."""
    body = _filed(_R146_UI)["description"]
    assert "do not silence it by deleting" in body, body


def test_nothing_is_filed_when_there_is_nothing_to_say():
    for ui in (None, {}, {"ran": False}, {"screens": []},
               {"screens": [{"name": "x", "works": "fine", "problems": []}]}):
        wh = _WH()
        _file(_Orch(wh), ui)
        assert wh.created == [], (ui, wh.created)


def test_the_cap_says_what_it_left_out():
    """#1034: a silently truncated list understates the work."""
    many = {"screens": [{"name": "s", "problems": ["p%d" % i for i in range(9)]}],
            "top_issues": ["t%d" % i for i in range(11)]}
    lines, _screens, dropped = _lines(many)
    assert dropped == (9 - 5) + (11 - 8), dropped
    body = _filed(many)["description"]
    assert "further problem entries not shown" in body, body


def test_an_open_task_is_not_cloned():
    """#794: a four-milestone run walks the app four times."""
    base = "Test-user named user-visible UI frictions (screen walkthrough) — fix"
    wh = _WH([{"title": base + " [explore_grid]", "status": "in_progress"}])
    _file(_Orch(wh), _R146_UI)
    assert wh.created == [], wh.created


def test_a_completed_task_does_not_suppress_a_new_one():
    base = "Test-user named user-visible UI frictions (screen walkthrough) — fix"
    wh = _WH([{"title": base + " [explore_grid]", "status": "completed"}])
    _file(_Orch(wh), _R146_UI)
    assert len(wh.created) == 1


def test_a_listing_fault_still_files():
    """A dedupe fault must not swallow the finding."""
    wh = _WH(list_raises=True)
    _file(_Orch(wh), _R146_UI)
    assert len(wh.created) == 1, "the finding was lost to a hub fault"


def test_a_missing_workhub_is_not_a_crash():
    class _NoHub:
        hubs = None
        import logging as _l
        _logger = _l.getLogger("t1203c8b")
    _file(_NoHub(), _R146_UI)          # must not raise


def test_the_caller_hands_it_the_ui_section():
    """★ I have tested a helper and not its caller repeatedly. Three properties: the call
    exists exactly once, it is fed `report["ui"]` (not the whole report, whose `summary` is a
    different shape), and it is NOT inside the browser walk's `if broken:` branch — a run whose
    UI is objectively fine is exactly the run whose frictions nobody would otherwise hear."""
    import ast
    import inspect

    src = inspect.getsource(HP.HealPipeline)
    tree = ast.parse(src.lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_file_ui_friction_task_1203c8"]
    assert len(calls) == 1, "called %d times" % len(calls)
    dumped = ast.dump(calls[0])
    assert "'ui'" in dumped, dumped[:300]

    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
            raise AssertionError("the call sits behind a branch: %s"
                                 % ast.dump(node.test)[:160])


def test_the_browser_walks_p0_path_is_untouched():
    """★ The objective defects keep blocking. This patch adds an audience; it must not have
    softened the one that was already escalating."""
    import inspect
    src = inspect.getsource(HP.HealPipeline)
    assert 'priority="P0"' in src, "the browser walk's P0 dispatch is gone"
    assert "Test-user found UI defects (browser walkthrough)" in src
