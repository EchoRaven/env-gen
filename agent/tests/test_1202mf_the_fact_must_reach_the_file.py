"""#1202mf — two facts I added landed on the returned dict, not on the artifact.

#1202lx (was the running image built from the source on disk?) and #1202lz (which /api paths
did the browser call and this app not serve?) each put their answer on the dict
`run_visual_fidelity` RETURNS, and both commit messages claimed it reached "the artifact a
reader consults". It did not.

`_persist_verdict` builds its own #500 best-of-captures structure from
`(passed, min_similarity, summary, coverage, results)` and never sees the returned dict.
tiktok-r122's `design/visual_gate/verdict.json`, written 18:49:54, carries thirteen keys and
neither of mine:

    ['better_state_available', 'better_state_note', 'blocking_average',
     'blocking_average_live', 'code_state', 'coverage', 'judge_unstable_893', 'milestone',
     'min_similarity', 'passed', 'screens', 'screens_below_record_928', 'summary']

That is the fact-with-no-reader defect this entire batch has been closing, committed by me
twice. It was caught by reading r122's verdict.json — not by the tests, which asserted the
SOURCE LINE that sets the key and were green throughout.

So these tests read the FILE.
"""
import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _persist(tmp_path, **extra):
    vf._persist_verdict(
        tmp_path, passed=True, min_similarity=0.65, summary="ok",
        coverage={"judged": 1, "measured": 1, "coverage": 1.0, "unjudged": []},
        results=[{"name": "feed", "route": "/", "similarity": 0.8, "passed": True,
                  "dimensions": {}, "deviations": []}],
        **extra)
    p = tmp_path / "design" / "visual_gate" / "verdict.json"
    assert p.is_file(), "no verdict.json was written at all"
    return json.loads(p.read_text(encoding="utf-8"))


def test_build_currency_reaches_the_file(tmp_path):
    """★ #1202lx's claim, now actually true."""
    v = _persist(tmp_path, build_currency_1202lx={
        "verdict": "changed", "detail": "app/ has changed since the image was built"})
    assert v["build_currency_1202lx"]["verdict"] == "changed"
    assert "changed since the image was built" in v["build_currency_1202lx"]["detail"]


def test_api_404s_reach_the_file(tmp_path):
    """★ #1202lz's claim, now actually true."""
    v = _persist(tmp_path, api_404s_1202lz={"/api/profiles": ["(startup)"]})
    assert v["api_404s_1202lz"] == {"/api/profiles": ["(startup)"]}


def test_both_default_to_none_without_breaking_the_writer(tmp_path):
    """Callers that do not pass them must still get a verdict file."""
    v = _persist(tmp_path)
    assert v.get("build_currency_1202lx") is None
    assert v.get("api_404s_1202lz") is None
    assert v["passed"] is True


def test_the_pre_existing_keys_survive(tmp_path):
    """★ Non-regression: #500's structure is what everything else reads."""
    v = _persist(tmp_path, api_404s_1202lz={})
    for k in ("passed", "min_similarity", "summary", "coverage", "screens"):
        assert k in v, k


def test_the_caller_passes_both(tmp_path):
    """★ Reachability: the writer accepting them proves nothing if nobody supplies them —
    which is precisely how this defect survived two commits."""
    import ast
    import inspect
    src = inspect.getsource(vf.run_visual_fidelity)
    calls = [ast.unparse(n) for n in ast.walk(ast.parse(src.lstrip()))
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_persist_verdict"]
    assert calls, "the persist call moved"
    assert "build_currency_1202lx=" in calls[0]
    assert "api_404s_1202lz=" in calls[0]
