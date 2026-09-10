"""#1202jm: the console from the LIVE capture is where a blank route says why.

r111 blanked exactly one route. Eight screens rendered, `/comments` did not, and the browser
had already said what happened — an uncaught error whose stack reads

    at CommentMedia (http://localhost:8009/assets/index-DGbcM8dN.js:9821:54)

That crash IS the repair. The persisted record for that screen carried `console_errors: []`,
truthfully describing the kept 0.62 capture that #500's merge preserved (#931's rule: every
unsuffixed field belongs to the RECORDED capture). So the live console had nowhere to land,
and the one artefact that outlives the run was the one without the cause in it.

Same shape as #1202jl one field over, and the more useful half: `blank_live` says the page was
empty, `console_errors_live` says why.
"""
import sys
import pathlib
import json

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf  # noqa: E402

_CRASH = ["uncaught: TypeError: x is not a function\n    at CommentMedia (.../index.js:9821:54)"]


def _res(name, sim, blank=None, console=None, route="/x"):
    r = {"name": name, "route": route, "similarity": sim, "passed": sim >= 0.65,
         "dimensions": {}, "deviations": [], "fixes": [], "summary": ""}
    if blank is not None:
        r["blank"] = blank
    if console is not None:
        r["console_errors"] = console
    return r


def _persist(tmp, results):
    vf._persist_verdict(tmp, passed=False, min_similarity=0.65, summary="s",
                        coverage={}, results=results)
    return {s["name"]: s
            for s in json.loads((pathlib.Path(tmp) / "design" / "visual_gate" / "verdict.json")
                                .read_text(encoding="utf-8"))["screens"]}


def test_the_live_console_reaches_the_record(tmp_path):
    _persist(tmp_path, [_res("comments_panel", 0.62, blank=False, console=[])])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, blank=True,
                                 console=_CRASH)])["comments_panel"]
    assert s["similarity_live"] == 0.00 and s["blank_live"] is True
    assert s["console_errors_live"] == _CRASH, (
        "the crash that blanked the route must land on the record that reports the blank")


def test_the_kept_captures_console_is_not_overwritten(tmp_path):
    """#931: `console_errors` describes the capture the dimensions/deviations describe."""
    _persist(tmp_path, [_res("comments_panel", 0.62, blank=False, console=["old: warn"])])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, blank=True,
                                 console=_CRASH)])["comments_panel"]
    assert s["console_errors"] == ["old: warn"], (
        "overwriting it would make every other field on the record describe a different "
        "capture than its console")


def test_a_quiet_live_capture_is_recorded_as_checked_not_missing(tmp_path):
    """#771b's distinction: [] means 'checked, none'; None would mean 'not recorded'."""
    _persist(tmp_path, [_res("player", 0.88, console=["x"])])
    s = _persist(tmp_path, [_res("player", 0.00, console=[])])["player"]
    assert s["console_errors_live"] == [], "a silent capture is evidence, not an absence"


def test_a_screen_not_captured_has_no_live_console(tmp_path):
    _persist(tmp_path, [_res("player", 0.88), _res("landing", 0.40)])
    _persist(tmp_path, [_res("player", 0.00, console=_CRASH), _res("landing", 0.40)])
    s = _persist(tmp_path, [_res("landing", 0.45)])["player"]
    assert s["similarity_live"] is None
    assert "console_errors_live" in s and s["console_errors_live"] is None, (
        "nobody photographed it, so nobody read its console either")


def test_the_note_names_every_live_field(tmp_path):
    _persist(tmp_path, [_res("comments_panel", 0.62, blank=False, console=[])])
    s = _persist(tmp_path, [_res("comments_panel", 0.00, blank=True,
                                 console=_CRASH)])["comments_panel"]
    for f in ("similarity_live", "capture_missing_live", "capture_error_live",
              "blank_live", "console_errors_live"):
        assert f"`{f}`" in s["similarity_live_note"], f"{f} missing from the live-field note"
