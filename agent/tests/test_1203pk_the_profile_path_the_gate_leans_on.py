"""#1203pk: `_ensure_profile_selected` (#548a) and `_wait_seed_settled` (#548b) had no test.

Found by asking which framework ticket markers no test names -- 27 of 1934, and these two were
among the few with real behaviour behind them. Both sit on the path the visual gate leans on:
#548a's own docstring is "(Re-)establish an ACTIVE profile so protected routes render real
content". If it stops working, protected routes render empty, every screen scores near zero, and
the gate reports the app rather than the capture -- which is the shape #1203ov is about
("nothing observed is not a failed login") and the subsystem holding the top two end-game
blockers.

The contract in the docstring is "each step best-effort; never raises", and that matters more
than usual here: this runs inside the capture loop, so a raise does not degrade one screen, it
loses the round. The tests below drive every arm, including the one where every call raises.

Both halves of the persist are pinned separately (#1139/#1148: a precedent has two halves, and
copying one is how a mechanism ends up with no consumer). The init script has to reach the
CONTEXT, for future page loads, AND be evaluated on the CURRENT page, for this one -- the
docstring says so, and a single-half version would pass any test that only checked a return
value.
"""

import asyncio
import unittest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


class _Page:
    """A playwright-ish page that dispatches on which JS it is handed."""

    def __init__(self, profile_id="p-1", picker=False, raises=()):
        self.profile_id = profile_id
        self.picker = picker
        self.raises = set(raises)          # "discover", "persist", "picker", "timeout"
        self.evaluated = []
        self.waited = []

    async def evaluate(self, js, *args):
        self.evaluated.append(js)
        if js is vf._PROFILE_DISCOVER_JS:
            if "discover" in self.raises:
                raise RuntimeError("discover failed")
            return self.profile_id
        if js is vf._PROFILE_PICKER_CLICK_JS:
            if "picker" in self.raises:
                raise RuntimeError("picker failed")
            return self.picker
        if "persist" in self.raises:
            raise RuntimeError("persist failed")
        return None

    async def wait_for_timeout(self, ms):
        if "timeout" in self.raises:
            raise RuntimeError("timeout failed")
        self.waited.append(ms)


class _Ctx:
    def __init__(self, raises=False):
        self.raises = raises
        self.scripts = []

    async def add_init_script(self, js):
        if self.raises:
            raise RuntimeError("init script rejected")
        self.scripts.append(js)


def _run(page, ctx, token="tok"):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(vf._ensure_profile_selected(page, ctx, token))
    finally:
        loop.close()


class ItReEstablishesAProfile(unittest.TestCase):

    def test_a_discovered_id_is_persisted_and_reported(self):
        page, ctx = _Page(profile_id="p-7"), _Ctx()
        self.assertTrue(_run(page, ctx))

    def test_the_id_reaches_BOTH_the_context_and_the_current_page(self):
        """#1139/#1148: two halves. The init script is for future loads; the current page needs
        its own evaluate or this capture still renders the logged-out view."""
        page, ctx = _Page(profile_id="p-7"), _Ctx()
        _run(page, ctx)
        self.assertEqual(len(ctx.scripts), 1, "the init script never reached the context")
        self.assertIn("p-7", ctx.scripts[0])
        persisted = [j for j in page.evaluated
                     if isinstance(j, str) and "p-7" in j and j.startswith("() => {")]
        self.assertTrue(persisted, "the id was never applied to the CURRENT page")

    def test_the_rediscovery_happens_before_the_persist(self):
        """A re-seed invalidates a previously-persisted id, so the id must come from the app's
        own endpoint on this pass, not from whatever was stored last time."""
        page, ctx = _Page(profile_id="p-7"), _Ctx()
        _run(page, ctx)
        self.assertIs(page.evaluated[0], vf._PROFILE_DISCOVER_JS)


class ThePickerPathIsTheFallback(unittest.TestCase):

    def test_clicking_a_picker_tile_counts_as_selected(self):
        """The app's own handler persists under the app's OWN key, which is what defeats
        storage-key variance between lanes."""
        page, ctx = _Page(profile_id=None, picker=True), _Ctx()
        self.assertTrue(_run(page, ctx))

    def test_the_picker_click_is_given_time_to_settle(self):
        page, ctx = _Page(profile_id=None, picker=True), _Ctx()
        _run(page, ctx)
        self.assertTrue(page.waited, "the click was not given any time to take effect")

    def test_no_id_means_no_init_script(self):
        """Persisting an empty id would overwrite a working one with nothing."""
        page, ctx = _Page(profile_id=None, picker=False), _Ctx()
        self.assertFalse(_run(page, ctx))
        self.assertEqual(ctx.scripts, [])

    def test_neither_path_working_reports_FALSE_rather_than_raising(self):
        page, ctx = _Page(profile_id=None, picker=False), _Ctx()
        self.assertIs(_run(page, ctx), False)


class ItNeverRaisesIntoTheCaptureLoop(unittest.TestCase):
    """The docstring's contract. A raise here loses the ROUND, not one screen."""

    def test_a_failing_discovery_does_not_raise(self):
        self.assertIs(_run(_Page(raises=["discover"]), _Ctx()), False)

    def test_a_rejected_init_script_still_tries_the_current_page(self):
        page, ctx = _Page(profile_id="p-7"), _Ctx(raises=True)
        self.assertTrue(_run(page, ctx), "a context that refuses the script lost the page path")

    def test_a_failing_persist_does_not_raise(self):
        page, ctx = _Page(profile_id="p-7", raises=["persist"]), _Ctx()
        self.assertIs(_run(page, ctx), False)

    def test_a_failing_picker_probe_does_not_raise(self):
        page, ctx = _Page(profile_id=None, raises=["picker"]), _Ctx()
        self.assertIs(_run(page, ctx), False)

    def test_everything_failing_at_once_does_not_raise(self):
        page = _Page(profile_id=None, raises=["discover", "persist", "picker", "timeout"])
        self.assertIs(_run(page, _Ctx(raises=True)), False)

    def test_a_failing_settle_wait_DISCARDS_the_successful_click(self):
        """Documents current behaviour rather than asserting what I first assumed.

        `ok = True` is set AFTER `wait_for_timeout`, inside the same try, so a failure in the
        wait throws away the knowledge that the click succeeded and the function reports False.
        Deliberately left as it is: `wait_for_timeout` failing is near-hypothetical, the cost is
        one extra click next round, and reordering a line in the capture path for a case with no
        corpus evidence is the kind of change #647 warns against. Pinned so that if the ordering
        ever matters, this test says what it used to do.
        """
        page, ctx = _Page(profile_id=None, picker=True, raises=["timeout"]), _Ctx()
        self.assertIs(_run(page, ctx), False)


if __name__ == "__main__":
    unittest.main()


# --- #548b: the seed-settle gate, also untested ---------------------------------------------------
#
# Same origin as the above (a ticket marker no test named). Its job is to stop a capture starting
# DURING a mid-run re-seed that momentarily wiped the profiles table -- which would photograph an
# empty app and score it as the app's fault. The contract is "non-empty AND stable (same count on
# two consecutive polls)", with three early exits: no endpoint, an unreadable count, and a spent
# poll budget. All of them must return rather than raise, because this runs before the capture.


class _CountPage:
    """A page whose profile-count poll returns a scripted sequence."""

    def __init__(self, counts, raise_on=None):
        self.counts = list(counts)
        self.raise_on = raise_on          # index at which `evaluate` raises
        self.polls = 0
        self.waits = 0

    async def evaluate(self, js, *args):
        i = self.polls
        self.polls += 1
        if self.raise_on is not None and i == self.raise_on:
            raise RuntimeError("count probe failed")
        return self.counts[i] if i < len(self.counts) else self.counts[-1]

    async def wait_for_timeout(self, ms):
        self.waits += 1


def _settle(page):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(vf._wait_seed_settled(page, "tok"))
    finally:
        loop.close()


class ItWaitsForTheSeedToSettle(unittest.TestCase):

    def test_a_stable_nonempty_count_stops_the_wait(self):
        """Two consecutive equal non-zero counts is the whole definition of settled."""
        page = _CountPage([3, 3])
        _settle(page)
        self.assertEqual(page.polls, 2, "it did not stop at the first stable pair")

    def test_a_count_that_is_still_moving_keeps_polling(self):
        """A re-seed in progress shows a changing count, which is exactly when NOT to capture."""
        page = _CountPage([1, 2, 3, 3])
        _settle(page)
        self.assertGreaterEqual(page.polls, 4, page.polls)

    def test_an_empty_table_is_never_treated_as_stable(self):
        """0 == 0 is stable by arithmetic and must NOT satisfy the gate -- capturing then is the
        bug: the app renders empty and the gate blames the app."""
        page = _CountPage([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        _settle(page)
        self.assertGreaterEqual(page.polls, 3,
                                "a zero count read as settled after %d polls" % page.polls)

    def test_no_profiles_endpoint_returns_at_once(self):
        """-1 means no endpoint, so there is no gate to satisfy and such apps must be
        byte-identical to before this existed."""
        page = _CountPage([-1, -1])
        _settle(page)
        self.assertEqual(page.polls, 1)
        self.assertEqual(page.waits, 0)

    def test_the_poll_budget_is_bounded(self):
        """A table that never settles must not block the capture for ever."""
        page = _CountPage([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
        _settle(page)
        self.assertLessEqual(page.polls, max(1, vf._SEED_SETTLE_POLLS), page.polls)

    def test_a_failing_probe_returns_rather_than_raising(self):
        self.assertIsNone(_settle(_CountPage([1, 1], raise_on=0)))

    def test_an_unreadable_count_returns_rather_than_raising(self):
        self.assertIsNone(_settle(_CountPage(["not-a-number"])))

    def test_it_returns_None_on_every_path(self):
        """It is called for its blocking, not its value; a truthy return would invite a caller
        to branch on it."""
        for counts in ([3, 3], [-1], [0, 0], ["x"]):
            self.assertIsNone(_settle(_CountPage(counts)), counts)
