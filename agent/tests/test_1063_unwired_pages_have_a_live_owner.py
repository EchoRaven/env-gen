"""#1063 — `_COVERED_ELSEWHERE` claims an owner; pin that the owner is reachable.

`dispatch_failing_checks` skips logging a blocker as having "NO remediation owner"
when it appears in `_COVERED_ELSEWHERE` — "Owned by a bespoke helper ... NOT
dead-ends". Three names in that set describe the blank-shell condition:

    deliverability_ui_page_unwired   ui_page_unwired   frontend_navigable

Two of them are live. The third is not, and it is worth knowing which is which:

  * `dispatch_unwired_ui_pages` reads the delivery gate's BLOCKER list, so it sees
    `deliverability_ui_page_unwired` (320 occurrences in the 201 kept logs) and
    files "Make the declared pages deliverable: fill stubs + wire routes" — created
    195 times across 48 of those logs. This is the live path.

  * `dispatch_frontend_navigable` reads `data["checks"]` for a check NAMED
    `frontend_navigable`. That name IS produced — validation_runner's
    `_add("frontend_navigable", ok, detail)` writes it with status "fail" — so the
    guard matches by construction. It has simply never been exercised: 0
    "FRONTEND-NAVIGABLE remediation dispatched" lines in the corpus, because the
    check almost always passes and the four runs where it failed had already lost
    docker_up, so validation never reached the feedback loop. Live, untested.

The risk worth pinning is the OTHER direction: `_COVERED_ELSEWHERE` suppresses the
"NO remediation owner" log for all three names. If the live path is removed or the
producer renamed, the gate keeps declaring the condition owned while nobody is
dispatched — a blocker that fires 320 times, silently unhandled. That is the exact
shape of #1041/#1042/#1049/#1050.

So: pin both the live path and the producer the untested one depends on.
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402


class TheClaimedOwnerExists(unittest.TestCase):

    def test_covered_elsewhere_lists_the_blank_shell_names(self):
        # Read the set through ast, not by counting to the next `}` — #923 forbids
        # a span locator that ends on a bare bracket, because anything nested
        # inside moves the end.
        import ast
        tree = ast.parse(inspect.getsource(rd))
        members = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "_COVERED_ELSEWHERE"
                            for t in node.targets)
                    and isinstance(node.value, ast.Set)):
                members = {e.value for e in node.value.elts
                           if isinstance(e, ast.Constant)}
                break
        self.assertIsNotNone(members, "_COVERED_ELSEWHERE set literal not found")
        for name in ("deliverability_ui_page_unwired", "ui_page_unwired"):
            self.assertIn(name, members)

    def test_the_live_helper_is_present_and_reads_the_blocker_list(self):
        fn = getattr(rd.RemediationDispatcher, "dispatch_unwired_ui_pages", None)
        self.assertTrue(callable(fn),
                        "_COVERED_ELSEWHERE claims a bespoke owner for the unwired "
                        "pages; this is it")
        params = list(inspect.signature(fn).parameters)
        self.assertIn("blockers", params,
                      "it must read the gate's BLOCKER list — reading data['checks'] "
                      "is what made dispatch_frontend_navigable unreachable")

    def test_the_live_helper_files_the_task_the_corpus_shows(self):
        src = inspect.getsource(rd.RemediationDispatcher.dispatch_unwired_ui_pages)
        self.assertIn("Make the declared pages deliverable", src)
        self.assertIn('assignee="frontend"', src)


class TheUntestedPathIsRecordedAsUntested(unittest.TestCase):
    """`dispatch_frontend_navigable` is LIVE — validation_runner produces the name
    with status "fail" — but has fired 0 times in 201 runs, because the check
    almost always passes and the four failing runs died on docker_up first."""

    def test_the_producer_exists_so_the_guard_can_match(self):
        from multi_agent.runtime import validation_runner as vr
        src = inspect.getsource(vr)
        self.assertIn('_add("frontend_navigable"', src,
                      "the guard keys on this name; if the producer goes, the "
                      "dispatch becomes unreachable rather than merely unexercised")
        i = src.index("def _add(")
        self.assertIn('"status": "pass" if ok else "fail"',
                      src[i:src.index("\n\n", i)],
                      "the guard compares status == 'fail'; a boolean here would "
                      "silently stop it matching")

    def test_the_docstring_records_the_measurement(self):
        doc = rd.RemediationDispatcher.dispatch_frontend_navigable.__doc__ or ""
        self.assertIn("#1063", doc)
        self.assertIn("dispatch_unwired_ui_pages", doc,
                      "it must point at the path that carries this in practice")


if __name__ == "__main__":
    unittest.main()
