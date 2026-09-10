"""#1202kc: two guards that an empty value silently disabled.

Both were found by re-reading this session's own "measured, not fixed" list, and both are the
same shape — a guard whose OFF switch could be thrown by a typo, with nothing to distinguish
"the operator turned this off" from "a shell expanded an unset variable".

  * `_warn_if_nothing_scored_1202hy` read
    `float(os.environ.get("ENVGEN_NOTHING_SCORED_WARN_USD", "50") or 0)` and then returned
    early on `floor <= 0`. `ENVGEN_NOTHING_SCORED_WARN_USD=` — what a shell writes when the
    variable it expands is itself unset — collapses to 0 and drops the warning for the whole
    run. Blank now means the default; only an explicit number disables, and disabling says so.

  * `_eval_visual_similarity` read `float(params.get("min_similarity") or 0.0)`, so a gate with
    no threshold passed ANY score. `_validate` requires the field, so reaching that fallback
    means the spec bypassed validation — and a gate whose bar is unknown must fail CLOSED.

Neither has corpus traffic today (no user-gate specs in 150 runs, and nobody sets that env
var), which is why they sat unfixed. That is an argument about likelihood, not correctness:
both are one-line paths from a typo to a silently absent check.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import json                                                            # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import run_snapshot as RS  # noqa: E402
from env_generator.llm_generator.multi_agent.runtime import user_gates as UG  # noqa: E402


def _run_dir(tmp_path, usd, judged=0):
    """A run that has spent `usd` and whose gate has judged `judged` screens.

    Both files are required: #1202hy deliberately treats a MISSING gate file as "not
    measured", which is not the same as "judged nothing" — so a fixture without it would
    return None for a reason unrelated to the floor and prove nothing about it.
    """
    (tmp_path / "run_budget.json").write_text(json.dumps({"llm": {"usd": usd}}))
    g = tmp_path / "design" / "visual_gate"
    g.mkdir(parents=True, exist_ok=True)
    (g / "gate_state.json").write_text(json.dumps({"total_judgments": judged}))
    return tmp_path


def _clear(tmp_path):
    RS._NOTHING_SCORED_WARNED_1202HY.pop(str(pathlib.Path(tmp_path)), None)


def test_an_empty_env_var_keeps_the_default_floor(monkeypatch, tmp_path):
    """★ The typo case: `ENVGEN_NOTHING_SCORED_WARN_USD=` must not disable the guard."""
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "")
    _clear(tmp_path)
    out = RS._warn_if_nothing_scored_1202hy(_run_dir(tmp_path, 120.0))
    assert out, "a blank value means 'unset', so the $50 default applies and this must warn"


def test_a_whitespace_env_var_is_also_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "   ")
    _clear(tmp_path)
    assert RS._warn_if_nothing_scored_1202hy(_run_dir(tmp_path, 120.0))


def test_an_explicit_zero_still_disables(monkeypatch, tmp_path):
    """Turning it off deliberately stays possible — that was never the defect."""
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "0")
    _clear(tmp_path)
    assert RS._warn_if_nothing_scored_1202hy(_run_dir(tmp_path, 120.0)) is None


def test_a_real_threshold_is_honoured(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "500")
    _clear(tmp_path)
    assert RS._warn_if_nothing_scored_1202hy(_run_dir(tmp_path, 120.0)) is None, (
        "$120 is below a $500 floor"
    )
    _clear(tmp_path)
    assert RS._warn_if_nothing_scored_1202hy(_run_dir(tmp_path, 600.0))


def test_garbage_falls_back_to_the_default_rather_than_off(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVGEN_NOTHING_SCORED_WARN_USD", "fifty")
    _clear(tmp_path)
    assert RS._warn_if_nothing_scored_1202hy(_run_dir(tmp_path, 120.0)), (
        "an unparseable value must not read as 0")


def test_a_gate_with_no_threshold_fails_closed():
    """★ A gate whose bar is unknown must not wave a page through."""
    out = UG._eval_visual_similarity({"page_id": "home"}, None, pathlib.Path("."))
    assert out["passed"] is False
    assert "min_similarity" in out["message"]


def test_an_explicit_zero_threshold_is_still_honoured():
    """0.0 is a legitimate bar; only ABSENCE is refused."""
    out = UG._eval_visual_similarity(
        {"page_id": "home", "min_similarity": 0.0}, None, pathlib.Path("."))
    assert "min_similarity" not in out["message"], out
