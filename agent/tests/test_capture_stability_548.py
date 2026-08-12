"""#548 + #550 (netflix, r103, 2026-08-06) — kill the Part-A run-to-run variance.

#548 CAPTURE STABILITY (visual_fidelity): the DB is periodically RE-SEEDED during a
run, momentarily WIPING the ``profiles`` table. The frontend gates every protected
route on a selected profile (``needProfile`` → the "Who's watching?" picker when none
is selected/persisted, or when the persisted id no longer resolves). A screenshot
taken while a re-seed is in flight captures the tiny profile-picker instead of the
real page, and the judge scores that real screen ~0.05 with NO code change (r103:
browse_home 0.78→0.06 in 13 min). The fix makes the CAPTURE faithful:
  (b) seed-settled wait before capture, (a) re-select a profile + (c) detect a
  picker capture as INVALID and re-select+re-navigate, never feeding a picker to the
  judge as a real screen.
The capture loop needs playwright, so the DECISION is factored into pure helpers
(``_is_profile_picker_capture`` / ``_screen_is_profile_screen``) tested here, plus the
small async ``_ensure_profile_selected`` / ``_wait_seed_settled`` driven with fakes.
Integration point: ``capture_route_screenshots`` runs the probe right before each
protected screen's shot and skips (never records) a still-picker capture.

#550 my_list grid tiebreaker (frontend_scaffold._wants_rows_539): route
``/browse/my-list`` carries BOTH the ambient "browse" ROWS token and the "list"/
"mylist" GRID token; the header-band tiebreaker then flipped my_list to a rows+hero
layout (0.78→0.45). A GRID token now takes PRECEDENCE over an ambient-only "browse"
rows hit (a genuine rows token still contests). browse_home / new_and_popular stay
rows; browse_by_languages stays grid.

CONSTRAINTS proven: additive; byte-identical when the signal is absent (no profile
gate → the picker decision is False so the retry path is never entered; no grid token
→ _wants_rows_539 unchanged); no product literals; scoring/threshold untouched.
"""
import asyncio

import env_generator.llm_generator.multi_agent.runtime.visual_fidelity as vf
import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _wants_rows_539,
)


# ─────────────────────────── #548 pure: picker detection ───────────────────────

def test_who_watching_heading_is_a_picker():
    # the universal "Who's watching?" heading → the capture is the selection gate.
    assert vf._is_profile_picker_capture(
        {"whos": True, "profilesRoute": False, "avatars": 0}) is True


def test_profiles_route_with_avatar_grid_is_a_picker():
    # bounced to a /profiles chooser AND showing an avatar selection grid.
    assert vf._is_profile_picker_capture(
        {"whos": False, "profilesRoute": True, "avatars": 3}) is True


def test_profiles_route_without_grid_is_not_flagged():
    # conservative: a /profiles URL alone (no tiles) is not enough to flag a picker.
    assert vf._is_profile_picker_capture(
        {"whos": False, "profilesRoute": True, "avatars": 0}) is False


def test_real_content_page_is_never_flagged():
    # a non-gate app / a real content screen → NOT a picker → NO re-select/retry →
    # the capture is byte-identical to the pre-#548 behavior.
    assert vf._is_profile_picker_capture(
        {"whos": False, "profilesRoute": False, "avatars": 6}) is False
    assert vf._is_profile_picker_capture(None) is False
    assert vf._is_profile_picker_capture("not-a-dict") is False
    assert vf._is_profile_picker_capture({}) is False


# ─────────────────── #548 pure: which screens are the picker itself ─────────────

def test_profiles_screen_itself_is_exempt():
    # the real profiles/"who's watching" reference screen — its picker capture is
    # CORRECT and must NOT be treated as invalid.
    assert vf._screen_is_profile_screen({"name": "whos_watching", "route": "/x"})
    assert vf._screen_is_profile_screen({"name": "x", "route": "/profiles"})
    assert vf._screen_is_profile_screen({"name": "x", "route": "/profiles/"})
    assert vf._screen_is_profile_screen({"name": "select_profiles", "route": "/x"})
    assert vf._screen_is_profile_screen({"name": "profile_picker", "route": "/x"})


def test_content_and_account_screens_are_not_profile_screens():
    # a protected content screen is NOT the picker (its gate-bounce IS re-selected),
    # and a SINGULAR /profile account page is not a chooser either.
    assert vf._screen_is_profile_screen({"name": "browse_home", "route": "/browse"}) is False
    assert vf._screen_is_profile_screen({"name": "my_list", "route": "/browse/my-list"}) is False
    assert vf._screen_is_profile_screen({"name": "account_profile", "route": "/profile"}) is False
    assert vf._screen_is_profile_screen(None) is False


# ─────────────────────── #548: the JS assets are well-formed ────────────────────

def test_capture_stability_js_assets_present():
    for js in (vf._PROFILE_PICKER_PROBE, vf._PROFILE_PICKER_CLICK_JS,
               vf._PROFILE_COUNT_JS):
        assert isinstance(js, str) and js.strip()
    # the probe keys the pure helper reads
    for k in ("whos", "profilesRoute", "avatars"):
        assert k in vf._PROFILE_PICKER_PROBE
    # no product literals leaked into the capture-stability code
    for js in (vf._PROFILE_PICKER_PROBE, vf._PROFILE_PICKER_CLICK_JS,
               vf._PROFILE_COUNT_JS):
        assert "netflix" not in js.lower()


# ─────────────────── #548 async: _ensure_profile_selected (fakes) ───────────────

class _FakeCtx:
    def __init__(self):
        self.init_scripts = []

    async def add_init_script(self, js):
        self.init_scripts.append(js)


class _FakePage:
    """Minimal page: routes evaluate() by the JS it is handed."""

    def __init__(self, *, pid="1", clicked=True, counts=None):
        self._pid = pid
        self._clicked = clicked
        self._counts = list(counts or [])
        self.storage_evals = []
        self.click_calls = 0

    async def evaluate(self, js, *args):
        if js is vf._PROFILE_DISCOVER_JS:
            return self._pid
        if js is vf._PROFILE_PICKER_CLICK_JS:
            self.click_calls += 1
            return self._clicked
        if js is vf._PROFILE_COUNT_JS:
            return self._counts.pop(0) if self._counts else -1
        if isinstance(js, str) and js.lstrip().startswith("() => {"):
            self.storage_evals.append(js)      # the storage-set on the current page
            return None
        return None

    async def wait_for_timeout(self, ms):
        return None


def test_ensure_profile_selected_persists_and_clicks():
    ctx, page = _FakeCtx(), _FakePage(pid="1", clicked=True)
    out = asyncio.run(
        vf._ensure_profile_selected(page, ctx, token="t"))
    assert out is True
    # a discovered id is persisted under every alias — init-script (future loads)
    # AND on the current page (immediate) — and the picker tile is clicked.
    assert ctx.init_scripts and "active_profile_id" in ctx.init_scripts[0]
    assert page.storage_evals, "the current page must be updated immediately"
    assert page.click_calls == 1


def test_ensure_profile_selected_noop_when_nothing_to_do():
    # no profile endpoint (pid None) and no on-screen tile → returns False and does
    # not fabricate a selection (a non-gate app is left untouched).
    ctx, page = _FakeCtx(), _FakePage(pid=None, clicked=False)
    out = asyncio.run(
        vf._ensure_profile_selected(page, ctx, token=None))
    assert out is False
    assert ctx.init_scripts == []
    assert page.storage_evals == []


# ─────────────────── #548 async: _wait_seed_settled (fakes) ─────────────────────

def test_seed_settle_returns_immediately_with_no_gate():
    # count -1 → no /profiles endpoint → no gate → return after a single poll
    # (a non-gate app is not delayed; byte-identical output).
    page = _FakePage(counts=[-1])
    asyncio.run(vf._wait_seed_settled(page, None))
    assert page._counts == []  # exactly one poll consumed


def test_seed_settle_waits_for_a_stable_nonempty_count():
    # 0 (mid-wipe) → 2 → 2 (stable & non-empty): settles on the repeat, so it never
    # discovers/captures against an empty (mid-re-seed) profiles table.
    page = _FakePage(counts=[0, 2, 2, 2, 2])
    asyncio.run(vf._wait_seed_settled(page, "t"))
    # consumed 0, 2, 2 → two remain
    assert page._counts == [2, 2]


# ───────────────────────────── #550 grid tiebreaker ────────────────────────────

def _screen(name, route, comp, bands=0):
    s = {"name": name, "route": route, "component": comp}
    if bands:
        s["components"] = [{"role": "section title"}, {"role": "row heading"}]
    return s


def test_my_list_is_a_grid():
    # route /browse/my-list carries the ambient "browse" rows token AND the
    # "list"/"mylist" grid token → GRID (the grid token wins the tie), even with the
    # 2 stacked header bands that previously flipped it to rows+hero.
    assert _wants_rows_539(
        _screen("my_list", "/browse/my-list", "MyListPage", bands=2)) == "grid"
    assert _wants_rows_539(
        _screen("my_list", "/browse/my-list", "MyListPage")) == "grid"


def test_content_home_and_new_popular_stay_rows():
    assert _wants_rows_539(
        _screen("browse_home", "/browse", "BrowsePage", bands=2)) == "rows"
    assert _wants_rows_539(
        _screen("new_and_popular", "/browse/new", "NewAndPopularPage", bands=2)) == "rows"


def test_by_languages_stays_grid():
    assert _wants_rows_539(
        _screen("browse_by_languages", "/browse/languages",
                "BrowseByLanguagesPage")) == "grid"


def test_genuine_rows_plus_grid_collision_still_defers():
    # a name carrying a GENUINE rows token ("popular") AND a grid token ("list") is
    # still ambiguous → defers to the data/header-band signal (byte-identical to the
    # pre-#550 behavior; the fix only changes the ambient-only "browse" tie).
    assert _wants_rows_539(
        _screen("popular_list", "/x", "PopularListPage", bands=2)) == "rows"
    # a pure grid token with no rows token at all is still a grid.
    assert _wants_rows_539(_screen("search", "/search", "SearchPage")) == "grid"


# ───────────────────────────────── imports guard ───────────────────────────────

def test_modules_import():
    assert vf is not None and fs is not None
    assert callable(vf.capture_route_screenshots)
    assert callable(fs._wants_rows_539)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
