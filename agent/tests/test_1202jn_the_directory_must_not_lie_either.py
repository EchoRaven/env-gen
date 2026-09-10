"""#1202jn: a stale capture is retired on EVERY path that photographs nothing.

#934 exists because a directory that keeps last round's picture under this round's name makes
a reader reason from the wrong pixels. Its docstring records the author doing it — "I opened
that file, reasoned from it, and wrote two tickets around 'the judge scored a working page
0.00' before checking the mtime".

It guarded one branch of four. `if not shot:` fans out into picker / blank / auth-bounce /
no-capture, and all four `continue` before the screenshot; only the last called #934. So it
landed again: r111's `fyp_feed_comments_panel` blanked, `visual_gate/fyp_feed_comments_panel
.png` kept a complete comments page two hours older than the verdict, and I reported "a
well-rendered screen scored 0.00" from it before checking the mtime.

The cost is not only to readers. #934 names two more: a lane reads the same directory, and
#713's duplicate-capture hash treats a stale file as a real image that can duplicate-match
another screen.

The record half is the same defect from the other side — `screenshot_live` was carried from
the round the capture WON, so the field whose name promises this round pointed at another's.
"""
import sys
import pathlib
import json

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                         # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf  # noqa: E402


# --- the directory ------------------------------------------------------------------

def test_a_stale_capture_is_actually_renamed(tmp_path):
    """The primitive itself, on a real file."""
    (tmp_path / "profile_own.png").write_bytes(b"old pixels")
    assert vf._retire_stale_capture_934(tmp_path, "profile_own") is True
    assert not (tmp_path / "profile_own.png").exists()
    assert (tmp_path / "profile_own.NOT-CAPTURED.png").read_bytes() == b"old pixels"


def test_retiring_nothing_is_not_an_error(tmp_path):
    assert vf._retire_stale_capture_934(tmp_path, "never_seen") is False


def test_the_retirement_guards_every_no_shot_branch():
    """★ The defect: it sat under one of the four `continue`-before-screenshot branches.

    Asserted structurally because the four branches are inside one long capture loop that no
    unit test can drive: the call must be an ancestor of ALL of them, i.e. directly under
    `if not shot:` rather than nested in a sibling branch.
    """
    src = inspect.getsource(vf)
    i = src.index('shot = shots.get(screen["name"])')
    j = src.index("_no_shot_768 = False", i)
    head = src[i:j]
    assert "_retire_stale_capture_934(shots_dir" in head, (
        "the retirement must run before the branch chain that explains WHY nothing was "
        "photographed — every one of those branches leaves the stale file in place")
    tail = src[j:src.index("results.append({", j)]
    assert "_retire_stale_capture_934(shots_dir" not in tail, (
        "and exactly once: a second call inside one branch is the shape that made three "
        "of the four silently uncovered")


def test_it_is_not_nested_under_a_further_condition():
    """#1202jn must not repeat #934's own mistake one level down."""
    tree = ast.parse(inspect.getsource(vf))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "_retire_stale_capture_934"]
    assert len(calls) == 1, f"expected exactly one call site, found {len(calls)}"


# --- the record ---------------------------------------------------------------------

def _res(name, sim, shot=None, route="/x"):
    return {"name": name, "route": route, "similarity": sim, "passed": sim >= 0.65,
            "dimensions": {}, "deviations": [], "fixes": [], "summary": "",
            "screenshot": shot}


def _persist(tmp, results):
    vf._persist_verdict(tmp, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    return {s["name"]: s
            for s in json.loads((pathlib.Path(tmp) / "design" / "visual_gate" / "verdict.json")
                                .read_text(encoding="utf-8"))["screens"]}


def test_a_round_that_photographed_nothing_says_so_in_the_path(tmp_path):
    """★ r111's shape: the kept 0.62 record's path outlived the round that took no picture."""
    _persist(tmp_path, [_res("comments_panel", 0.62, shot="/v/comments_panel.png")])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, shot=None)])["comments_panel"]
    assert s["similarity_live"] == 0.00
    assert s["screenshot_live"] is None, (
        "a field named `_live` must not point at the round the capture WON")


def test_a_live_capture_that_scored_lower_still_names_its_own_file(tmp_path):
    """Non-vacuity: None must track the input, not be hardcoded."""
    _persist(tmp_path, [_res("player", 0.88, shot="/v/best.png")])
    s = _persist(tmp_path, [_res("player", 0.20, shot="/v/this_round.png")])["player"]
    assert s["screenshot_live"] == "/v/this_round.png"


def test_a_screen_not_captured_this_round_has_no_live_path(tmp_path):
    """The middle round must leave a REAL path behind, or this proves nothing: a prior None
    would be carried by `**p` and the assertion would hold with the fix removed."""
    _persist(tmp_path, [_res("player", 0.88, shot="/v/a.png"), _res("landing", 0.40)])
    mid = _persist(tmp_path, [_res("player", 0.30, shot="/v/b.png"),
                              _res("landing", 0.40)])["player"]
    assert mid["screenshot_live"] == "/v/b.png", "non-vacuity: something must be there to clear"
    s = _persist(tmp_path, [_res("landing", 0.45)])["player"]
    assert s["similarity_live"] is None and s["screenshot_live"] is None


def test_the_note_names_every_live_field(tmp_path):
    _persist(tmp_path, [_res("comments_panel", 0.62, shot="/v/a.png")])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, shot=None)])["comments_panel"]
    for f in ("similarity_live", "capture_missing_live", "capture_error_live",
              "blank_live", "console_errors_live", "screenshot_live"):
        assert f"`{f}`" in s["similarity_live_note"], f"{f} missing from the live-field note"
