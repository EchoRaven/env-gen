"""#1203g4 — a run could say how much wall clock went to retries, never which error caused it.

`#1202wr` added `retries` and `retry_sec`, and they measure something large: across the 27 runs
that carry the counter, 3.9 hours of 43.5 process-wall hours went to re-rolls — 8.9%, and 36.8%
of tiktok-r158 alone (4353s, in a $467.84 run). Nothing on disk could say whether that wait was
CORRECT. A rate-limit sleep is the provider's price and the right thing to do; a timeout or a
malformed-response re-roll is waste. They cost the same wall clock and were indistinguishable.

The error type exists at the retry site — `error_type = type(e).__name__`, one line below the
recorder — and went only to `logger.info`. r151 through r164, the last fourteen runs, persist NO
`generation_*.log`, so the attribution is unrecoverable from the artifacts: `run_budget.json`'s
`llm` section carries exactly `retries` and `retry_sec` and no breakdown.

Rides #1202wr's channel for the reason it gave: `run_budget` writes `llm_usage()` wholesale.
"""
import inspect
import sys
from pathlib import Path

import pytest

_AGENT = str(Path(__file__).resolve().parents[1])
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

from utils import llm as _llm  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    _llm._LLM_USAGE["retries"] = 0
    _llm._LLM_USAGE["retry_sec"] = 0.0
    _llm._LLM_USAGE["retry_by_error"] = {}
    _llm._LLM_USAGE["retry_sec_by_error"] = {}
    yield


def test_usage_reports_the_breakdown_at_all():
    got = _llm.llm_usage()
    assert "retry_by_error" in got and "retry_sec_by_error" in got, sorted(got)


def test_a_run_with_zero_retries_still_carries_the_keys():
    """★ The keys must be INITIALISED, not conjured by the first retry.

    The recorder uses `setdefault`, and this file's fixture pre-seeds both keys, so a first
    version of the test above passed even with the keys deleted from `_LLM_USAGE`'s literal --
    the fixture was masking it. It matters: a run with no retries would then write a
    `run_budget.json` with no breakdown at all, and a reader could not tell "nothing was
    retried" from "this was never instrumented" -- the exact ambiguity #1202wr exists to end.

    Asserted over the module's own dict literal, so no reload and no reliance on the fixture."""
    import ast
    tree = ast.parse(inspect.getsource(_llm))
    lits = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_LLM_USAGE" for t in n.targets)]
    assert lits, "_LLM_USAGE is no longer a module-level literal"
    keys = {k.value for k in lits[0].value.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    for k in ("retries", "retry_sec", "retry_by_error", "retry_sec_by_error"):
        assert k in keys, "%s is not initialised in _LLM_USAGE (got %s)" % (k, sorted(keys))


def test_each_error_type_gets_its_own_count_and_seconds():
    _llm.record_llm_retry_1202wr(30.0, "RateLimitError")
    _llm.record_llm_retry_1202wr(1.0, "RateLimitError")
    _llm.record_llm_retry_1202wr(2.5, "APITimeoutError")
    got = _llm.llm_usage()
    assert got["retry_by_error"] == {"RateLimitError": 2, "APITimeoutError": 1}
    assert got["retry_sec_by_error"] == {"RateLimitError": 31.0, "APITimeoutError": 2.5}


def test_the_breakdown_sums_to_the_totals():
    """The whole point is attribution: a breakdown that does not add up to `retry_sec` would
    answer 'which error' with a number nobody can trust."""
    for sec, err in ((30.0, "RateLimitError"), (2.5, "APITimeoutError"),
                     (7.25, "APIConnectionError"), (1.0, "RateLimitError")):
        _llm.record_llm_retry_1202wr(sec, err)
    got = _llm.llm_usage()
    assert sum(got["retry_by_error"].values()) == got["retries"]
    assert round(sum(got["retry_sec_by_error"].values()), 2) == got["retry_sec"]


def test_a_retry_with_no_type_is_bucketed_not_dropped():
    """A retry that cannot name its error is exactly the state this counter exists to end, so
    it must be VISIBLE as unknown rather than vanish from the breakdown."""
    _llm.record_llm_retry_1202wr(4.0)
    got = _llm.llm_usage()
    assert got["retry_by_error"] == {"unknown": 1}
    assert got["retry_sec_by_error"] == {"unknown": 4.0}
    assert sum(got["retry_by_error"].values()) == got["retries"]


@pytest.mark.parametrize("err", [None, "", "   ", 0, False])
def test_every_empty_type_lands_in_one_bucket(err):
    _llm.record_llm_retry_1202wr(1.0, err)
    assert _llm.llm_usage()["retry_by_error"] == {"unknown": 1}


def test_the_old_signature_still_works():
    """#1202wr's callers pass only the elapsed seconds; none may break."""
    _llm.record_llm_retry_1202wr(3.75)
    got = _llm.llm_usage()
    assert got["retries"] == 1 and got["retry_sec"] == 3.75


def test_it_never_raises_on_a_hostile_value():
    class _Bad:
        def __str__(self):
            raise ValueError("nope")
    _llm.record_llm_retry_1202wr("not a number", _Bad())
    assert isinstance(_llm.llm_usage()["retry_by_error"], dict)


def test_the_other_counters_are_untouched():
    before = {k: v for k, v in _llm.llm_usage().items()
              if k not in ("retries", "retry_sec", "retry_by_error", "retry_sec_by_error")}
    _llm.record_llm_retry_1202wr(9.0, "RateLimitError")
    after = {k: v for k, v in _llm.llm_usage().items()
             if k not in ("retries", "retry_sec", "retry_by_error", "retry_sec_by_error")}
    assert before == after


# ------------------------------------------------------------------ wiring, over the AST

def test_the_retry_site_passes_the_error_type():
    """#1178's standing lesson: the type is in hand at the call site, and a recorder that is
    never given it reports `unknown` forever. Pinned over the AST so a positional-argument
    change cannot silently drop it."""
    import ast
    src = inspect.getsource(_llm)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "record_llm_retry_1202wr"]
    assert calls, "the recorder is never called"
    typed = []
    for c in calls:
        args = len(c.args) + len(c.keywords)
        if args >= 2:
            typed.append(c)
    assert typed, "no call site passes an error type — the breakdown can only say 'unknown'"
    # and the type must come from the exception, not a literal
    src_of = {ast.unparse(c) for c in typed}
    assert any("__name__" in s for s in src_of), src_of


def test_the_keys_reach_run_budget_through_llm_usage():
    """#1202wr's own reason for this channel: `run_budget` writes `llm_usage()` wholesale, so a
    key added to _LLM_USAGE needs no further wiring. Asserted, not assumed."""
    keys = set(_llm.llm_usage())
    assert {"retry_by_error", "retry_sec_by_error"} <= keys
    assert {"retries", "retry_sec"} <= keys        # #1202wr's pair must survive


def test_llm_usage_returns_a_copy_not_the_live_dict():
    """A caller mutating the report must not corrupt the counters — run_budget writes this
    straight into JSON across resumes."""
    _llm.record_llm_retry_1202wr(1.0, "RateLimitError")
    got = _llm.llm_usage()
    assert got["retry_by_error"] is not _llm._LLM_USAGE["retry_by_error"], (
        "`dict()` is shallow — the breakdown would be the live counter")
    got["retry_by_error"]["injected"] = 99
    got["retry_sec_by_error"]["injected"] = 99.0
    assert "injected" not in _llm._LLM_USAGE["retry_by_error"]
    assert "injected" not in _llm._LLM_USAGE["retry_sec_by_error"]
