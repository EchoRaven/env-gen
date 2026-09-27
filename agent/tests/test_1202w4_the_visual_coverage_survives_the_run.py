"""#1202w4: #351's visual-coverage measurement reaches an artifact.

#351 reports how much of the reference the visual gate actually judged, and carries a plan:
"turning this into a blocker comes after the page-seeding fix, or every run would start failing
a gate it cannot yet satisfy." Its numbers went to `_LOG.warning` and nowhere else, so nobody
holding a run's artifacts could tell whether that precondition had been met.

#947 made this a rule, and #946 is why: an APPROVED PLAN was silently voided because the
measurement it depended on was a log line that appeared in zero artifacts. #351 is the same
shape — a deferred decision whose evidence evaporates with the console.

Measured across the 31 run logs that still carry the line: coverage is a median 73% and never
above 82%, so about a quarter of the reference is never judged, and the same screens are
skipped every time — `settings_more_menu` in 31 of 31 runs, `profile_own` in 20,
`notifications_activity` in 17.

Reports only. The verdict is untouched, exactly as #351 requires.
"""
import ast
import inspect
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import visual_fidelity as VF      # noqa: E402

_R = VF.record_screen_coverage_1202w4
_COV = {"judged": 8, "measured": 11, "coverage": 8 / 11,
        "unjudged": ["settings_more_menu", "profile_own"]}


def test_the_measurement_lands_in_an_artifact(tmp_path):
    assert _R(tmp_path, _COV, "v1.0.0")
    rec = json.loads(
        (tmp_path / "logs" / "visual_screen_coverage_1202w4.jsonl").read_text().strip())
    assert rec["judged"] == 8 and rec["measured"] == 11
    assert rec["unjudged"] == ["settings_more_menu", "profile_own"]
    assert rec["milestone"] == "v1.0.0"
    assert 0.72 < rec["coverage"] < 0.73


def test_which_screens_went_unjudged_is_the_point(tmp_path):
    """A percentage alone cannot tell anyone WHICH part of the reference is never examined,
    and that is the fact the deferred decision turns on — `settings_more_menu` is skipped in
    31 of 31 runs."""
    _R(tmp_path, _COV, "")
    rec = json.loads(
        (tmp_path / "logs" / "visual_screen_coverage_1202w4.jsonl").read_text().strip())
    assert rec["unjudged"], "the names must travel, not just the count"


def test_it_appends_so_a_multi_milestone_run_keeps_every_reading(tmp_path):
    _R(tmp_path, _COV, "v1.0.0")
    _R(tmp_path, {**_COV, "judged": 9}, "v1.1.0")
    rows = [json.loads(l) for l in
            (tmp_path / "logs" / "visual_screen_coverage_1202w4.jsonl").read_text().splitlines()
            if l.strip()]
    assert [r["milestone"] for r in rows] == ["v1.0.0", "v1.1.0"]
    assert [r["judged"] for r in rows] == [8, 9]


def test_nothing_is_written_without_a_measurement(tmp_path):
    assert not _R(tmp_path, None)
    assert not _R(tmp_path, {})
    assert not _R(None, _COV)
    assert not (tmp_path / "logs" / "visual_screen_coverage_1202w4.jsonl").exists()


def test_the_gate_records_before_it_logs():
    """AST (#943): the artifact write must sit in the same branch as the warning, or the log
    keeps saying something the files never show."""
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(VF)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "run_visual_fidelity")
    branch = None
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and "VISUAL COVERAGE" in ast.unparse(node):
            branch = node
            break
    assert branch is not None, "the #351 report is gone"
    body = ast.unparse(branch)
    assert "record_screen_coverage_1202w4(project_dir, _coverage" in body


def test_it_does_not_touch_the_verdict():
    """#351 is explicit that `passed` stays untouched until the page-seeding fix lands. A
    recorder that changed the verdict would make every run fail a gate it cannot satisfy."""
    src = inspect.getsource(VF.record_screen_coverage_1202w4)
    for forbidden in ("passed", "_verdict", "raise"):
        assert forbidden not in src, f"the recorder must not reach `{forbidden}`"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
