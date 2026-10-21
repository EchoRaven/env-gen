r"""#1203op: the task named a consumer file that is not in the tree.

`#1203oj` (landed earlier today) made the FILES decide which lane a breaking-change P0 goes
to. This is the half underneath it: **nothing has ever checked that the registered file
exists.** `_record_breaking_change` copies `c["file_path"]` into "Consumer files: [...]" and
into `affected_files`, so a lane can be sent to a path that is not in the tree.

MEASURED, counting only paths that never existed AT ANY POINT in a run (each run's whole
`git log --all --name-only`):

    app/-shaped consumer registrations            6552
    ...naming a file that never existed             26, in 8 runs   (0.4%)
    breaking-change + auth-relaxed tasks          2757
    ...naming such a path                           62, in 5 runs

netflix-r44 37, tiktok-r191 17, tiktok-r184 4, netflix-r5 2, netflix-r6 2 — ~2.4 tasks per bad
registration, because one record is re-read on every re-declaration (#1203nm's shape, a
three-line source becoming most of a ledger). r184 and r191 are modern.

★ THE CONFOUND THAT MAKES THE OBVIOUS SCAN WRONG. Scanning the FINAL delivered tree answers
138 tasks in 19 runs, and that number is not this behaviour: the biggest group is
`LoginPage.jsx`, named by tasks that asked the lane to DELETE it. It is absent from the final
tree for exactly the right reason, and at the moment the task was filed it existed, so the
runtime check would not have fired. Only "never in the history" is safe to attribute.

★ AND EVERY ONE OF THE 62 IS RECOVERABLE, which is why this annotates instead of refusing:
23 have the same basename one directory away (`app/frontend/src/api.js` registered while only
`app/frontend/src/services/api.js` exists — r191's 17 are all this), and 41 have a near-named
sibling in the directory they name (`pages/GenreCategory.jsx` → `pages/GenreCategoryPage.jsx`).
NOT ONE was unrecoverable. #1203np's rule: an unactionable instruction is fixed by naming what
IS there, not by deleting the instruction.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _repo_app_files_1203op as tree_of,
    unregistered_consumer_files_1203op as notes,
)

_CORPUS = Path(__file__).resolve().parents[2] / "generated"


def _mk(root: Path, *rel: str) -> None:
    for r in rel:
        p = root / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")


class TheNoteNamesWhatIsThere(unittest.TestCase):

    def test_a_path_that_exists_gets_no_note(self):
        """★ Non-vacuity in the direction that matters: the normal case must stay silent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/services/api.js")
            self.assertEqual(notes(root, ["app/frontend/src/services/api.js"]), {})

    def test_the_same_basename_one_directory_away(self):
        """r191's 17 tasks: `src/api.js` registered, only `src/services/api.js` exists."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/services/api.js")
            out = notes(root, ["app/frontend/src/api.js"])
            self.assertEqual(list(out), ["app/frontend/src/api.js"])
            self.assertIn("app/frontend/src/services/api.js", out["app/frontend/src/api.js"])

    def test_a_near_named_sibling_in_the_directory_it_names(self):
        """netflix-r44's 37: `pages/GenreCategory.jsx` → `pages/GenreCategoryPage.jsx`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/pages/GenreCategoryPage.jsx",
                "app/frontend/src/pages/Unrelated.jsx")
            out = notes(root, ["app/frontend/src/pages/GenreCategory.jsx"])
            n = out["app/frontend/src/pages/GenreCategory.jsx"]
            self.assertIn("GenreCategoryPage.jsx", n)
            self.assertNotIn("Unrelated.jsx", n,
                             "a sibling with an unrelated name is not a lead: %r" % n)

    def test_nothing_like_it_still_says_what_the_directory_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/pages/Home.jsx")
            n = notes(root, ["app/frontend/src/pages/Zebra.jsx"])["app/frontend/src/pages/Zebra.jsx"]
            self.assertIn("nothing is named like it", n)
            self.assertIn("Home.jsx", n)

    def test_a_directory_that_does_not_exist_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/pages/Home.jsx")
            n = notes(root, ["app/frontend/src/nope/Zebra.jsx"])["app/frontend/src/nope/Zebra.jsx"]
            self.assertIn("there is no app/frontend/src/nope/ either", n)

    def test_a_long_directory_listing_declares_its_cut(self):
        """#1034: a capped list has to say it was cut."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, *["app/frontend/src/pages/P%02d.jsx" % i for i in range(20)])
            n = notes(root, ["app/frontend/src/pages/Zebra.jsx"])["app/frontend/src/pages/Zebra.jsx"]
            self.assertIn("more", n, "20 siblings listed with no declared cut: %r" % n)


class AFileInAWorktreeIsARealFile(unittest.TestCase):
    """#566j: a false blocker costs runs, and this one would live inside a P0's text."""

    def test_a_path_only_in_a_lane_worktree_is_not_reported_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/index.jsx",
                "worktrees/frontend/app/frontend/src/services/api.js")
            self.assertEqual(notes(root, ["app/frontend/src/services/api.js"]), {},
                             "the lane's own uncommitted file was called missing")

    def test_the_worktree_copy_is_offered_under_its_repo_relative_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "worktrees/frontend/app/frontend/src/services/api.js")
            n = notes(root, ["app/frontend/src/api.js"])["app/frontend/src/api.js"]
            self.assertIn("app/frontend/src/services/api.js", n)
            self.assertNotIn("worktrees/", n,
                             "the lane edits a repo-relative path, not a worktree path: %r" % n)


class TheWalkIsPaidForOnlyWhenSomethingIsWrong(unittest.TestCase):

    def test_nothing_missing_means_no_tree_walk(self):
        """★ The cost guard: 99.6% of registrations are fine, and the check must be free for
        them. Asserted by making the walk raise if it is entered."""
        import env_generator.llm_generator.multi_agent.runtime.registryhub as R
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/services/api.js")
            orig = R._repo_app_files_1203op
            calls = []
            R._repo_app_files_1203op = lambda *a, **k: calls.append(1) or set()
            try:
                self.assertEqual(notes(root, ["app/frontend/src/services/api.js"]), {})
            finally:
                R._repo_app_files_1203op = orig
            self.assertEqual(calls, [], "the tree was walked for a file that exists")

    def test_node_modules_is_not_a_source_of_leads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/node_modules/whatever/api.js",
                "app/frontend/src/index.jsx")
            out = notes(root, ["app/frontend/src/api.js"])
            self.assertIn("app/frontend/src/api.js", out)
            self.assertNotIn("node_modules", out["app/frontend/src/api.js"])
            self.assertNotIn("node_modules", " ".join(sorted(tree_of(root))))

    def test_an_unreadable_root_returns_nothing_rather_than_a_verdict(self):
        """#883: "could not look" is not "it is not there"."""
        self.assertEqual(notes(Path("/nonexistent-1203op"), ["app/frontend/src/api.js"]), {})
        self.assertEqual(notes(None, ["app/frontend/src/api.js"]), {})

    def test_hostile_input_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in (None, 5, [None], ["", "   "], [{"a": 1}], "not-a-list"):
                with self.subTest(files=f):
                    self.assertIsInstance(notes(Path(tmp), f), dict)


class TheNoteReachesTheTask(unittest.TestCase):
    """#1203f6 / #947: a finding that stops at a helper has not reached anybody."""

    def _hub(self, root: Path):
        from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
        hub_dir = root / "shared" / "hubs"
        hub_dir.mkdir(parents=True, exist_ok=True)
        try:
            return RegistryHub(hub_dir=hub_dir)
        except TypeError:
            return RegistryHub(hub_dir)

    def _file(self, root, registered, *present):
        created = []

        class _WH:
            def create_task(self, **kw):
                created.append(kw)
                return {"id": "t"}

        _mk(root, *present)
        hub = self._hub(root)
        hub._workhub = _WH()
        hub.register_endpoint("GET", "/api/titles", {"response_key": "items"},
                              provider="backend", agent="backend", status="implemented")
        hub.register_consumer("GET /api/titles", registered, "frontend")
        hub._record_breaking_change("GET /api/titles",
                                    {"is_breaking": True, "type_changed_fields": ["year"]},
                                    agent="backend")
        return created

    def test_the_p0_says_which_file_is_missing_and_what_is_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = self._file(Path(tmp), "app/frontend/src/api.js",
                                 "app/frontend/src/services/api.js")
        self.assertTrue(created, "no task was filed")
        d = str(created[0].get("description"))
        self.assertIn("#1203op", d)
        self.assertIn("app/frontend/src/services/api.js", d)
        self.assertEqual(created[0].get("affected_files"), ["app/frontend/src/api.js"],
                         "the registration must stay as it is (#1203nq: annotate, not discard)")

    def test_a_present_file_adds_nothing_to_the_p0(self):
        with tempfile.TemporaryDirectory() as tmp:
            created = self._file(Path(tmp), "app/frontend/src/services/api.js",
                                 "app/frontend/src/services/api.js")
        self.assertTrue(created)
        self.assertNotIn("#1203op", str(created[0].get("description")))

    def test_it_composes_with_1203oj_on_the_same_task(self):
        """★ Both patches landed today in the SAME function and read the SAME strings, so
        green separately is not green together. A ghost FRONTEND path registered by `backend`
        must redirect the owner (#1203oj) AND carry the missing-file note (#1203op)."""
        created = []

        class _WH:
            def create_task(self, **kw):
                created.append(kw)
                return {"id": "t"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, "app/frontend/src/services/api.js")
            hub = self._hub(root)
            hub._workhub = _WH()
            hub.register_endpoint("GET", "/api/titles", {"response_key": "items"},
                                  provider="backend", agent="backend", status="implemented")
            hub.register_consumer("GET /api/titles", "app/frontend/src/api.js", "backend")
            hub._record_breaking_change("GET /api/titles",
                                        {"is_breaking": True, "type_changed_fields": ["year"]},
                                        agent="backend")
        self.assertTrue(created)
        kw = created[0]
        self.assertEqual(kw.get("assignee"), "frontend")
        d = str(kw.get("description"))
        self.assertIn("#1203oj", d)
        self.assertIn("#1203op", d)
        self.assertIn("app/frontend/src/services/api.js", d)


class TheAuthRelaxedTaskCarriesItToo(unittest.TestCase):
    """#1032 -- one owner for the rule, and BOTH callers of it.

    ★ Mutation OP9 found this class missing: removing the note from `_notify_auth_relaxed_1202qq`
    changed nothing any test could see, so that call site was wired and unverified. 3 of this
    builder's 21 corpus tasks name a path that never existed (all in r184)."""

    def _run(self, registered, *present):
        from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
        created = []

        class _WH:
            def create_task(self, **kw):
                created.append(kw)
                return {"id": "t"}

            def list_tasks(self):
                # what #1202qq keys on: an auth_added P0 this lane was actually told about
                return [{"title": "Fix breaking change in GET /api/titles (auth added)",
                         "description": "{'auth_added': True}",
                         "assignee": "frontend"}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _mk(root, *present)
            hub_dir = root / "shared" / "hubs"
            hub_dir.mkdir(parents=True, exist_ok=True)
            try:
                hub = RegistryHub(hub_dir=hub_dir)
            except TypeError:
                hub = RegistryHub(hub_dir)
            hub._workhub = _WH()
            hub.register_endpoint("GET", "/api/titles", {"response_key": "items"},
                                  provider="backend", agent="backend", status="implemented")
            hub.register_consumer("GET /api/titles", registered, "frontend")
            sent = hub._notify_auth_relaxed_1202qq("GET /api/titles", agent="backend")
        return sent, created

    def test_the_undo_task_says_which_file_is_not_there(self):
        sent, created = self._run("app/frontend/src/api.js",
                                  "app/frontend/src/services/api.js")
        self.assertTrue(sent, "the auth-relaxed notice did not go out at all")
        self.assertTrue(created, "no undo task was filed")
        d = str(created[0].get("description"))
        self.assertIn("#1203op", d)
        self.assertIn("app/frontend/src/services/api.js", d)

    def test_a_present_file_adds_nothing_to_the_undo_task(self):
        sent, created = self._run("app/frontend/src/services/api.js",
                                  "app/frontend/src/services/api.js")
        self.assertTrue(sent)
        self.assertTrue(created)
        self.assertNotIn("#1203op", str(created[0].get("description")))


class WhatTheCorpusSays(unittest.TestCase):
    _PATH = re.compile(r"\b(app/(?:backend|frontend)/[A-Za-z0-9_./\-]+\.[A-Za-z]{2,4})\b")
    _TASK_RUNS = {"netflix-local-r44": 37, "tiktok-web-r191": 17, "tiktok-web-r184": 4,
                  "netflix-local-r5": 2, "netflix-local-r6": 2}

    def setUp(self):
        if not _CORPUS.is_dir():
            self.skipTest("no corpus on this disk")

    def _ever(self, root: Path):
        try:
            out = subprocess.run(["git", "-C", str(root), "log", "--all", "--name-only",
                                  "--format="], capture_output=True, text=True, timeout=240)
        except Exception:
            return None
        if out.returncode != 0:
            return None
        return {l.strip() for l in out.stdout.splitlines() if l.strip()}

    def test_the_measured_tasks_are_still_there_and_still_name_a_ghost(self):
        found = collections.Counter()
        checked = 0
        for run in sorted(self._TASK_RUNS):
            root = _CORPUS / run
            f = root / "shared" / "hubs" / "workhub_tasks.json"
            if not f.is_file() or not (root / ".git").is_dir():
                continue
            ever = self._ever(root)
            if not ever:
                continue
            checked += 1
            for k, t in json.loads(f.read_text(encoding="utf-8")).items():
                if k == "_meta" or not isinstance(t, dict):
                    continue
                ti = str(t.get("title") or "")
                if not (ti.startswith("Fix breaking change in")
                        or "is public again - undo the auth workaround" in ti):
                    continue
                ps = set(self._PATH.findall(" ".join(
                    str(t.get(x) or "") for x in ("title", "description"))))
                ps |= {str(x) for x in (t.get("affected_files") or []) if isinstance(x, str)}
                if [p for p in ps if p.startswith("app/") and p not in ever]:
                    found[run] += 1
        # ★ ON4's lesson: a ratchet that looked at nothing SKIPS, and a skip passes.
        self.assertEqual(checked, len(self._TASK_RUNS),
                         "only %d of the %d measured runs could be read -- a verdict from "
                         "that would be about nothing" % (checked, len(self._TASK_RUNS)))
        self.assertEqual(dict(found), self._TASK_RUNS)

    def test_every_one_of_them_is_recoverable(self):
        """The claim the whole disposition rests on: annotating is worth doing because the
        answer is always one suffix or one directory away. 23 same-name, 41 near-name, 0 lost."""
        kinds = collections.Counter()
        for run in sorted(self._TASK_RUNS):
            root = _CORPUS / run
            f = root / "shared" / "hubs" / "workhub_tasks.json"
            if not f.is_file():
                continue
            ever = self._ever(root)
            if not ever:
                continue
            for k, t in json.loads(f.read_text(encoding="utf-8")).items():
                if k == "_meta" or not isinstance(t, dict):
                    continue
                ti = str(t.get("title") or "")
                if not (ti.startswith("Fix breaking change in")
                        or "is public again - undo the auth workaround" in ti):
                    continue
                ps = set(self._PATH.findall(" ".join(
                    str(t.get(x) or "") for x in ("title", "description"))))
                ps |= {str(x) for x in (t.get("affected_files") or []) if isinstance(x, str)}
                ghost = sorted(p for p in ps if p.startswith("app/") and p not in ever)
                for p, n in (notes(root, ghost) or {}).items():
                    kinds["same name elsewhere" if "the file with that name is" in n
                          else ("near name in the directory"
                                if "nothing is named like it" not in n else "lost")] += 1
        self.assertEqual(kinds.get("lost", 0), 0,
                         "a ghost path with nothing to point at: %r" % dict(kinds))
        self.assertEqual((kinds["same name elsewhere"], kinds["near name in the directory"]),
                         (23, 41))

    def test_the_source_is_a_handful_of_registrations(self):
        """26 bad registrations in 8 runs out of 6552 -- the amplification, not the source,
        is what shows up in the ledger (#1203nm)."""
        tot, bad, runs = 0, 0, set()
        for f in sorted(glob.glob(str(_CORPUS / "*" / "shared" / "hubs"
                                      / "registryhub_consumers.json"))):
            root = Path(f).parents[2]
            if not (root / ".git").is_dir():
                continue
            ever = self._ever(root)
            if not ever:
                continue
            try:
                d = json.loads(Path(f).read_text(encoding="utf-8"))
            except Exception:
                continue
            for k, c in d.items():
                if k == "_meta" or not isinstance(c, dict):
                    continue
                fp = str(c.get("file_path") or "").replace("\\", "/")
                if not fp.startswith("app/"):
                    continue
                tot += 1
                if fp not in ever:
                    bad += 1
                    runs.add(root.name)
        # #1203r8 (2026-10-21): `tot` is the DENOMINATOR and already has its floor on the
        # line above; pinning it exactly as well meant one new run in the corpus broke this --
        # 6552 -> 6641 registrations while `bad` and `runs` returned 26 and 8, unchanged. The
        # bad registrations are the claim; the number of registrations read is just how big
        # the corpus is that day.
        self.assertGreater(tot, 6000, "only %d registrations read" % tot)
        self.assertEqual((bad, len(runs)), (26, 8))


if __name__ == "__main__":
    unittest.main()
