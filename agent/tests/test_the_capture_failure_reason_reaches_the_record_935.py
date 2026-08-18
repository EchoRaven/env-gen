r"""#935: #769 rescued the reason from a bare `except` and put it in a log line nobody keeps.

#769's comment is exactly right about why the reason matters — *"a navigation timeout, a closed
page and a proxy refusal are three different problems"* — and it fixed the discard by logging the
exception type and message. r154's run directory contains **no `#769` line anywhere**: nothing in
the run persists that logger. The reason existed, was caught, was written, and was still
unavailable to anyone holding only the run's artifacts.

★ What that cost, in this session. `title_detail` was photographed ONCE in r154, at 17:19:57 —
`history/` holds exactly one entry for it against 118 in total — and scored 0.00 in every round
after. With the stale PNG still on disk looking healthy (#934), I diagnosed judge noise, wrote it
into the r154 illustrations of two tickets, and only found the truth by listing mtimes. One
`capture_error` field would have said it in the first probe.

The fix follows the shape this function already uses four times over: an optional out-parameter
(`auth_redirected`, `blank_screens`, `picker_screens` #657, `console_errors` #740). The fifth
carries the exception to the screen record, and #933 carries it from there into the append-only
ledger.
"""
import ast
import inspect
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


# --------------------------------------------------------------------------- the out-parameter

def test_the_capture_fn_accepts_the_out_parameter():
    sig = inspect.signature(vf.capture_route_screenshots)
    assert "capture_errors" in sig.parameters
    assert sig.parameters["capture_errors"].default is None, (
        "must default to None like its four siblings, so every existing caller is unchanged")


def test_the_except_populates_it():
    """AST, not text: the #769 comment block names the field in prose, and a substring check
    would pass on the comment alone (three source-scanning instruments went wrong that way)."""
    fn = [n for n in ast.walk(ast.parse(inspect.getsource(vf)))
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name == "capture_route_screenshots"]
    assert fn, "capture_route_screenshots not found"
    writes = [n for n in ast.walk(fn[0])
              if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                      and t.value.id == "capture_errors" for t in n.targets)]
    assert len(writes) == 1, f"expected one write to capture_errors, found {len(writes)}"


def test_the_default_capture_threads_it():
    fn = [n for n in ast.walk(ast.parse(inspect.getsource(vf)))
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name == "run_visual_fidelity"]
    assert fn
    calls = [n for n in ast.walk(fn[0]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "capture_route_screenshots"]
    assert calls, "the default capture must still call the real screenshotter"
    assert any(k.arg == "capture_errors" for c in calls for k in c.keywords), (
        "the reason is collected by the capture fn and must be handed back")


# --------------------------------------------------------------------------- it reaches the ledger

def _row(tmp_path, results):
    vdir = tmp_path / "design" / "visual_gate"
    vdir.mkdir(parents=True, exist_ok=True)
    vf._append_round_record_640(vdir, {"code_state": "abc"}, results)
    return [json.loads(l) for l in (vdir / "rounds.jsonl").read_text().splitlines() if l.strip()][-1]


def test_the_reason_reaches_the_append_only_record(tmp_path):
    """★ The end of the chain — what r154 needed and did not have."""
    row = _row(tmp_path, [{"name": "title_detail", "similarity": 0.0, "capture_missing": True,
                           "capture_error": "TimeoutError: Timeout 20000ms exceeded",
                           "deviations": ["route /title/:id produced NO capture this pass — "
                                          "the harness did not photograph it, so there is "
                                          "nothing to judge. This is not a verdict on the page "
                                          "— the capture raised TimeoutError: Timeout 20000ms "
                                          "exceeded"]}])
    z = row["zero_reasons_933"]["title_detail"]
    assert z["capture_missing"] is True
    assert z["capture_error"].startswith("TimeoutError")
    assert "not a verdict on the page" in z["why"]


def test_three_different_causes_stay_distinguishable(tmp_path):
    """#769's own argument for keeping the type: these are three different problems."""
    z = _row(tmp_path, [
        {"name": "a", "similarity": 0.0, "capture_missing": True,
         "capture_error": "TimeoutError: Timeout 20000ms exceeded", "deviations": ["x"]},
        {"name": "b", "similarity": 0.0, "capture_missing": True,
         "capture_error": "TargetClosedError: page closed", "deviations": ["x"]},
        {"name": "c", "similarity": 0.0, "capture_missing": True,
         "capture_error": "Error: net::ERR_PROXY_CONNECTION_FAILED", "deviations": ["x"]},
    ])["zero_reasons_933"]
    assert {z[k]["capture_error"].split(":")[0] for k in "abc"} == {
        "TimeoutError", "TargetClosedError", "Error"}


def test_a_screen_that_scored_carries_nothing(tmp_path):
    assert "zero_reasons_933" not in _row(tmp_path, [{"name": "landing", "similarity": 0.7}])


def test_a_zero_with_no_capture_error_still_records_the_rest(tmp_path):
    """A judge failure is a zero with no capture error — the field must be None, not missing."""
    z = _row(tmp_path, [{"name": "x", "similarity": 0.0,
                         "deviations": ["judge returned no JSON"]}])["zero_reasons_933"]["x"]
    assert z["capture_error"] is None and z["why"] == "judge returned no JSON"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
