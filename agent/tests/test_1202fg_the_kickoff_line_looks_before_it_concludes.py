"""#1202fg: don't assert which of two causes it is when the evidence is one read away.

#862's line said "This is the shape of a lane that never started rather than one
that is slow; check .agent_logs for empty per-agent directories" -- it names the
distinguishing evidence and then does not look at it.

netflix-r41's third resume died on that sentence being wrong: the lanes had made
151 tool calls between them (verifier 74, orchestrator 62, backend 7, frontend 2)
and the log still said they never started, so the run's own record pointed at the
wrong repair. The two causes need different fixes -- a lane that never spawned is
an orchestration failure; a lane that is working but has not recorded a SECTION is
a meeting-protocol one.
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff_driver import (  # noqa: E402
    KickoffDriver,
    _lane_log_activity_1202fg,
)

SRC = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
       / "kickoff_driver.py").read_text(encoding="utf-8")


def _driver(logs):
    """A stand-in carrying only what the reporter reads."""
    d = types.SimpleNamespace()
    root = Path(tempfile.mkdtemp())
    (root / ".agent_logs").mkdir()
    for lane, size in (logs or {}).items():
        p = root / ".agent_logs" / lane
        p.mkdir()
        if size:
            (p / "a.jsonl").write_text("x" * size, encoding="utf-8")
    d._orch = types.SimpleNamespace(output_dir=root)
    d._lane_activity_1202fg = types.MethodType(
        KickoffDriver._lane_activity_1202fg, d)
    return d


class TestItLooksBeforeItConcludes(unittest.TestCase):

    def test_the_unchecked_assertion_is_gone(self):
        # Scoped to the warning: a whole-file search finds the sentence in
        # _lane_activity_1202fg's docstring, which QUOTES it. Same
        # comment-trips-the-assertion shape #943 exists to stop.
        i = SRC.index("Kickoff: NO attendee has recorded anything")
        warning = SRC[i:SRC.index("KICKOFF_INITIAL_STALL_MIN_SEC", i)]
        self.assertNotIn("shape of a lane that never started", warning)

    def test_working_lanes_are_reported_as_working(self):
        """r41's case: logs are non-empty, so 'never started' would be false."""
        msg = _driver({"backend": 2048, "verifier": 4096})._lane_activity_1202fg()
        self.assertIn("ARE running", msg)
        self.assertIn("backend", msg)
        self.assertIn("meeting-protocol", msg)

    def test_empty_logs_are_reported_as_never_started(self):
        msg = _driver({"backend": 0, "frontend": 0})._lane_activity_1202fg()
        self.assertIn("never started", msg)
        self.assertIn("orchestration failure", msg)

    def test_an_unreadable_tree_claims_neither_cause(self):
        d = types.SimpleNamespace(_orch=types.SimpleNamespace(output_dir="/nonexistent-fg"))
        d._lane_activity_1202fg = types.MethodType(KickoffDriver._lane_activity_1202fg, d)
        msg = d._lane_activity_1202fg()
        self.assertIn("cannot be told", msg)
        self.assertNotIn("never started", msg)

    def test_the_reader_never_raises(self):
        self.assertEqual(_lane_log_activity_1202fg(None), {})
        self.assertEqual(_lane_log_activity_1202fg(12345), {})

    def test_the_verdict_reaches_the_warning(self):
        """A reporter nothing calls is the written-but-never-wired shape."""
        i = SRC.index("Kickoff: NO attendee has recorded anything")
        block = SRC[i:SRC.index("KICKOFF_INITIAL_STALL_MIN_SEC", i)]
        self.assertIn("self._lane_activity_1202fg()", block)


if __name__ == "__main__":
    unittest.main()
