r"""#1203pp: the spend cap was never compared with what delivering costs.

The ledger reads `ENVGEN_MAX_SPEND_USD`, records it (#1203fd) and the enforcement stops the
run at it. Nothing asked whether the number is an amount this generator has ever delivered a
milestone under, so a launch that cannot finish is indistinguishable from one that can until
the allowance is gone.

Measured over the 31 runs whose ledger records a cap (22 delivered at least one milestone):
the lowest cap that ever delivered is $150 (tiktok-web-r163, one milestone, and it spent
$187.61 -- $0.11 past the $187.50 that #1183's post-gate overshoot raised its ceiling to).
Two runs were capped below that, r188 at $12 and r187 at $45; both delivered nothing and both
stopped AT the cap, r188 after a single tick.

The function is pure so these properties have a driver at all: everything around it in
`run_budget.py` needs a live run directory and a process environment, which is why its
neighbours went unverified.
"""
import json
import os
import unittest

from env_generator.llm_generator.multi_agent.runtime import run_budget as RB

_SAY = RB.cap_below_delivering_floor_1203pp
_FLOOR = RB.DELIVERING_CAP_FLOOR_USD_1203PP


class TheSentenceMeansWhatItSays(unittest.TestCase):

    def test_r188s_cap_is_called_out(self):
        """★ THE TICKET, at the exact figure that bought one tick."""
        self.assertTrue(_SAY(12.0))

    def test_r187s_cap_is_called_out(self):
        self.assertTrue(_SAY(45.0))

    def test_the_floor_itself_is_not_called_out(self):
        """r163 DID deliver at $150. A guard wider than its evidence (#647) would flag the
        one cap in the record that worked."""
        self.assertEqual(_SAY(_FLOOR), "")

    def test_a_cap_above_the_floor_is_not_called_out(self):
        for cap in (150.01, 400.0, 900.0, 1700.0):
            self.assertEqual(_SAY(cap), "", cap)

    def test_it_names_the_cap_that_was_SET(self):
        """#983: a check that fires while naming nothing. The operator has to see their own
        number to recognise it as theirs."""
        self.assertIn("$12.00", _SAY(12.0))
        self.assertNotIn("$12.00", _SAY(45.0))

    def test_it_names_the_floor_and_the_run_that_set_it(self):
        s = _SAY(12.0)
        self.assertIn("$150.00", s)
        self.assertIn("tiktok-web-r163", s)

    def test_it_names_the_denominator(self):
        """n=1 at the floor and 2 below it. A sentence that hid that would be making a
        prediction out of three runs."""
        s = _SAY(12.0)
        for part in ("31 runs", "22 delivered", "2 capped"):
            self.assertIn(part, s, s)

    def test_it_says_it_is_not_a_prediction(self):
        self.assertIn("not a prediction", _SAY(12.0))

    def test_it_says_the_cap_is_still_being_obeyed(self):
        """#1202ii: an explicit env var is an instruction. A $12 smoke test is legitimate
        and the run must not read as though the cap will be raised for it."""
        self.assertIn("obeyed as set", _SAY(12.0))

    def test_absent_is_not_zero(self):
        """#1026b, and 0.0 is also how the enforcement spells unlimited."""
        for v in (None, "", "   ", 0, 0.0, "0", -5, "-5"):
            self.assertEqual(_SAY(v), "", repr(v))

    def test_junk_does_not_raise(self):
        for v in ("abc", "$300", [], {}, object()):
            self.assertEqual(_SAY(v), "", repr(v))

    def test_a_string_cap_is_read_as_a_number(self):
        """It is read straight off the environment, where everything is a string."""
        self.assertTrue(_SAY("12"))
        self.assertEqual(_SAY("900"), "")

    def test_the_floor_is_a_parameter(self):
        """So a later measurement replaces the number rather than forking the sentence
        (#1202vs: a correction must replace the figure, not add a copy)."""
        self.assertTrue(_SAY(200.0, floor=400.0))
        self.assertEqual(_SAY(500.0, floor=400.0), "")


class TheLedgerCarriesIt(unittest.TestCase):
    """#1203fd's own lesson: a cap readable only from the live environment is gone to anyone
    reading the finished run. A note kept only in a log line has the same hole."""

    def _caps(self, cap):
        env = dict(os.environ)
        if cap is None:
            env.pop("ENVGEN_MAX_SPEND_USD", None)
        else:
            env["ENVGEN_MAX_SPEND_USD"] = str(cap)
        old = os.environ
        try:
            os.environ = env  # noqa: B003 - _caps_1203fd reads os.environ directly
            return RB._caps_1203fd({"max_wall_sec": 100.0, "max_ticks": 5})
        finally:
            os.environ = old

    def test_a_low_cap_is_recorded_beside_the_cap(self):
        out = self._caps(12)
        self.assertEqual(out["max_spend_usd"], 12.0)
        self.assertTrue(out["below_delivering_floor_1203pp"])
        self.assertIn("$12.00", out["below_delivering_floor_1203pp"])

    def test_a_healthy_cap_records_None_not_absent(self):
        """None, not a missing key: a reader has to tell "checked, above the floor" from an
        older ledger that never checked (#883 -- 'could not tell' is not 'clean')."""
        out = self._caps(900)
        self.assertIn("below_delivering_floor_1203pp", out)
        self.assertIsNone(out["below_delivering_floor_1203pp"])

    def test_no_cap_records_None(self):
        out = self._caps(None)
        self.assertIsNone(out["max_spend_usd"])
        self.assertIsNone(out["below_delivering_floor_1203pp"])

    def test_the_field_survives_json(self):
        self.assertIn("1203pp", json.dumps(self._caps(45)))


class _Spy:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *args):
        self.lines.append(fmt % args if args else fmt)

    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


class TheOperatorIsToldOnce(unittest.TestCase):
    """`load_caps` runs on every tick to pick up a live cap raise (#1202ii), so the line has
    to be said once -- #1041's storm is the failure mode on the other side."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from env_generator.llm_generator.multi_agent.runtime import message_format as MF
        MF._STATE_SAID_1202AD.pop("run_budget.cap_floor_1203pp", None)
        self.addCleanup(MF._STATE_SAID_1202AD.pop, "run_budget.cap_floor_1203pp", None)
        self._old = os.environ.get("ENVGEN_MAX_SPEND_USD")

        def _restore():
            if self._old is None:
                os.environ.pop("ENVGEN_MAX_SPEND_USD", None)
            else:
                os.environ["ENVGEN_MAX_SPEND_USD"] = self._old
        self.addCleanup(_restore)

    def _budget(self):
        spy = _Spy()
        return RB.RunBudget(self._tmp.name, spy), spy

    _DEF = {"max_wall_sec": 100.0, "max_ticks": 5, "unlimited": False}

    def _said(self, spy):
        return [l for l in spy.lines if "1203pp" in l]

    def test_a_low_cap_is_said(self):
        os.environ["ENVGEN_MAX_SPEND_USD"] = "12"
        b, spy = self._budget()
        b.load_caps(dict(self._DEF))
        self.assertEqual(len(self._said(spy)), 1, spy.lines)
        self.assertIn("$12.00", self._said(spy)[0])

    def test_it_is_said_ONCE_across_a_whole_run(self):
        os.environ["ENVGEN_MAX_SPEND_USD"] = "12"
        b, spy = self._budget()
        for _ in range(40):
            b.load_caps(dict(self._DEF))
        self.assertEqual(len(self._said(spy)), 1, self._said(spy))

    def test_raising_the_cap_to_another_low_value_is_said_again(self):
        """The sentence is about the cap, so a cap that CHANGED is a new fact. Keyed on the
        value, not on the process."""
        os.environ["ENVGEN_MAX_SPEND_USD"] = "12"
        b, spy = self._budget()
        b.load_caps(dict(self._DEF))
        os.environ["ENVGEN_MAX_SPEND_USD"] = "45"
        b.load_caps(dict(self._DEF))
        said = self._said(spy)
        self.assertEqual(len(said), 2, said)
        self.assertIn("$45.00", said[1])

    def test_a_healthy_cap_says_nothing(self):
        os.environ["ENVGEN_MAX_SPEND_USD"] = "900"
        b, spy = self._budget()
        for _ in range(5):
            b.load_caps(dict(self._DEF))
        self.assertEqual(self._said(spy), [])

    def test_no_cap_says_nothing(self):
        os.environ.pop("ENVGEN_MAX_SPEND_USD", None)
        b, spy = self._budget()
        b.load_caps(dict(self._DEF))
        self.assertEqual(self._said(spy), [])

    def test_it_is_said_on_a_FRESH_run_directory_too(self):
        """`load_caps` has TWO returns and a fresh run takes the second one: with no ledger
        on disk `read_text` raises and the `except` branch returns the env defaults. That is
        every first tick of every new run -- the one launch the operator can still fix -- so
        a call wired onto the success path alone would be silent exactly when it matters
        most. Both paths say it; this drives the one a new run actually takes."""
        os.environ["ENVGEN_MAX_SPEND_USD"] = "12"
        b, spy = self._budget()
        self.assertFalse(os.path.exists(b.path()), "the fixture is not a fresh directory")
        b.load_caps(dict(self._DEF))
        self.assertEqual(len(self._said(spy)), 1, spy.lines)

    def test_a_budget_with_no_logger_does_not_raise(self):
        os.environ["ENVGEN_MAX_SPEND_USD"] = "12"
        b = RB.RunBudget(self._tmp.name, None)
        b.load_caps(dict(self._DEF))

    def test_the_caps_it_returns_are_unchanged_by_the_check(self):
        """It reports; it does not adjust. Silently raising a cap would spend money the
        operator declined."""
        os.environ["ENVGEN_MAX_SPEND_USD"] = "12"
        b, _ = self._budget()
        out = b.load_caps(dict(self._DEF))
        self.assertEqual(out["max_wall_sec"], 100.0)
        self.assertEqual(out["max_ticks"], 5)
        self.assertNotIn("max_spend_usd", out)


if __name__ == "__main__":
    unittest.main()
