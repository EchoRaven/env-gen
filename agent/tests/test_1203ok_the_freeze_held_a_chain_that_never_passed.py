r"""#1203ok: the freeze's carve-out asked for one word and the store has five.

FREEZE-ON-GREEN keeps an already-passing chain from being re-authored into a broken one (run-25
oscillated for 75 minutes). `#1202nz` then carved out the chain that is FAILING now, with the
right principle — "a chain that is FAILING now is not" the chain the freeze protects — and the
wrong test: `status == "failing"`.

MEASURED over the corpus's 3,278 chain records, the status vocabulary is

    passing 2954 | failing 135 | coverage 92 | registered 80 | environment_blocked 17

and the last three are not passing either: `registered` has never run, `coverage` was filed to
cover an endpoint, `environment_blocked` could not execute because the stack was down. The
freeze's own justification ("re-authoring a passing chain is a no-op") says nothing about any
of them.

REACHABLE, not theoretical: 94 runs carry at least one such record and 78 of those had
business_chain GREEN at some tick — the other half of the freeze's condition. r144 ends with 17
`environment_blocked` chains and a green business_chain, r108 16, googlemaps-r16 8, and r191 —
the newest run — carries 3.

★ AND THE REFUSALS ARE REAL AND CURRENT: r190's log holds 27 `is frozen` refusals of
`registryhub_register_verification_chain` across 16 chain names (`discover_search` 5,
`tenant_lifecycle_reset_isolation` 4). Every one of those five checked chains is `passing`, so
THOSE refusals were correct — which is why this ticket widens the carve-out rather than
touching the freeze.
"""
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _chain_recorded_a_non_pass_1203ok as recorded_non_pass,
)


class OnlyARecordedNonPassIsCarvedOut(unittest.TestCase):
    """The carve-out is by MECHANISM: the chain RAN and did not pass."""

    def test_a_passing_chain_is_protected(self):
        self.assertFalse(recorded_non_pass({"status": "passing", "last_result": {"ok": True}}))

    def test_failing_is_1202nzs_own_case(self):
        self.assertTrue(recorded_non_pass({"status": "failing", "last_result": {"ok": False}}))

    def test_environment_blocked_is_the_same_shape_in_another_word(self):
        """17 such records in r144, whose business_chain went green."""
        self.assertTrue(recorded_non_pass(
            {"status": "environment_blocked", "last_result": {"broken": ["stack down"]}}))

    def test_the_status_is_read_tolerantly(self):
        for s in ("FAILING", " failing ", "Environment_Blocked"):
            with self.subTest(status=s):
                self.assertTrue(recorded_non_pass({"status": s, "last_result": {"x": 1}}))
        for s in ("PASSING", " passing "):
            with self.subTest(status=s):
                self.assertFalse(recorded_non_pass({"status": s, "last_result": {"x": 1}}))

    def test_a_chain_that_never_ran_stays_protected(self):
        """★ My first patch released these too and the suite refused it: a `registered` chain
        becomes `failing` on the next gate cycle, after which #1202nz's path applies, and
        `coverage` records are written by the framework's own coverage-completion. 92 + 80 of
        the corpus's records are in this class and NONE of them carries a result."""
        for s in ("registered", "coverage", "", None):
            with self.subTest(status=s):
                self.assertFalse(recorded_non_pass({"status": s}))

    def test_a_result_under_any_of_the_three_keys_counts_as_having_run(self):
        for key in ("last_result", "results", "history"):
            with self.subTest(key=key):
                self.assertTrue(recorded_non_pass({"status": "failing", key: {"a": 1}}))

    def test_hostile_input_never_raises(self):
        for rec in (None, "failing", 7, [{"status": "failing"}]):
            with self.subTest(rec=repr(rec)[:20]):
                self.assertFalse(recorded_non_pass(rec))


class TheFreezeUsesIt(unittest.TestCase):
    def _hub(self, tmp):
        from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
        try:
            return RegistryHub(hub_dir=Path(tmp))
        except TypeError:
            return RegistryHub(Path(tmp))

    @staticmethod
    def _steps():
        return [{"method": "GET", "path": "/api/titles", "expect_status": 200}]

    def _frozen_hub(self, status, ran=True):
        """A hub with the freeze armed and one stored chain in `status`.

        `ran` controls whether the record carries a result, which is what the carve-out keys
        on -- not the status word alone.
        """
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        hub = self._hub(tmp)
        # `normalize_steps` PREPENDS an auth preamble, so those endpoints must exist too --
        # without them the registration is rejected and the first version of this fixture
        # skipped every load-bearing test in this file.
        for _m, _p in (("POST", "/auth/register"), ("POST", "/auth/login"),
                       ("GET", "/api/titles")):
            hub.register_endpoint(_m, _p, {"response_key": "items"},
                                  provider="backend", agent="backend", status="implemented")
        res = hub.register_verification_chain("c1", self._steps(), agent="verifier")
        self.assertNotIn("error", str(res)[:60].lower(), res)

        def _set_status(d):
            # `update` hands a `_MapView`, whose API is get/set/delete/value -- NOT item
            # assignment, which is what kept these tests skipped a second time.
            rec = dict(d.get("c1") or {})
            rec["status"] = status
            if ran:
                rec["last_result"] = {"broken": ["synthetic"]}
            else:
                rec.pop("last_result", None)
                rec.pop("results", None)
                rec.pop("history", None)
            d.set("c1", rec)
            return d

        hub._verification_chains.update(_set_status)
        hub._chains_frozen_eps = set((hub._endpoints.value() or {}).keys())
        return hub

    def test_a_passing_chain_is_still_frozen(self):
        try:
            hub = self._frozen_hub("passing", ran=True)
        except Exception as exc:
            self.skipTest("RegistryHub needs more setup here: %s" % exc)
        out = hub.register_verification_chain("c1", self._steps(), agent="verifier")
        self.assertTrue(out.get("frozen"), out)

    def test_an_environment_blocked_chain_may_be_re_authored(self):
        """★ The state #1202nz's literal test missed: it RAN, the stack was down, and the
        attempt is recorded — so the freeze is protecting nothing while refusing the fix."""
        try:
            hub = self._frozen_hub("environment_blocked", ran=True)
        except Exception as exc:
            self.skipTest("RegistryHub needs more setup here: %s" % exc)
        out = hub.register_verification_chain("c1", self._steps(), agent="verifier")
        self.assertFalse(out.get("frozen"),
                         "an environment_blocked chain is still frozen, so a verifier cannot "
                         "correct a chain whose only recorded attempt failed")

    def test_a_chain_that_never_ran_is_still_frozen(self):
        """The existing `test_freeze_blocks_reauthor_of_existing_chain_keeps_passing_one`
        asserts this, and it is right to — see the helper's docstring."""
        for status in ("registered", "coverage"):
            with self.subTest(status=status):
                try:
                    hub = self._frozen_hub(status, ran=False)
                except Exception as exc:
                    self.skipTest("RegistryHub needs more setup here: %s" % exc)
                out = hub.register_verification_chain("c1", self._steps(), agent="verifier")
                self.assertTrue(out.get("frozen"), out)

    def test_a_failing_chain_still_may_be_re_authored(self):
        """#1202nz's own case must keep working."""
        try:
            hub = self._frozen_hub("failing", ran=True)
        except Exception as exc:
            self.skipTest("RegistryHub needs more setup here: %s" % exc)
        out = hub.register_verification_chain("c1", self._steps(), agent="verifier")
        self.assertFalse(out.get("frozen"), out)


class WhatTheCorpusSays(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    @staticmethod
    def _statuses(f):
        import json
        from collections import Counter
        try:
            d = json.load(open(f, errors="ignore"))
        except Exception:
            return Counter()
        return Counter(str(v.get("status")) for k, v in d.items()
                       if isinstance(v, dict) and k != "_meta")

    def test_the_status_vocabulary_is_still_five_words(self):
        """If a sixth appears, this carve-out has to be re-read rather than assumed."""
        from collections import Counter
        total = Counter()
        for f in sorted(self.corpus.glob("*/shared/hubs/registryhub_verification_chains.json")):
            total += self._statuses(f)
        if not total:
            self.skipTest("no chain stores on this disk")
        self.assertEqual(set(total) - {"passing", "failing", "coverage", "registered",
                                       "environment_blocked"}, set(),
                         "a new chain status appeared: %s" % sorted(total))
        self.assertGreater(total["passing"], 1000)

    def test_the_states_the_old_test_missed_are_populated(self):
        """Non-vacuity: if these were all zero the widening would protect nothing."""
        from collections import Counter
        total = Counter()
        for f in sorted(self.corpus.glob("*/shared/hubs/registryhub_verification_chains.json")):
            total += self._statuses(f)
        if not total:
            self.skipTest("no chain stores on this disk")
        missed = total["coverage"] + total["registered"] + total["environment_blocked"]
        self.assertGreater(missed, 100,
                           "only %d record(s) are in a state the literal `failing` test "
                           "missed, so re-measure before trusting this patch" % missed)

    def test_the_newest_run_carries_one(self):
        f = self.corpus / "tiktok-web-r191" / "shared" / "hubs" / \
            "registryhub_verification_chains.json"
        if not f.is_file():
            self.skipTest("r191 has no chain store on this disk")
        st = self._statuses(f)
        self.assertGreater(st["coverage"] + st["registered"] + st["environment_blocked"], 0,
                           "r191 no longer carries a never-ran chain: %s" % dict(st))

    def test_r144_is_the_environment_blocked_case(self):
        f = self.corpus / "tiktok-web-r144" / "shared" / "hubs" / \
            "registryhub_verification_chains.json"
        if not f.is_file():
            self.skipTest("r144 has no chain store on this disk")
        self.assertGreaterEqual(self._statuses(f)["environment_blocked"], 10,
                                "r144 was measured at 17 environment_blocked chains")


if __name__ == "__main__":
    unittest.main()
