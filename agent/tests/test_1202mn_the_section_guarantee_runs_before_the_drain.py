"""#1202mn: the kickoff section guarantee must not be sequenced behind the drain.

`_handle_kickoff_request`'s `finally` holds two things: a drain that replays
every queued task_ready — each able to run a full agentic loop — and
`_ensure_initial_section_decision`, the "closed-by-construction" write that lets
the kickoff coordinator stop waiting for this attendee. They ran in that order,
so the one cheap local write the meeting is blocked on arrived only after
arbitrary unrelated work.

MEASURED in tiktok-r123's second resume, from that run's own ledgers:

  * M1: the backend lane took `#1202er`'s skip at 13:49:07, entered
    a 2000-step agentic loop in the same second, and logged 3087
    lines of other work. Its `backend` section decision landed at 14:43:15 —
    42 minutes AFTER the kickoff gave up at 14:00:52 and reconciled from the
    registry instead. Its frontend section never arrived at all.
  * M2: verifier recorded at 15:03:58 and backend by 15:05:06, both well inside
    the window; the coordinator then spent its last 18 minutes waiting on
    frontend alone, whose section arrived at 16:23:31 — an hour after the
    15:23:20 timeout.

Two full 1200s timeouts in one run. Priced from that run's own token ledger at
the configured rates: ~$62 and ~$51, about 30% of the resume's spend, for a
write that needs no model.

The fix is a reordering, so the test that matters is about ORDER — and about
call-site order, not definition order. `#1202fd` shipped inert precisely because
its ordering assertion compared where a method was DEFINED (line 4207) instead
of where it was CALLED (line 1551), and passed against broken wiring.
"""
import ast
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MESSAGING = (LLM_DIR / "multi_agent" / "agents" / "runtime" / "messaging.py")
SRC = MESSAGING.read_text(encoding="utf-8")


def _kickoff_finally_body():
    """The `finally` body of `_handle_kickoff_request`, as AST nodes."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_handle_kickoff_request"):
            for t in ast.walk(node):
                if isinstance(t, ast.Try) and t.finalbody:
                    return t.finalbody
    raise AssertionError("_handle_kickoff_request has no try/finally")


def _call_names(nodes):
    """Names of the calls in these statements, in source order."""
    out = []
    for stmt in nodes:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if name:
                    out.append((n.lineno, name))
    out.sort()
    return [name for _ln, name in out]


class TheGuaranteeRunsFirst(unittest.TestCase):

    def test_the_section_is_recorded_before_the_drain(self):
        names = _call_names(_kickoff_finally_body())
        self.assertIn("_ensure_initial_section_decision", names, names)
        self.assertIn("_drain_deferred_task_ready_messages", names, names)
        self.assertLess(
            names.index("_ensure_initial_section_decision"),
            names.index("_drain_deferred_task_ready_messages"),
            "the section write is sequenced behind an unbounded drain again: %s"
            % names)

    def test_both_still_run_on_the_exception_path(self):
        """They are in `finally`, so a failed kickoff turn still records the
        section — that is the whole point of a closed-by-construction guarantee."""
        body = _kickoff_finally_body()
        names = _call_names(body)
        self.assertIn("_ensure_initial_section_decision", names)
        # and nothing in the finally can return early before it
        for stmt in body:
            for n in ast.walk(stmt):
                self.assertNotIsInstance(
                    n, ast.Return, "an early return in the finally would skip it")


class TheOrderingIsCheckedAtTheCallSite(unittest.TestCase):
    """Validation before trust: prove this file's probe can actually see the
    order it claims to check, by running it against a reversed copy."""

    def test_the_probe_goes_red_when_the_order_is_reversed(self):
        reversed_src = SRC.replace(
            "            self._ensure_initial_section_decision(\n"
            "                meeting_id=meeting_id,\n"
            "                milestone_index=milestone_index,\n"
            "                expected_section=expected_section,\n"
            "            )\n"
            "            # Drain any task_ready that arrived while we were busy\n"
            "            # responding to kickoff. This is the same path\n"
            "            # _handle_task_ready uses on its way out.\n"
            "            await self._drain_deferred_task_ready_messages()",
            "            await self._drain_deferred_task_ready_messages()\n"
            "            self._ensure_initial_section_decision(\n"
            "                meeting_id=meeting_id,\n"
            "                milestone_index=milestone_index,\n"
            "                expected_section=expected_section,\n"
            "            )")
        self.assertNotEqual(reversed_src, SRC,
                            "the reversal anchor no longer matches the source")
        tree = ast.parse(reversed_src)
        body = None
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "_handle_kickoff_request"):
                for t in ast.walk(node):
                    if isinstance(t, ast.Try) and t.finalbody:
                        body = t.finalbody
                        break
        self.assertIsNotNone(body)
        names = _call_names(body)
        self.assertGreater(
            names.index("_ensure_initial_section_decision"),
            names.index("_drain_deferred_task_ready_messages"),
            "the probe cannot distinguish the two orders, so its pass proves nothing")


class TheWriteItselfIsCheap(unittest.TestCase):
    """It must stay a local write — putting a model call in front of the
    coordinator's wait would recreate the defect in a new shape."""

    def test_the_guarantee_calls_no_agentic_loop(self):
        tree = ast.parse(SRC)
        fn = [n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_ensure_initial_section_decision"][0]
        called = {getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                  for n in ast.walk(fn) if isinstance(n, ast.Call)}
        for forbidden in ("run_agentic_loop", "_drain_deferred_task_ready_messages"):
            self.assertNotIn(forbidden, called, called)


if __name__ == "__main__":
    unittest.main()
