"""#1203pb: four default subscriptions that no emitter can ever satisfy.

`DEFAULT_SUBSCRIPTIONS` wires agents to push-events "they previously could only see by
polling", and its first comment says outright "Stuck merges + failed agent tasks MUST reach
orchestrator". Four of those wires cannot carry anything, confirmed from BOTH sides:

  workhub/task_stale        no emitter anywhere (0 literal emit sites), 0 events in 104 runs,
                            530 subscriptions installed
  codehub/pr_opened         same shape: no emitter, 0 events, 463 subscriptions
  codehub/review_requested  an emitter exists but never runs: 0 events, 926 subscriptions
  codehub/merge_conflict    emitted from step_runner/workflow_policies, so the events carry
                            source_hub=frontend (2299) or backend (569) and never `codehub`;
                            2868 events exist and this subscription matches none -- they reach
                            the orchestrator through explicit `recipients` instead

The mirror of #1203f6: a recipient waiting for a finding nobody files. The remedy is the one
`validate_orphaned_tool_offerings` uses for the same class on the tool side -- say it once,
change no behaviour.
"""

import ast
import inspect
import io
import logging
import os
import unittest

from env_generator.llm_generator.multi_agent.runtime import agent_subscriptions as AS


class TheFrozenListDescribesRealWires(unittest.TestCase):

    def test_every_entry_names_a_subscription_that_actually_exists(self):
        """An entry about a wire nobody installs would report a defect that cannot happen."""
        installed = {(h, t) for subs in AS.DEFAULT_SUBSCRIPTIONS.values() for h, t, _ in subs}
        for pair in AS._NO_EMITTER_1203PB:
            self.assertIn(pair, installed, "%s/%s is not in DEFAULT_SUBSCRIPTIONS" % pair)

    def test_every_entry_carries_a_reason(self):
        for pair, why in AS._NO_EMITTER_1203PB.items():
            self.assertTrue(why and len(why) > 20, "%s/%s has no stated reason" % pair)

    def test_each_agents_dead_list_is_a_subset_of_its_own_subscriptions(self):
        for agent, subs in AS.DEFAULT_SUBSCRIPTIONS.items():
            mine = {(h, t) for h, t, _ in subs}
            for h, t, _why in AS.unsatisfiable_subscriptions_1203pb(agent):
                self.assertIn((h, t), mine)

    def test_an_agent_with_no_dead_wires_reports_none(self):
        self.assertEqual(AS.unsatisfiable_subscriptions_1203pb("no_such_agent"), [])

    def test_it_is_pure_and_needs_no_hub(self):
        sig = inspect.signature(AS.unsatisfiable_subscriptions_1203pb)
        self.assertEqual(list(sig.parameters), ["agent_id"])

    def test_the_docstring_says_why_the_list_is_frozen(self):
        """#883: a static scan can only FAIL to find an emitter, which is not proof of none."""
        doc = AS.unsatisfiable_subscriptions_1203pb.__doc__ or ""
        self.assertIn("NON-LITERAL", doc)
        self.assertIn("883", doc)


class NothingEmitsThem(unittest.TestCase):
    """The ratchet. If someone adds an emitter, the frozen entry must be removed."""

    @staticmethod
    def _literal_emit_types():
        root = os.path.dirname(os.path.dirname(inspect.getfile(AS)))   # .../multi_agent
        root = os.path.dirname(root)                                   # .../llm_generator
        found = set()
        for dp, _d, fns in os.walk(root):
            if os.sep + "tests" in dp or "__pycache__" in dp:
                continue
            for fn in sorted(fns):
                if not fn.endswith(".py"):
                    continue
                try:
                    with open(os.path.join(dp, fn), encoding="utf-8", errors="ignore") as fh:
                        tree = ast.parse(fh.read())
                except Exception:
                    continue
                for n in ast.walk(tree):
                    if not isinstance(n, ast.Call):
                        continue
                    name = (n.func.attr if isinstance(n.func, ast.Attribute)
                            else getattr(n.func, "id", ""))
                    if name not in ("_emit", "emit", "publish_event", "publish"):
                        continue
                    arg = n.args[0] if n.args else None
                    for kw in n.keywords:
                        if kw.arg == "event_type":
                            arg = kw.value
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
        return found

    def test_the_scan_reaches_the_framework(self):
        """#947: a ceiling of zero is evidence only while the scan is known to have looked."""
        types = self._literal_emit_types()
        self.assertGreater(len(types), 50, "the emit-site scan found almost nothing")
        self.assertIn("task_failed", types, "a known emitter is missing -- the scan is blind")

    def test_no_literal_emitter_exists_for_the_two_with_none(self):
        types = self._literal_emit_types()
        for t in ("task_stale", "pr_opened"):
            self.assertNotIn(t, types,
                             "%s now has an emitter -- remove its #1203pb entry" % t)

    def test_the_two_that_DO_have_an_emitter_say_so_in_their_reason(self):
        types = self._literal_emit_types()
        for (_h, t), why in AS._NO_EMITTER_1203PB.items():
            if t in types:
                self.assertTrue("emitter exists" in why or "emitted from" in why,
                                "%s has an emitter but its reason denies it" % t)


class ItSaysItOnceAndChangesNothing(unittest.TestCase):

    def setUp(self):
        AS._UNSATISFIABLE_SAID_1203PB.clear()
        self.stream = io.StringIO()
        self.h = logging.StreamHandler(self.stream)
        self.log = logging.getLogger(AS.__name__)
        self.log.addHandler(self.h)
        self.log.setLevel(logging.INFO)

    def tearDown(self):
        self.log.removeHandler(self.h)
        AS._UNSATISFIABLE_SAID_1203PB.clear()

    def test_the_line_names_the_agent_the_count_and_each_reason(self):
        AS.warn_unsatisfiable_subscriptions_1203pb("orchestrator")
        out = self.stream.getvalue()
        self.assertIn("orchestrator", out)
        self.assertIn("task_stale", out)
        self.assertIn("no emitter anywhere", out)

    def test_a_second_call_for_the_same_agent_is_silent(self):
        AS.warn_unsatisfiable_subscriptions_1203pb("orchestrator")
        first = self.stream.getvalue()
        AS.warn_unsatisfiable_subscriptions_1203pb("orchestrator")
        self.assertEqual(self.stream.getvalue(), first)

    def test_an_agent_with_nothing_dead_emits_no_line(self):
        AS.warn_unsatisfiable_subscriptions_1203pb("no_such_agent")
        self.assertEqual(self.stream.getvalue(), "")

    def test_it_says_the_delivery_is_unchanged(self):
        """It must not read as a new failure: these wires were already dead."""
        AS.warn_unsatisfiable_subscriptions_1203pb("verifier")
        self.assertIn("changes no delivery", self.stream.getvalue())

    def test_the_installer_calls_it(self):
        src = inspect.getsource(AS.ensure_default_subscriptions)
        self.assertIn("warn_unsatisfiable_subscriptions_1203pb", src,
                      "#1203f6: the report must reach a caller")

    def test_the_installer_reports_before_it_subscribes(self):
        src = inspect.getsource(AS.ensure_default_subscriptions)
        self.assertLess(src.index("warn_unsatisfiable_subscriptions_1203pb"),
                        src.index("eventhub.subscribe"),
                        "a later subscribe raising must not swallow the line")

    def test_a_reporter_failure_cannot_break_the_pulse(self):
        saved = AS._NO_EMITTER_1203PB
        try:
            class Hostile(dict):
                def get(self, *a, **k):
                    raise RuntimeError("no")
            AS._NO_EMITTER_1203PB = Hostile()
            AS.warn_unsatisfiable_subscriptions_1203pb("orchestrator")   # must not raise
        finally:
            AS._NO_EMITTER_1203PB = saved

    def test_the_hubless_installer_path_still_returns(self):
        AS.ensure_default_subscriptions(None, "orchestrator")


if __name__ == "__main__":
    unittest.main()
