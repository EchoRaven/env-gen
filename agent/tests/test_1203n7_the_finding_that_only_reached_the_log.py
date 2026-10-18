r"""#1203n7: #1203ga found 6 dangling seed rows, said so 1182 times, and told nobody.

TWO DEFECTS, one call site.

1. NO RECIPIENT. #1203ga's own comment says it is "Reported, not blocking, which is #1168's
   stated policy for this exact property ('evidence for the lane', #566j: a false seed
   blocker wedges a run)". It copied the POLICY and not the CHANNEL. #1168's comment says
   why the channel matters in its own words -- it "rides here because this dict is what the
   gate report prints, so a seed whose rows point at nothing stops being invisible" --
   whereas #1203ga had only `logging.getLogger(__name__).warning(...)`. #1139's shape from
   the other side: the finding existed and reached no reader.

   MEASURED, and this is the part that makes the channel worth having: `seed_data` IS
   persisted -- 30 corpus runs' stored records carry its `flagged_tables` -- while
   `orphan_fk_rows`, #1168's OWN payload on that same channel, appears in 0 of 5708 stored
   records, because it answers from the live database #1039 records as essentially never
   available. The authored seed file is on disk the whole time.

2. ONE LINE, 1182 TIMES. r190 emitted exactly ONE distinct message
   ("#1203ga the authored seed has 6 row(s) ... feed.sound_id=6") 624 times in its first
   leg, 424 in the third and 134 in the second -- 1182 identical lines for one fact. The
   gate recomputes every tick and the warning had no latch, while this very module carries
   #760/#762's say-once memory and a `reset_said_700()` contract for tests.

The latch is keyed on the FINDING, not on the gate: a seed the lane partly repaired (6
dangling rows -> 3) must speak again rather than be swallowed, which is the failure mode
#760's say-once has to avoid. Blocking behaviour is deliberately unchanged (#566j).
"""
import ast
import inspect
import unittest

from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    DeliverabilityReport,
    compute_deliverability,
    record_authored_orphan_fk_1203n7 as record,
    reset_said_700,
)


class ItRidesTheChannel1168Uses(unittest.TestCase):
    def setUp(self):
        reset_said_700()

    def test_the_rows_and_the_total_land_on_the_seed_dict(self):
        seed = {"tables": 3}
        record(seed, {"feed.sound_id": 6, "comments.user_id": 2})
        self.assertEqual(seed["authored_orphan_fk_rows_1203ga"],
                         {"feed.sound_id": 6, "comments.user_id": 2})
        self.assertEqual(seed["authored_orphan_fk_total_1203ga"], 8)

    def test_it_does_not_disturb_what_1168_already_put_there(self):
        seed = {"orphan_fk_rows": {"x.y": 1}, "orphan_fk_total": 1, "flagged": 2}
        record(seed, {"feed.sound_id": 6})
        self.assertEqual(seed["orphan_fk_rows"], {"x.y": 1})
        self.assertEqual(seed["flagged"], 2)

    def test_the_keys_survive_the_report_serialiser(self):
        """The consumer half. #1139 shipped a key nothing read; this asserts the key actually
        comes out the other side of what the gate record is built from."""
        seed = {}
        record(seed, {"feed.sound_id": 6})
        out = DeliverabilityReport(seed_data=seed).to_dict()
        self.assertEqual(out["seed_data"]["authored_orphan_fk_total_1203ga"], 6)
        self.assertIn("feed.sound_id", out["seed_data"]["authored_orphan_fk_rows_1203ga"])

    def test_nothing_is_written_when_there_is_no_finding(self):
        for empty in ({}, None, [], "nope"):
            with self.subTest(orphans=repr(empty)):
                seed = {}
                self.assertFalse(record(seed, empty))
                self.assertEqual(seed, {})


class ItSaysItOncePerFinding(unittest.TestCase):
    def setUp(self):
        reset_said_700()

    def test_the_same_finding_speaks_once(self):
        self.assertTrue(record({}, {"feed.sound_id": 6}))
        self.assertFalse(record({}, {"feed.sound_id": 6}))
        self.assertFalse(record({}, {"feed.sound_id": 6}))

    def test_a_partly_repaired_seed_speaks_again(self):
        """6 dangling rows -> 3 is news. A latch keyed on the gate would have eaten it."""
        self.assertTrue(record({}, {"feed.sound_id": 6}))
        self.assertTrue(record({}, {"feed.sound_id": 3}))

    def test_a_new_table_speaks_again(self):
        self.assertTrue(record({}, {"feed.sound_id": 6}))
        self.assertTrue(record({}, {"feed.sound_id": 6, "comments.user_id": 1}))

    def test_key_order_is_not_a_new_finding(self):
        self.assertTrue(record({}, {"a.x": 1, "b.y": 2}))
        self.assertFalse(record({}, {"b.y": 2, "a.x": 1}))

    def test_the_channel_is_still_written_on_a_silenced_repeat(self):
        """The latch is about the LOG. A later tick's gate record must still carry the finding,
        or silencing the line would also delete the evidence."""
        self.assertTrue(record({}, {"feed.sound_id": 6}))
        seed = {}
        self.assertFalse(record(seed, {"feed.sound_id": 6}))
        self.assertEqual(seed["authored_orphan_fk_total_1203ga"], 6)

    def test_reset_said_700_covers_it(self):
        """#762's contract: module state must not leak between tests in one session."""
        self.assertTrue(record({}, {"feed.sound_id": 6}))
        reset_said_700()
        self.assertTrue(record({}, {"feed.sound_id": 6}))


class ItNeverRaises(unittest.TestCase):
    def setUp(self):
        reset_said_700()

    def test_a_seed_that_is_not_a_dict_still_lets_the_line_speak(self):
        """The channel cannot be written, so the log is all that is left -- losing the finding
        entirely would be worse. The only caller passes `_seed_summary`'s dict, pinned by
        `TheCallSiteUsesIt` below, so this is a type guard and not a degradation path."""
        self.assertTrue(record("nope", {"feed.sound_id": 6}))

    def test_unstringable_counts(self):
        class _Bad:
            def __int__(self):
                raise ValueError("no")
        self.assertFalse(record({}, {"feed.sound_id": _Bad()}))


class TheCallSiteUsesIt(unittest.TestCase):
    """#1032/#772: one owner. Asserted on the AST so a comment quoting the call cannot feed it
    -- the trap this repo has recorded three times."""

    def _call(self):
        tree = ast.parse(inspect.getsource(compute_deliverability).lstrip())
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "record_authored_orphan_fk_1203n7"):
                return n
        return None

    def test_the_gate_calls_the_helper(self):
        self.assertIsNotNone(self._call(),
                             "the authored-orphan finding is back to log-only")

    def test_it_passes_the_seed_summary_dict(self):
        node = self._call()
        self.assertTrue(node.args, "the helper was called with no seed")
        self.assertEqual(getattr(node.args[0], "id", None), "seed",
                         "the finding is not being written onto the gate report's seed dict")

    def test_the_warning_only_fires_when_the_helper_says_so(self):
        """It must gate the log, not merely run beside it."""
        src = inspect.getsource(compute_deliverability)
        tree = ast.parse(src.lstrip())
        gated = False
        for n in ast.walk(tree):
            if isinstance(n, ast.If) and "record_authored_orphan_fk_1203n7" in ast.dump(n.test):
                for sub in ast.walk(n):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "warning"):
                        gated = True
        self.assertTrue(gated, "the warning is not inside the helper's condition")


class TheBlockingBehaviourIsUnchanged(unittest.TestCase):
    """#566j: a false seed blocker wedges a run. This ticket moves a finding onto a channel;
    it must not turn it into a blocker."""

    def test_the_helper_cannot_reach_the_blockers_list(self):
        src = inspect.getsource(record)
        self.assertNotIn("blockers", src)

    def test_the_message_still_says_it_is_not_blocking(self):
        """Anchored on the AST node, not on a byte window -- #943's ratchet caught the first
        version of this assertion (`src[i:i+1200]`), which is the trap this repo records: a
        window sized in bytes breaks when a COMMENT grows."""
        tree = ast.parse(inspect.getsource(compute_deliverability).lstrip())
        said = []
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "warning" and n.args):
                lit = n.args[0]
                if isinstance(lit, ast.Constant) and isinstance(lit.value, str) \
                        and lit.value.startswith("#1203ga"):
                    said.append(lit.value)
        self.assertTrue(said, "the #1203ga warning is gone")
        self.assertIn("Reported, not blocking", said[0])


if __name__ == "__main__":
    unittest.main()
