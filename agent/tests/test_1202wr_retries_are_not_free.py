"""#1202wr: a run must be able to say how much of itself went to LLM retries.

`_retry_with_backoff` measures each attempt's elapsed seconds and logs them, and nothing
counted the attempts. `llm_usage()` reports calls / prompt / cached / completion /
cache_unreported / usd -- no retry anywhere. So a finished run could not say how much of
its wall clock, or of its bill (a failed attempt can still be charged for input), went to
re-rolls. Retry storms are a classic cost sink and this one was invisible.

The counters ride the channel that already exists rather than a new one (#1032):
`run_budget` writes `payload["llm"] = llm_usage()` wholesale, so a key added here reaches
`run_budget.json` with no further wiring -- and, unlike a fresh artifact, it is carried
across resumes by the same code that carries the dollars.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from utils import llm as _llm  # noqa: E402


def _reset():
    _llm._LLM_USAGE["retries"] = 0
    _llm._LLM_USAGE["retry_sec"] = 0.0


def test_usage_reports_retries_at_all():
    _reset()
    got = _llm.llm_usage()
    assert "retries" in got and "retry_sec" in got, sorted(got)


def test_each_failed_attempt_counts():
    _reset()
    _llm.record_llm_retry_1202wr(2.5)
    _llm.record_llm_retry_1202wr(1.25)
    got = _llm.llm_usage()
    assert got["retries"] == 2
    assert got["retry_sec"] == 3.75, got


def test_a_missing_or_odd_duration_still_counts_the_attempt():
    """The attempt happened; losing its seconds must not lose the retry."""
    _reset()
    _llm.record_llm_retry_1202wr(None)
    _llm.record_llm_retry_1202wr("slow")
    assert _llm.llm_usage()["retries"] >= 1


def test_a_negative_duration_cannot_shrink_the_total():
    _reset()
    _llm.record_llm_retry_1202wr(5.0)
    _llm.record_llm_retry_1202wr(-99.0)
    assert _llm.llm_usage()["retry_sec"] == 5.0


def test_the_existing_totals_are_untouched():
    """A new key must not disturb what run_budget already carries."""
    _reset()
    before = {k: v for k, v in _llm.llm_usage().items() if k not in ("retries", "retry_sec")}
    _llm.record_llm_retry_1202wr(3.0)
    after = {k: v for k, v in _llm.llm_usage().items() if k not in ("retries", "retry_sec")}
    assert before == after


def test_the_recorder_is_called_on_the_failure_path():
    """★ A counter nobody increments is the defect #1202wm was about."""
    import ast

    with open(os.path.join(_AGENT, "utils", "llm.py"), encoding="utf-8") as fh:  # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_retry_with_backoff"), None)
    assert fn is not None, "_retry_with_backoff is gone"
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
    assert handlers, "the retry loop no longer catches anything"
    assert any(isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == "record_llm_retry_1202wr"
               for h in handlers for c in ast.walk(h)), (
        "an attempt fails, is retried, and is still not counted")


def test_it_rides_the_channel_run_budget_already_writes():
    """★ The reason this is a key and not a new artifact: run_budget writes the whole dict."""
    import ast

    path = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                        "run_budget.py")
    with open(path, encoding="utf-8") as fh:      # #1202eu
        src = fh.read()
    assert 'payload["llm"] = llm_usage()' in src, (
        "run_budget no longer persists llm_usage() wholesale, so these keys may not be "
        "reaching run_budget.json any more -- check before trusting them")
