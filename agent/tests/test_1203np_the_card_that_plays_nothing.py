r"""#1203np: the media finding reached a log line and an artifact, and no actor at all.

`#1202xn` has detected seeded media the app cannot serve since r124. Its finding goes to
`logging.getLogger(__name__).warning(...)` and `logs/unstaged_seed_media_1202xn.jsonl` — and
nowhere else. `RemediationDispatcher` has entries for routes, pages, filters and list totals,
and had NONE for media. That is #1041's shape, the one #1148's docstring names ("the evidence
exists, the party who can act on it is never told") and the one #1203ii closed for `#1202w0`.

THE EVIDENCE IS IN, which is the bar `record_unstaged_seed_media_1202xn` set for itself ("the
next runs' files are the evidence for whether it earns a gate check"): 456 ledger rows across
15 runs, and in the DELIVERED trees still on disk, 135 unstaged references across 21 runs —
r144 12, r169 12, r183 12, r181 9, r187 9, r186 8, r191 6. Those are shipped apps whose cards
render a thumbnail and play nothing.

AND THE INSTRUCTION HAD TO BE POSSIBLE. A run is offline, so "stage the missing video" is not
an available action, and `#1202xn` deliberately refuses to synthesise a placeholder ("a grey
stand-in would be worse than a stated gap"). What is available is REPOINTING, and the
framework already knows the targets because it staged them: 98 of the 135 (73%) sit in a
directory that holds staged files, 18 sharing the creator stem, and three runs are wholly in
that class (r191 6 of 6, r172 4 of 4, r140 3 of 3). r190's seed asks for
`khaby.lame__7663376464665906452.mp4` while four other khaby.lame videos sit beside it among
76 files totalling 392 MB.

OWNER BY CAUSE, which is `#1202xn`'s own rule — it labels every row "(not staged)" or
"(excluded from the image by .dockerignore)" because "different owners, and a reader who
cannot tell them apart looks in the wrong place". MEASURED: 133 of the 135 are "not staged"
(backend: a seed row names a file nobody staged) and 2 are exclusions (frontend: the file is
on disk and a `.dockerignore` line keeps it out of the image), and NO run carries both.
"""
import ast
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent import orchestrator as ORCH
from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as RD
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    staged_alternatives_1203np as alts,
)


def _tree(root: Path, staged, seed_refs, dockerignore=None):
    pub = root / "app" / "frontend" / "public" / "assets" / "real_videos"
    pub.mkdir(parents=True)
    for name in staged:
        (pub / name).write_bytes(b"x")
    be = root / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_dataset.json").write_text(
        json.dumps({"videos": [{"video_url": "/assets/real_videos/" + r}
                               for r in seed_refs]}), encoding="utf-8")
    if dockerignore is not None:
        (root / "app" / "frontend" / ".dockerignore").write_text(
            dockerignore, encoding="utf-8")
    return root


class TheAlternativesAreWhatTheFrameworkStaged(unittest.TestCase):
    def test_a_same_creator_file_comes_first(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["zed__111111111.mp4", "khaby.lame__222222222.mp4"], [])
            got = alts(root, ["/assets/real_videos/khaby.lame__999999999.mp4 (not staged)"])
            tot, ex = got["/assets/real_videos/khaby.lame__999999999.mp4"]
            self.assertEqual(tot, 2)
            self.assertEqual(ex[0], "khaby.lame__222222222.mp4")

    def test_the_rest_of_the_directory_is_still_offered(self):
        """A hand-invented name matches no stem -- netflix's `arcane-trailer.mp4` against a
        directory of `clip_*.mp4`. It must still get an answer."""
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_1.mp4", "clip_2.mp4"], [])
            tot, ex = alts(root, ["/assets/real_videos/arcane-trailer.mp4"])[
                "/assets/real_videos/arcane-trailer.mp4"]
            self.assertEqual(tot, 2)
            self.assertEqual(sorted(ex), ["clip_1.mp4", "clip_2.mp4"])

    def test_the_cap_limits_examples_and_never_the_total(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_%d.mp4" % i for i in range(9)], [])
            tot, ex = alts(root, ["/assets/real_videos/x.mp4"], cap=2)[
                "/assets/real_videos/x.mp4"]
            self.assertEqual(tot, 9)
            self.assertEqual(len(ex), 2)

    def test_the_detectors_cause_suffix_is_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_1.mp4"], [])
            for suffix in (" (not staged)",
                           " (excluded from the image by .dockerignore)"):
                with self.subTest(suffix=suffix):
                    got = alts(root, ["/assets/real_videos/x.mp4" + suffix])
                    self.assertIn("/assets/real_videos/x.mp4", got)

    def test_the_missing_file_is_not_offered_as_its_own_alternative(self):
        """If it were on disk it would not be in the finding; defended anyway, because a
        self-referential suggestion reads as 'repoint it at itself'."""
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["x.mp4", "clip_1.mp4"], [])
            tot, ex = alts(root, ["/assets/real_videos/x.mp4"])[
                "/assets/real_videos/x.mp4"]
            self.assertEqual(tot, 2)
            self.assertNotIn("x.mp4", ex)

    def test_an_empty_directory_yields_no_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), [], [])
            self.assertEqual(alts(root, ["/assets/real_videos/x.mp4"]), {})

    def test_no_public_tree_and_bad_input_return_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(alts(Path(d), ["/assets/a.mp4"]), {})
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_1.mp4"], [])
            self.assertEqual(alts(root, []), {})
            self.assertEqual(alts(root, None), {})
            self.assertEqual(alts(root, ["", "   "]), {})


class _Hub:
    def __init__(self):
        self.tasks = []

    def create_task(self, **kw):
        self.tasks.append(kw)


class _Hubs:
    def __init__(self):
        self.workhub = _Hub()


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, *a):
        self.lines.append(a)

    def error(self, *a):
        self.lines.append(a)


class _Orch:
    def __init__(self, out):
        self.output_dir = str(out)
        self.hubs = _Hubs()
        self._logger = _Log()
        self._current_milestone_version = "1.0.0"


def _run(orch):
    import asyncio
    asyncio.new_event_loop().run_until_complete(
        RD.RemediationDispatcher(orch).dispatch_unstaged_seed_media_1203np())
    return orch.hubs.workhub.tasks


class TheFindingNowReachesSomeone(unittest.TestCase):
    def _absent_tree(self, d):
        return _tree(Path(d), ["khaby.lame__222.mp4", "clip_1.mp4"],
                     ["khaby.lame__999.mp4"])

    def test_a_task_is_filed_and_names_the_reference(self):
        with tempfile.TemporaryDirectory() as d:
            tasks = _run(_Orch(self._absent_tree(d)))
            self.assertEqual(len(tasks), 1)
            self.assertIn("khaby.lame__999.mp4", tasks[0]["description"])

    def test_it_carries_the_alternative_the_framework_staged(self):
        with tempfile.TemporaryDirectory() as d:
            desc = _run(_Orch(self._absent_tree(d)))[0]["description"]
            self.assertIn("khaby.lame__222.mp4", desc)
            self.assertIn("already holds", desc)

    def test_it_is_a_P1_for_the_backend_when_the_file_was_never_staged(self):
        with tempfile.TemporaryDirectory() as d:
            t = _run(_Orch(self._absent_tree(d)))[0]
            self.assertEqual(t["priority"], "P1")
            self.assertEqual(t["assignee"], "backend")

    def test_a_dockerignore_exclusion_goes_to_the_frontend(self):
        """`#1202xn`'s own rule: the two causes have different owners."""
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_1.mp4", "staged.mp4"], ["staged.mp4"],
                         dockerignore="public/assets/real_videos/*.mp4\n")
            tasks = _run(_Orch(root))
            self.assertEqual(len(tasks), 1)
            self.assertIn("dockerignore", tasks[0]["description"])
            self.assertEqual(tasks[0]["assignee"], "frontend")

    def test_both_causes_route_to_the_backend_and_say_so(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_1.mp4", "staged.mp4"],
                         ["staged.mp4", "never__777.mp4"],
                         dockerignore="public/assets/real_videos/staged.mp4\n")
            tasks = _run(_Orch(root))
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["assignee"], "backend")
            self.assertIn("carries BOTH kinds", tasks[0]["description"])

    def test_one_cause_does_not_mention_the_other_owners_handoff(self):
        """Non-vacuity for the sentence above: it must be conditional, not always printed."""
        with tempfile.TemporaryDirectory() as d:
            desc = _run(_Orch(self._absent_tree(d)))[0]["description"]
            self.assertNotIn("carries BOTH kinds", desc)

    def test_a_clean_tree_files_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["staged.mp4"], ["staged.mp4"])
            self.assertEqual(_run(_Orch(root)), [])

    def test_it_does_not_refile_within_a_milestone(self):
        with tempfile.TemporaryDirectory() as d:
            orch = _Orch(self._absent_tree(d))
            _run(orch)
            _run(orch)
            _run(orch)
            self.assertEqual(len(orch.hubs.workhub.tasks), 1)

    def test_a_new_milestone_files_again(self):
        with tempfile.TemporaryDirectory() as d:
            orch = _Orch(self._absent_tree(d))
            _run(orch)
            orch._current_milestone_version = "1.1.0"
            _run(orch)
            self.assertEqual(len(orch.hubs.workhub.tasks), 2)

    def test_a_missing_output_dir_is_survived(self):
        orch = _Orch("")
        orch.output_dir = None
        self.assertEqual(_run(orch), [])


class TheInstructionIsOneTheLaneCanCarryOut(unittest.TestCase):
    def _desc(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["khaby.lame__222.mp4"], ["khaby.lame__999.mp4"])
            return _run(_Orch(root))[0]["description"]

    def test_it_says_the_run_is_offline(self):
        self.assertIn("OFFLINE", self._desc())

    def test_it_offers_repoint_and_drop(self):
        d = self._desc()
        self.assertIn("REPOINT", d)
        self.assertIn("DROP the row", d)

    def test_it_refuses_a_grey_placeholder(self):
        """#1202xn's stated trade, carried into the instruction rather than left in a
        docstring the lane never reads."""
        self.assertIn("Do NOT substitute a grey placeholder", self._desc())

    def test_the_row_list_declares_its_own_cut(self):
        with tempfile.TemporaryDirectory() as d:
            refs = ["never__%d.mp4" % i for i in range(14)]
            root = _tree(Path(d), ["clip_1.mp4"], refs)
            desc = _run(_Orch(root))[0]["description"]
            self.assertIn("more not shown", desc)

    def test_the_rows_are_one_per_line(self):
        with tempfile.TemporaryDirectory() as d:
            root = _tree(Path(d), ["clip_1.mp4"],
                         ["never__1.mp4", "never__2.mp4", "never__3.mp4"])
            desc = _run(_Orch(root))[0]["description"]
            self.assertGreaterEqual(len([l for l in desc.splitlines()
                                         if l.startswith("- /assets/")]), 3)

    def test_a_reference_with_nothing_to_repoint_to_says_that(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "app" / "frontend" / "public").mkdir(parents=True)
            be = root / "app" / "backend"
            be.mkdir(parents=True)
            (be / "seed_dataset.json").write_text(
                json.dumps({"v": [{"u": "/assets/real_videos/never__1.mp4"}]}),
                encoding="utf-8")
            tasks = _run(_Orch(root))
            self.assertEqual(len(tasks), 1)
            self.assertIn("nothing staged in that directory", tasks[0]["description"])


class TheCallSiteIsNotBehindTheGate(unittest.TestCase):
    """★ The mistake this call site's own comment records #1203ii inheriting: "I copied the
    call site together with its gate". The runs that ship unstaged media are precisely the
    ones whose delivery gate goes green, so a dispatch nested inside
    `if gate.get("failed_checks")` would never fire for them."""

    def _call_nodes(self):
        tree = ast.parse(inspect.getsource(ORCH))
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in (
                    "dispatch_unstaged_seed_media_1203np",
                    "dispatch_list_totals_unreachable_1203ii"):
                out.append(fn.attr)
        return out

    def test_the_orchestrator_calls_it(self):
        self.assertIn("dispatch_unstaged_seed_media_1203np", self._call_nodes())

    def test_it_is_not_nested_inside_a_failed_checks_branch(self):
        tree = ast.parse(inspect.getsource(ORCH))
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = ast.dump(node.test)
            if "failed_checks" not in test:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
            self.assertNotIn("dispatch_unstaged_seed_media_1203np", body,
                             "the media dispatch sits behind a failed-checks branch, so it "
                             "cannot fire for the green-gate runs that carry the finding")

    def test_it_sits_beside_its_precedent(self):
        """Both neighbours are hoisted to the same place for the same reason."""
        names = self._call_nodes()
        self.assertIn("dispatch_list_totals_unreachable_1203ii", names)

    def test_its_failure_cannot_swallow_the_other_dispatch(self):
        """#1201 -- each dispatch gets its own try, which the call site comment requires.

        Read through the AST. The first version of this test sliced `src[i:i + 400]` and the
        #943 ratchet failed the suite for it, correctly: a window measured in characters
        passes or fails on formatting. The semantic boundary here is the enclosing `Try`.
        """
        tree = ast.parse(inspect.getsource(ORCH))
        holders = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Try)
                   and "dispatch_unstaged_seed_media_1203np" in ast.dump(
                       ast.Module(body=n.body, type_ignores=[]))]
        self.assertTrue(holders, "the media dispatch is not wrapped in a try at all")
        # the INNERMOST one -- an enclosing try encloses all three dispatches, so the
        # smallest span is the one that belongs to this dispatch
        node = min(holders, key=lambda n: (n.end_lineno or 0) - n.lineno)
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        self.assertNotIn("dispatch_list_totals_unreachable_1203ii", body,
                         "the two dispatches share a try, so one failing swallows the other")
        handlers = ast.dump(ast.Module(body=list(node.handlers), type_ignores=[]))
        self.assertIn("#1203np dispatch failed", handlers,
                      "the handler does not say which dispatch failed")


if __name__ == "__main__":
    unittest.main()
