"""E2E: run aggregator + renderer against the real agent/.agent_logs/ directory."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

def _newest_real_logs():
    """The most recently written `.agent_logs` that actually holds events.

    Prefers where runs write today; falls back to the pre-migration location so a host that
    still has old-style logs is not skipped. Returns None only when neither exists, which is
    the fresh-clone case the skip is for."""
    cands = list((AGENT_DIR.parent / "generated").glob("*/.agent_logs"))
    cands.append(AGENT_DIR / ".agent_logs")
    live = [d for d in cands if d.is_dir() and any(d.rglob("*.jsonl"))]
    return max(live, key=lambda d: d.stat().st_mtime) if live else None


REAL_LOGS = _newest_real_logs()
_HAVE_LOGS = REAL_LOGS is not None
_WHY = "no .agent_logs/ with *.jsonl under generated/*/ or agent/ — a fresh clone has no runs"


class ObservabilityE2ETests(unittest.TestCase):
    @unittest.skipUnless(_HAVE_LOGS, _WHY)
    def test_aggregate_real_logs_produces_nontrivial_stats(self) -> None:
        """#1203gr: snapshot the tree, and drop the half-written tail line.

        "every LINE becomes an event" compares the aggregator's count against a second walk of
        the same directory, which is only sound on COMPLETE lines. `_newest_real_logs` picks
        the most recently written tree — the LIVE run's, when one is going — and an agent that
        is mid-append leaves a final line with no newline on it. Python's file iteration yields
        that partial line, the parser cannot read it, and the counts differ. Caught running the
        suite during r170: 3422 events against 3430 lines, eight files each holding one
        unterminated tail (file 401 complete lines, iteration yielding 402).

        So copy, then truncate each file at its last newline. A test that fails only because a
        run happens to be live is a test nobody can trust, and weakening the invariant to
        "parses what is parseable" would have given up the thing #1203gc added.
        """
        from multi_agent.runtime.observability.log_parser import aggregate_logs
        snap = Path(tempfile.mkdtemp(prefix="obs_snap_")) / ".agent_logs"
        shutil.copytree(REAL_LOGS, snap)
        self.addCleanup(shutil.rmtree, snap.parent, ignore_errors=True)
        for f in snap.rglob("*.jsonl"):
            raw = f.read_bytes()
            cut = raw.rfind(b"\n")
            if cut != -1 and cut != len(raw) - 1:
                f.write_bytes(raw[:cut + 1])
        stats = aggregate_logs(snap)
        files = sorted(snap.rglob("*.jsonl"))
        # #1203gc: `> 0` was all this asserted, which a parser that read one file and dropped the
        # rest would satisfy. Two exact invariants hold instead, measured over r161-r164 (8 agent
        # dirs each; 33/21/20/33 files; 14997/9575/7836/18181 events): every agent DIRECTORY is
        # counted, and every LINE becomes an event. Both are tree-independent.
        self.assertEqual(stats.total_agents, len({f.parent for f in files}),
                         "an agent directory was dropped")
        lines = sum(sum(1 for _ in f.open(encoding="utf-8", errors="ignore")) for f in files)
        self.assertEqual(stats.total_events, lines, "events and log lines disagree")
        self.assertGreater(stats.total_events, 0)

    @unittest.skipUnless(_HAVE_LOGS, _WHY)
    def test_render_real_dashboard_produces_valid_html(self) -> None:
        from multi_agent.runtime.observability.log_parser import aggregate_logs
        from multi_agent.runtime.observability.dashboard import render_dashboard
        tmp = Path(tempfile.mkdtemp(prefix="obs_e2e_"))
        try:
            stats = aggregate_logs(REAL_LOGS)
            out = tmp / "dashboard.html"
            html = render_dashboard(stats, output_path=out)
            self.assertTrue(out.exists())
            self.assertIn("<html", html.lower())
            self.assertIn("Agent Observability Dashboard", html)
            # File should be at least somewhat substantial
            self.assertGreater(out.stat().st_size, 500)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
