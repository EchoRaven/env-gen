r"""#1203oj: the breaking-change P0 went to the lane that does not own the file.

`_record_breaking_change` files one P0 per CONSUMER agent and takes that agent from the
registered consumer record. MEASURED WITH THE SHIPPED PREDICATE: 169 of the corpus's 9,539
consumer records, across 26 runs, disagree with their own `file_path` — dominantly
`agent: backend` naming `app/frontend/src/services/api.js`:

    tiktok-web-r181 29   netflix-local-r43 21   tiktok-web-r120 16
    tiktok-web-r172 15   netflix-local-r32 14   netflix-local-r5   8   (+20 more runs)

On the other side: of the corpus's 2,736 breaking-change tasks, 273 in 16 runs are assigned to
a lane their own `affected_files` contradict — "Fix breaking change in GET /api/titles",
`affected_files: app/frontend/src/services/api.js`, `assignee: backend`, P0. r191 has 17, so it
is current.

★ MY FIRST NUMBERS WERE 109/14 AND 209, from a throwaway scan whose path test accepted
`frontend/` without the `app/` prefix. These are what the shipped predicate says, re-measured
after it existed.

WHAT IT COSTS, in a lane's own words: netflix-local-r21's backend wrote FOUR triage comments of
the form "This should be reassigned to frontend/debugger ... not backend". (That run's tasks
come from a different source, so it is the cost of the SHAPE, not of these 109 records.)

★ THE FILE IS THE STRONGER EVIDENCE — #1203np's rule, "the owner comes from the cause": the
file is the thing that must change, while `agent` is a claim made at registration. The task is
redirected and the description says BOTH; the registration is left alone, because it is also
the link that made the consumer reachable and dropping it would lose that.

★ FOUND BY READING WHAT THE LANES SAID TO EACH OTHER — `workhub_comments.json`, 3,304 comments
across 104 runs. The same instrument as #1203mz (the lane's own code comments), one surface up.
"""
import json
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _breaking_task_owner_1203oj as owner,
    _consumer_file_lane_1203oj as lane,
)


class TheLaneComesFromThePath(unittest.TestCase):
    def test_a_frontend_path(self):
        for p in ("app/frontend/src/services/api.js", "app/frontend/src/pages/X.jsx",
                  "components/Y.tsx", r"app\frontend\src\services\api.js"):
            with self.subTest(path=p):
                self.assertEqual(lane(p), "frontend")

    def test_a_backend_path(self):
        for p in ("app/backend/custom_routes.py", "app/backend/models.py", "seed_data.py"):
            with self.subTest(path=p):
                self.assertEqual(lane(p), "backend")

    def test_a_capitalised_path_still_resolves(self):
        """The path comes from a registration an LLM wrote, so its case is not guaranteed.
        Mutation OJ8 (drop `.lower()`) read MISSED until this case existed."""
        self.assertEqual(lane("APP/FRONTEND/src/services/api.js"), "frontend")
        self.assertEqual(lane("App/Backend/custom_routes.PY"), "backend")

    def test_a_path_that_says_nothing(self):
        """Narrow on purpose: 9,539 consumer records carry a file_path and only 109 disagree,
        so a wider rule would be guessing on a population that is already right."""
        for p in ("", None, "api.js", "config.yaml", "docker/docker-compose.yml"):
            with self.subTest(path=p):
                self.assertEqual(lane(p), "")


class TheOwnerIsRedirectedOnlyOnAContradiction(unittest.TestCase):
    def test_the_measured_case(self):
        asg, note = owner("backend", ["app/frontend/src/services/api.js"])
        self.assertEqual(asg, "frontend")
        self.assertIn("#1203oj", note)
        self.assertIn("registered by `backend`", note)
        self.assertIn("re-register the consumer", note)

    def test_agreement_changes_nothing(self):
        for ag, files in (("frontend", ["app/frontend/src/services/api.js"]),
                          ("backend", ["app/backend/custom_routes.py"])):
            with self.subTest(agent=ag):
                asg, note = owner(ag, files)
                self.assertEqual(asg, ag)
                self.assertEqual(note, "")

    def test_files_that_say_nothing_change_nothing(self):
        asg, note = owner("backend", ["api.js", "config.yaml"])
        self.assertEqual(asg, "backend")
        self.assertEqual(note, "")

    def test_a_mixed_record_is_not_evidence_about_either_lane(self):
        """A consumer naming files from BOTH lanes says nothing about which must change.

        ★ The registered agent here is NEITHER lane on purpose. With `backend` as the agent,
        dropping the `len(lanes) != 1` guard still passes whenever the set happens to pop
        `backend` first -- a falsifier that depends on hash order is not one (mutation OJ3 read
        MISSED against the earlier version)."""
        asg, note = owner("database", ["app/frontend/src/a.jsx", "app/backend/b.py"])
        self.assertEqual(asg, "database")
        self.assertEqual(note, "")
        asg, note = owner("backend", ["app/frontend/src/a.jsx", "app/backend/b.py"])
        self.assertEqual(asg, "backend")
        self.assertEqual(note, "")

    def test_an_unknown_agent_is_left_alone(self):
        asg, note = owner("", ["app/frontend/src/services/api.js"])
        self.assertEqual(asg, "")
        self.assertEqual(note, "")

    def test_hostile_input_never_raises(self):
        for ag, files in ((None, None), ("backend", "notalist"), (object(), [object()])):
            with self.subTest(agent=repr(ag)[:16]):
                self.assertIsInstance(owner(ag, files), tuple)


class TheTaskActuallyGetsTheRedirectedOwner(unittest.TestCase):
    """End to end through the real hub, not through the helper alone."""

    def _hub(self, tmp):
        from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
        try:
            return RegistryHub(hub_dir=Path(tmp))
        except TypeError:
            return RegistryHub(Path(tmp))

    def test_the_created_task_is_assigned_from_the_file(self):
        created = []

        class _WH:
            def create_task(self, **kw):
                created.append(kw)
                return {"id": "task_x"}

        with tempfile.TemporaryDirectory() as tmp:
            try:
                hub = self._hub(tmp)
            except Exception as exc:
                self.skipTest("RegistryHub needs more setup here: %s" % exc)
            hub._workhub = _WH()
            # The real API, not a poke at `_consumers.value()` -- that returns a COPY, so the
            # first version of this test registered nothing and no task was filed at all.
            # A PENDING registration lands in `_pending_consumers`, which
            # `_record_breaking_change` does not read -- the second version of this test filed
            # nothing for that reason. So: declare the endpoint, then register for real.
            hub.register_endpoint("GET", "/api/titles", {"response_key": "items"},
                                  provider="backend", agent="backend", status="implemented")
            hub.register_consumer("GET /api/titles", "app/frontend/src/services/api.js",
                                  "backend")
            hub._record_breaking_change(
                "GET /api/titles",
                {"is_breaking": True, "type_changed_fields": ["year"]},
                agent="backend")
        self.assertTrue(created, "no task was filed")
        kw = created[0]
        self.assertEqual(kw.get("assignee"), "frontend",
                         "the P0 still goes to the lane the file contradicts")
        self.assertIn("#1203oj", str(kw.get("description")))
        self.assertEqual(kw.get("affected_files"), ["app/frontend/src/services/api.js"],
                         "the files must stay as registered")

    def test_an_agreeing_record_is_untouched_end_to_end(self):
        created = []

        class _WH:
            def create_task(self, **kw):
                created.append(kw)
                return {"id": "task_y"}

        with tempfile.TemporaryDirectory() as tmp:
            try:
                hub = self._hub(tmp)
            except Exception as exc:
                self.skipTest("RegistryHub needs more setup here: %s" % exc)
            hub._workhub = _WH()
            hub.register_endpoint("GET", "/api/titles", {"response_key": "items"},
                                  provider="backend", agent="backend", status="implemented")
            hub.register_consumer("GET /api/titles", "app/frontend/src/services/api.js",
                                  "frontend")
            hub._record_breaking_change(
                "GET /api/titles",
                {"is_breaking": True, "type_changed_fields": ["year"]},
                agent="backend")
        self.assertTrue(created)
        self.assertEqual(created[0].get("assignee"), "frontend")
        self.assertNotIn("#1203oj", str(created[0].get("description")))


class WhatTheCorpusSays(unittest.TestCase):
    _MEASURED = {"netflix-local-r43": 21, "tiktok-web-r181": 29, "tiktok-web-r120": 16,
                 "tiktok-web-r172": 15, "netflix-local-r32": 14}

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_the_contradicting_records_are_still_there(self):
        checked = 0
        for run, n in sorted(self._MEASURED.items()):
            f = self.corpus / run / "shared" / "hubs" / "registryhub_consumers.json"
            if not f.is_file():
                continue
            checked += 1
            try:
                d = json.load(open(f, errors="ignore"))
            except Exception:
                self.fail("%s consumer store is unreadable" % run)
            bad = [c for c in d.values()
                   if isinstance(c, dict) and c.get("agent")
                   and lane(c.get("file_path")) not in ("", str(c.get("agent")))]
            with self.subTest(run=run):
                self.assertEqual(len(bad), n,
                                 "%s was measured at %d contradicting consumer record(s)"
                                 % (run, n))
        if not checked:
            self.skipTest("no measured run on this disk")

    def test_the_redirect_would_have_moved_the_measured_tasks(self):
        """The population this patch is for: tasks whose assignee their own files contradict."""
        moved = 0
        for f in sorted(self.corpus.glob("*/shared/hubs/workhub_tasks.json")):
            try:
                d = json.load(open(f, errors="ignore"))
            except Exception:
                continue
            for t in d.values():
                if not isinstance(t, dict) or "status" not in t:
                    continue
                md = t.get("metadata") or {}
                if not isinstance(md, dict) or md.get("source") != "registryhub_breaking_change":
                    continue
                files = md.get("affected_files") or []
                asg, note = owner(t.get("assignee"), files)
                if note:
                    moved += 1
        self.assertGreater(moved, 200,
                           "only %d breaking-change P0(s) would move; the 273 measured ones "
                           "are gone, so re-measure before trusting this patch" % moved)


if __name__ == "__main__":
    unittest.main()
