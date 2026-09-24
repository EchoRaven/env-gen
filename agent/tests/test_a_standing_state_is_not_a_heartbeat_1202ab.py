r"""#1202ab/#1202ac: two more logs that reported a heartbeat instead of a state.

Swept r32 — the newest run, carrying every fix — for repeated warnings, the technique that
found #1197 and #1198. Two of the top offenders were both mine to fix and one was mine to
have caused:

    117 x 9 pages   LANE PAGE WITH OWN COMPONENTS: <page> ... KEEPING the lane's page
    117             #1202j N asset path(s) are referenced but exist nowhere in the tree

★ The lane-page line was also self-contradicting. It ended with "set
ENVGEN_DEFER_TO_LANE_PAGE=1 to keep the lane's" while its own verdict said "KEEPING the lane's
page" — advice written when #914 shipped the flag OFF, left in place after #1020 turned it ON
by default. A reader would go and switch on the behaviour they were already watching work. The
flag is now only mentioned when it would change something.

★ The asset line is #1202j, which I added two days ago, and I had already removed this exact
noise three times by then — #1202n (heal declines), #1202p (declaration drift), #1202v (seed
audit). Same rule everywhere: a state that CHANGES is reported again, standing still is quiet,
and no verdict moves.
"""

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

_FS = (THIS_DIR.parent
       / "env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py"
       ).read_text(encoding="utf-8")
_SC = (THIS_DIR.parent
       / "env_generator/llm_generator/multi_agent/runtime/scaffolder.py"
       ).read_text(encoding="utf-8")


def _lane_page_block():
    i = _FS.index("# #1202ab: two things wrong with this line")
    return _FS[i:_FS.index("except Exception:", i)]


def _asset_block():
    i = _SC.index("# #1202ac:")
    return _SC[i:_SC.index("except Exception as _e1202j", i)]


def test_the_lane_page_verdict_is_memoed_per_page():
    b = _lane_page_block()
    assert "_LANE_PAGE_SAID_1202AB" in b
    assert "_seen1202ab.get(comp) != _state1202ab" in b


def test_the_memo_key_includes_the_verdict_so_a_flip_is_reported():
    """Keeping and replacing are different states; a change between them must be said."""
    assert "bool(_defer_914)" in _lane_page_block()


def test_the_flag_is_only_offered_when_it_would_change_something():
    b = _lane_page_block()
    assert '"" if _defer_914 else' in b
    # and the contradictory phrasing is gone
    assert "to keep the lane's)" not in _FS


def test_the_asset_report_is_memoed_on_the_set():
    b = _asset_block()
    assert "_unstaged_assets_said_1202ac" in b
    assert "tuple(sorted(_as1202j))" in b


def test_a_changed_asset_set_is_reported_again():
    """The memo compares the SET, so staging one of them is news."""
    b = _asset_block()
    assert "!= _key1202ac" in b


def test_neither_change_touches_a_verdict():
    """Both are logging-only: no blocker, no return value, no projection decision."""
    for b in (_lane_page_block(), _asset_block()):
        assert "return" not in b
        assert "blockers" not in b
