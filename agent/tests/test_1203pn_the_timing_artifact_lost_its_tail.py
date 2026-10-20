"""#1203pn: the per-tool timing artifact was only ever written on an exact 50-call boundary.

`_flush_tool_ms_1202wl` had exactly one caller -- the `% _FLUSH_EVERY_1202WL` branch inside
`_record_tool_ms_1202wl` -- and `AgentTooling` has no agent-end hook. So:

  * `calls` is ALWAYS a multiple of 50. Measured across the corpus's 300
    `browser_test_user_*` timing artifacts: 295 read exactly 50 and 5 read 100, and the
    per-tool counts sum to the same figure in all 300 (15250 = 15250), so the writes really
    are landing on the boundary. An agent that made 99 calls is recorded as 50 and 49 calls of
    timing are lost -- a systematic undercount in what `read_tool_timings_1203ge` hands a
    reader, whose whole stated purpose is that "a reader that wants the run's tool cost should
    not have to rediscover the directory layout".
  * an agent that made fewer than 50 calls never reaches the boundary and writes NO artifact at
    all, so a short-lived agent is invisible rather than cheap.

And the SHAPE misleads, which is why this is worth a ticket rather than a shrug: a column of
exact 50s reads as a ceiling. It cost a wrong hypothesis within the hour -- "the browser walk is
hitting a 50-call budget, so it is being cut off" -- which the per-tool counts then contradicted.
#1039's family: a figure indistinguishable from a cap.

The fix is a time-based flush ALONGSIDE the count one, not instead of it: the interval exists
because this sits on the hot path of every tool invocation, so flushing per call would be a real
cost. 30s bounds the lost tail and also covers the under-50 agent.
"""

import json
import tempfile
import time
import types
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.agents.runtime.tooling import AgentTooling


class _Stub(AgentTooling):
    """The minimum an `AgentTooling` recorder touches.

    A SUBCLASS, so the real `_record_tool_ms_1202wl`, the real `_flush_tool_ms_1202wl` and the
    real thresholds are what run -- a hand-built stub with copied methods would drift from what
    ships, and the first version of this harness failed for exactly that reason. `__init__` is
    not chained: the recorder reads only `agent_id`, `_hubs.base_dir` and `_logger`.
    """

    def __init__(self, root):            # noqa: D107 - see the class docstring
        self.agent_id = "browser_test_user_1_page_demo"
        self._hubs = types.SimpleNamespace(base_dir=str(root))
        self._logger = types.SimpleNamespace(
            debug=lambda *a, **k: None, info=lambda *a, **k: None,
            warning=lambda *a, **k: None, error=lambda *a, **k: None)


def _rec(stub, tool="browser_navigate", ms=10.0):
    AgentTooling._record_tool_ms_1202wl(stub, tool, ms)


def _artifact(root):
    d = Path(root) / "logs" / "tool_timings_1202wl"
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    return json.loads(files[0].read_text(encoding="utf-8")) if files else None


class TheCountBoundaryStillWorks(unittest.TestCase):

    def test_fifty_calls_writes_the_artifact(self):
        """Non-vacuity, and the existing behaviour must survive."""
        root = tempfile.mkdtemp()
        s = _Stub(root)
        for _ in range(AgentTooling._FLUSH_EVERY_1202WL):
            _rec(s)
        a = _artifact(root)
        self.assertIsNotNone(a, "the 50-call boundary stopped writing")
        self.assertEqual(a["calls"], 50)

    def test_the_hot_path_does_not_write_on_every_call(self):
        """The interval exists for a reason: this sits on every tool invocation.

        The first call DOES write -- `_tool_ms_flushed_at_1203pn` starts absent, reads as 0.0,
        and so is already stale -- and that is deliberate: it is what makes an agent with two
        calls visible without any end-of-life hook. What must not happen is a write per call.
        So the check is that four rapid calls after the first add nothing: the artifact still
        says `calls == 1`.

        The first version of this test asserted nothing was written at all, which contradicted
        `test_a_fresh_recorder_does_not_wait_for_the_whole_interval` in the same file. Writing
        immediately and then throttling is the better behaviour, so this is the assertion that
        changed.
        """
        root = tempfile.mkdtemp()
        s = _Stub(root)
        for _ in range(5):
            _rec(s)
        a = _artifact(root)
        self.assertIsNotNone(a)
        self.assertEqual(a["calls"], 1, "it wrote on a call that neither trigger allowed")


class TheTailIsNoLongerLost(unittest.TestCase):

    def test_an_agent_under_fifty_calls_is_not_invisible(self):
        """The second consequence: a short-lived agent used to leave no artifact at all."""
        root = tempfile.mkdtemp()
        s = _Stub(root)
        _rec(s)
        s._tool_ms_flushed_at_1203pn = time.time() - (AgentTooling._FLUSH_SECONDS_1203PN + 1)
        _rec(s)
        a = _artifact(root)
        self.assertIsNotNone(a, "an agent with 2 calls still leaves nothing behind")
        self.assertEqual(a["calls"], 2)

    def test_the_recorded_count_is_no_longer_always_a_multiple_of_fifty(self):
        """The shape that misled: a column of exact 50s reads as a ceiling."""
        root = tempfile.mkdtemp()
        s = _Stub(root)
        for _ in range(7):
            _rec(s)
        s._tool_ms_flushed_at_1203pn = time.time() - (AgentTooling._FLUSH_SECONDS_1203PN + 1)
        _rec(s)
        a = _artifact(root)
        self.assertEqual(a["calls"], 8)
        self.assertTrue(a["calls"] % AgentTooling._FLUSH_EVERY_1202WL,
                        "the only counts reachable are still boundary multiples")

    def test_a_fresh_recorder_does_not_wait_for_the_whole_interval(self):
        """`_tool_ms_flushed_at_1203pn` starts absent, which reads as 0.0 -- an epoch timestamp
        -- so the very first call is already 'stale' and writes. That is the behaviour that
        makes an under-50 agent visible without any end-of-life hook."""
        root = tempfile.mkdtemp()
        s = _Stub(root)
        _rec(s)
        a = _artifact(root)
        self.assertIsNotNone(a, "the first call left nothing behind")
        self.assertEqual(a["calls"], 1)

    def test_the_per_tool_totals_still_agree_with_the_count(self):
        """The corpus invariant that proved the writes land on the boundary: 15250 == 15250."""
        root = tempfile.mkdtemp()
        s = _Stub(root)
        for t in ("browser_navigate", "browser_click", "browser_navigate"):
            _rec(s, t)
        s._tool_ms_flushed_at_1203pn = 0.0
        _rec(s, "browser_fill")
        a = _artifact(root)
        self.assertEqual(a["calls"],
                         sum(v["count"] for v in a["tools"].values()))


class ItNeverRaises(unittest.TestCase):

    def test_no_writable_base_is_not_an_error(self):
        s = _Stub(tempfile.mkdtemp())
        s._hubs = types.SimpleNamespace(base_dir=None)
        s.workspace = None
        _rec(s)          # must not raise

    def test_a_junk_duration_is_ignored_rather_than_recorded_as_zero(self):
        """The function's own rule: "an unknown duration recorded as 0 understates"."""
        root = tempfile.mkdtemp()
        s = _Stub(root)
        for bad in (None, True, "x", object()):
            AgentTooling._record_tool_ms_1202wl(s, "browser_navigate", bad)
        self.assertIsNone(_artifact(root), "a junk duration was recorded as a call")


if __name__ == "__main__":
    unittest.main()
