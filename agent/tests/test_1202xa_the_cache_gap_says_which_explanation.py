"""#1202xa: bucket each call by the gap since the same label's previous one.

The per-phase split (#1202cr) says the orchestrator caches worse than the lanes: over the 48
runs carrying it, the orchestrator's four phases hold 265M of the corpus's 634M uncached
prompt tokens -- 42% -- at a 75-84% hit rate against the lanes' 96-97%. r137 alone spent
$190.49 on 3225 calls.

Two explanations fit that equally well and imply OPPOSITE fixes:

  volatility  the prefix changes between calls. The orchestrator's message list is rewritten
              by `condense_messages`, by `_mask_old_observations` (which mutates `m.content`
              in place for every tool result older than the last 8 -- a boundary that advances
              as the turn grows), and by the step reminder being deleted from the middle and
              re-appended.
  expiry      an ephemeral cache entry lives ~5 minutes. Lanes call back-to-back; the
              orchestrator often thinks for minutes between calls, so a cold prefix would have
              nothing to do with volatility and rewriting the message handling would buy
              nothing.

An aggregate hit rate cannot separate them; the gap since the same label's previous call can.
Under expiry the rate collapses only past the TTL. Under volatility it is flat and low at
every gap. This is the instrument, not the answer -- the answer needs a run.

Keyed by LABEL because that is the grain a cached prefix lives at: two lanes interleaving
their calls say nothing about either one's prefix age.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

from utils.llm import (  # noqa: E402
    _CACHE_BY_GAP_1202XA,
    _LAST_CALL_AT_1202XA,
    _gap_bucket_1202xa,
    _record_cache_gap_1202xa,
    llm_cache_by_gap_1202xa,
)

_LLM = os.path.join(_AGENT, "utils", "llm.py")
_BUDGET = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                       "run_budget.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _fresh():
    _CACHE_BY_GAP_1202XA.clear()
    _LAST_CALL_AT_1202XA.clear()


def test_the_buckets_straddle_the_ttl():
    """★ A bucket boundary that does not sit on the TTL cannot separate the two curves."""
    assert _gap_bucket_1202xa(None) == "first"
    assert _gap_bucket_1202xa(0.0) == "<60s"
    assert _gap_bucket_1202xa(59.9) == "<60s"
    assert _gap_bucket_1202xa(60.0) == "60-300s"
    assert _gap_bucket_1202xa(300.0) == "60-300s"
    assert _gap_bucket_1202xa(300.1) == ">300s"


def test_expiry_and_volatility_produce_different_shapes():
    """★ The whole point: the instrument must tell the two apart, or it answers nothing."""
    _fresh()
    t = 1000.0
    for i in range(1, 4):                      # back-to-back, warm
        _record_cache_gap_1202xa("lane", 10000, 9600, now=t + i * 5)
    for i in range(1, 4):                      # ten minutes apart, cold
        _record_cache_gap_1202xa("orch", 10000, 0, now=t + i * 600)
    got = llm_cache_by_gap_1202xa()
    assert got["<60s"]["hit_pct"] == 96.0, got
    assert got[">300s"]["hit_pct"] == 0.0, got

    _fresh()                                   # volatility: cold at EVERY gap
    for i in range(1, 4):
        _record_cache_gap_1202xa("a", 10000, 0, now=t + i * 5)
    for i in range(1, 4):
        _record_cache_gap_1202xa("b", 10000, 0, now=t + i * 600)
    flat = llm_cache_by_gap_1202xa()
    assert flat["<60s"]["hit_pct"] == 0.0 and flat[">300s"]["hit_pct"] == 0.0, flat


def test_the_gap_is_per_label_not_global():
    """Two lanes interleaving say nothing about either one's prefix age."""
    _fresh()
    t = 2000.0
    _record_cache_gap_1202xa("a", 10, 10, now=t)
    _record_cache_gap_1202xa("b", 10, 10, now=t + 1)       # 'b' is also a first call
    _record_cache_gap_1202xa("a", 10, 10, now=t + 400)     # 'a' waited 400s despite b's call
    got = llm_cache_by_gap_1202xa()
    assert got["first"]["calls"] == 2, got
    assert got[">300s"]["calls"] == 1, (
        "the gap was measured against another label's call: %r" % got)


def test_an_unreported_cache_field_is_not_counted_as_a_miss():
    """★ #1026b. Counting 'not told' as 0 would manufacture the volatility signal this
    instrument exists to test for."""
    _fresh()
    _record_cache_gap_1202xa("x", 100, "n/a", now=10.0)
    got = llm_cache_by_gap_1202xa()
    assert got["first"]["cache_unreported"] == 1, got
    assert got["first"]["cached"] == 0 and got["first"]["prompt"] == 100


def test_the_rate_is_reported_beside_its_counts():
    """#1034: a percentage on its own cannot be checked."""
    _fresh()
    _record_cache_gap_1202xa("x", 1000, 750, now=1.0)
    e = llm_cache_by_gap_1202xa()["first"]
    assert e["hit_pct"] == 75.0 and e["prompt"] == 1000 and e["cached"] == 750
    assert e["uncached"] == 250


def test_a_zero_prompt_reports_no_rate_rather_than_zero():
    _fresh()
    _record_cache_gap_1202xa("x", 0, 0, now=1.0)
    assert llm_cache_by_gap_1202xa()["first"]["hit_pct"] is None


def test_recording_never_raises():
    _fresh()
    for bad in (None, object(), "x"):
        _record_cache_gap_1202xa(bad, bad, bad, now=1.0)


def test_the_recorder_is_called_where_the_label_is_known():
    """A recorder nothing calls is #1202wm's dead mechanism."""
    fn = next((n for n in ast.walk(ast.parse(_read(_LLM)))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_record_by_label_1202cr"), None)
    assert fn is not None
    assert "_record_cache_gap_1202xa" in ast.unparse(fn), (
        "the gap recorder is not called from the one place that holds the label")


def test_the_measurement_reaches_an_artifact():
    """★ #947: a measurement that only exists in memory is not a measurement. The whole
    reason this ticket exists is that the last question died for want of a persisted number."""
    src = _read(_BUDGET)
    assert "llm_cache_by_gap_1202xa" in src, (
        "run_budget.json does not carry the buckets, so a finished run cannot be asked")
    tree = ast.parse(src)
    written = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Subscript)
                       and isinstance(t.slice, ast.Constant)
                       and t.slice.value == "llm_cache_by_gap_1202xa"
                       for t in n.targets)]
    assert written, "the key is mentioned but never assigned into the payload"
