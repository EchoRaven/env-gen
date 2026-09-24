"""#1202fb: "it could not run" must be a state, not a heartbeat.

netflix-r43 (live) printed `#1039 live seed row-count DID NOT RUN` 57 times in one
run, against 9 SUCCESSFUL counts of the same measurement -- and the successes are
quiet. So the log says "NOT CHECKED, not clean" 57 times about an audit that did
run, and produced an artifact counting 13 tables. It read that way to me while
mining, which is #883's failure mode arriving from the other side: not a silent
empty, a deafening one.

#1202ad's table lists `#1202v seed audit "0 of N"` -- this same file, already
fixed once for the same noise at a different line. This is the sixth site.
"""
import logging
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.message_format import reset_state_memo_1202ad  # noqa: E402
from multi_agent.runtime.seed_audit import _not_measured_1039  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.warnings = []

    def emit(self, record):
        if record.levelno >= logging.WARNING:
            self.warnings.append(record.getMessage())


class TestNotMeasuredIsAState(unittest.TestCase):

    def setUp(self):
        reset_state_memo_1202ad("seed_audit:")
        self.cap = _Capture()
        self.log = logging.getLogger("multi_agent.runtime.seed_audit")
        self.log.addHandler(self.cap)
        self._prev = self.log.level
        self.log.setLevel(logging.DEBUG)

    def tearDown(self):
        self.log.removeHandler(self.cap)
        self.log.setLevel(self._prev)

    def test_the_same_reason_is_said_once(self):
        for _ in range(57):
            _not_measured_1039("no database container resolved from /x/docker-compose.yml")
        self.assertEqual(len(self.cap.warnings), 1,
                         "57 identical states must not be 57 warnings")

    def test_it_still_says_what_883_requires(self):
        """The empty default must announce itself, or it reads as a clean measurement."""
        _not_measured_1039("no database container resolved")
        msg = self.cap.warnings[0]
        self.assertIn("DID NOT RUN", msg)
        self.assertIn("NOT CHECKED", msg)
        self.assertIn("no database container resolved", msg)

    def test_a_different_reason_is_news(self):
        _not_measured_1039("no database container resolved")
        _not_measured_1039("query failed: connection refused")
        self.assertEqual(len(self.cap.warnings), 2)

    def test_returning_to_a_seen_reason_is_news_again(self):
        """#1202ad is deliberately NOT log-once: a state that moves back has moved."""
        _not_measured_1039("A")
        _not_measured_1039("B")
        _not_measured_1039("A")
        self.assertEqual(len(self.cap.warnings), 3)

    def test_it_still_returns_the_empty_mapping(self):
        self.assertEqual(_not_measured_1039("whatever"), {})

    def test_it_never_raises(self):
        self.assertEqual(_not_measured_1039(None), {})
        self.assertEqual(_not_measured_1039(object()), {})


if __name__ == "__main__":
    unittest.main()
