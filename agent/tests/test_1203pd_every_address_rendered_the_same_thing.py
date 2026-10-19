"""#1203pd: every address under the route rendered the same thing, and nobody was told.

`route_params_ignored_1202uw` finds routes whose path carries a `:param` that the component
subtree never reads. The consequence is not an error -- EVERY address under the route renders
the same thing -- so no gate sees it. The finding reached a `logger.warning` and
`logs/route_params_ignored_1202uw.jsonl` and nothing else: the dispatcher list had entries for
unimplemented routes, route consolidation, frontend navigability, unwired pages, unbuilt pages,
list totals, seeded media, fabricated arrays and never-matching filters, and NONE for this.

EVIDENCE: 299 ledger rows over 25 runs -- deduplicated 1 to 4 routes per run, because the
detector re-runs on every scaffold pass. The newest two runs carry the identical pair
`/:username -> ProfileOwnPage` and `/@:username -> ProfileOwnPage` (r189, r191), and #1202uw's
own warning records what r135 shipped: a ProfileView that takes the logged-in user from props
and never reads the name, so every profile URL showed an empty own-profile shell.
"""

import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as RD
from env_generator.llm_generator.multi_agent import orchestrator as ORCH


def _app(root: Path, routes_src: str, pages: dict):
    """A frontend tree whose App.jsx declares routes and whose pages may ignore the param."""
    fe = root / "app" / "frontend" / "src"
    (fe / "pages").mkdir(parents=True, exist_ok=True)
    (fe / "App.jsx").write_text(routes_src, encoding="utf-8")
    for name, body in pages.items():
        (fe / "pages" / name).write_text(body, encoding="utf-8")
    return str(root)


_IGNORES = """
import { Routes, Route } from 'react-router-dom'
import ProfileOwnPage from './pages/ProfileOwnPage.jsx'
export default function App() {
  return (<Routes><Route path="/@:username" element={<ProfileOwnPage/>}/></Routes>)
}
"""
_PAGE_IGNORING = "export default function ProfileOwnPage(){ return <div>me</div> }"
_PAGE_READING = ("import { useParams } from 'react-router-dom'\n"
                 "export default function ProfileOwnPage(){ const {username}=useParams();"
                 " return <div>{username}</div> }")


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
        RD.RemediationDispatcher(orch).dispatch_route_params_ignored_1203pd())
    return orch.hubs.workhub.tasks


class TheFindingNowReachesSomeone(unittest.TestCase):

    def test_a_task_is_filed_and_names_the_route(self):
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_IGNORING})
            tasks = _run(_Orch(out))
            self.assertEqual(len(tasks), 1)
            self.assertIn("username", tasks[0]["description"])

    def test_a_page_that_READS_its_param_files_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_READING})
            self.assertEqual(_run(_Orch(out)), [])

    def test_it_is_a_P1_for_the_frontend(self):
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_IGNORING})
            t = _run(_Orch(out))[0]
            self.assertEqual(t["assignee"], "frontend")
            self.assertEqual(t["priority"], "P1")

    def test_the_task_names_BOTH_acceptable_fixes(self):
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_IGNORING})
            desc = _run(_Orch(out))[0]["description"]
            self.assertIn("useParams", desc)
            self.assertIn("REMOVE THE PARAMETER", desc)

    def test_the_task_forbids_the_fake_fix_and_states_the_test(self):
        """The lane can make the page LOOK right by hardcoding one entity or by echoing the
        parameter into a heading. The task has to say what would actually count."""
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_IGNORING})
            desc = _run(_Orch(out))[0]["description"]
            self.assertIn("hardcode", desc.lower())
            self.assertIn("two different", desc)

    def test_the_second_call_in_the_same_milestone_files_nothing(self):
        """#1041: it runs every tick, so without the guard it would storm."""
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_IGNORING})
            orch = _Orch(out)
            _run(orch)
            _run(orch)
            self.assertEqual(len(orch.hubs.workhub.tasks), 1)

    def test_a_new_milestone_lets_it_fire_again(self):
        with tempfile.TemporaryDirectory() as d:
            out = _app(Path(d), _IGNORES, {"ProfileOwnPage.jsx": _PAGE_IGNORING})
            orch = _Orch(out)
            _run(orch)
            orch._current_milestone_version = "2.0.0"
            _run(orch)
            self.assertEqual(len(orch.hubs.workhub.tasks), 2)

    def test_an_empty_tree_files_nothing_and_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_run(_Orch(d)), [])

    def test_no_output_dir_is_a_quiet_return(self):
        orch = _Orch("")
        orch.output_dir = None
        self.assertEqual(_run(orch), [])

    def test_a_detector_that_raises_cannot_break_the_tick(self):
        saved = RD.__dict__.get("_rpi_probe")
        import env_generator.llm_generator.multi_agent.runtime.scaffolder as SC
        orig = SC.route_params_ignored_1202uw
        try:
            SC.route_params_ignored_1202uw = lambda *_a, **_k: (_ for _ in ()).throw(
                RuntimeError("no"))
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(_run(_Orch(d)), [])      # must not raise
        finally:
            SC.route_params_ignored_1202uw = orig
            if saved is not None:
                RD.__dict__["_rpi_probe"] = saved


class ItIsWiredTheWayItsNeighboursAre(unittest.TestCase):

    @staticmethod
    def _src(mod):
        with open(inspect.getfile(mod), encoding="utf-8", errors="ignore") as fh:
            return fh.read()

    def test_the_orchestrator_calls_it(self):
        self.assertIn("dispatch_route_params_ignored_1203pd", self._src(ORCH),
                      "#1203f6: a dispatcher nothing calls is the defect it exists to close")

    def test_it_is_called_OUTSIDE_the_gate_branch_like_its_neighbours(self):
        """#1203ii's bug: the call site was copied together with its gate, and the runs that
        carry this defect are exactly the ones whose gate goes green."""
        src = self._src(ORCH)
        mine = src.index("dispatch_route_params_ignored_1203pd")
        sibling = src.index("dispatch_unstaged_seed_media_1203np")
        self.assertLess(abs(mine - sibling), 2000,
                        "it drifted away from the neighbours it must sit beside")

    def test_it_has_its_own_try_so_one_failure_cannot_swallow_another(self):
        """#943: read the try/except that WRAPS the call, not 400 bytes after it.

        A byte window here breaks the moment the comment above the call grows, and the
        comment above this call is one I wrote and will edit.
        """
        tree = ast.parse(self._src(ORCH))
        wrapped = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            if "dispatch_route_params_ignored_1203pd" not in body:
                continue
            handlers = " ".join(ast.unparse(h) for h in node.handlers)
            wrapped.append(handlers)
        self.assertTrue(wrapped, "the call is not inside a try of its own")
        self.assertTrue(any("1203pd dispatch failed" in h for h in wrapped),
                        "its handler must name the dispatch that failed (#1201)")

    def test_it_rereads_its_own_detector_and_not_a_gate_key(self):
        body = inspect.getsource(RD.RemediationDispatcher.dispatch_route_params_ignored_1203pd)
        self.assertIn("route_params_ignored_1202uw", body)
        tree = ast.parse(body.lstrip())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertNotIn("gate", names, "reading a gate key inherits the caller's branch")

    def test_it_declares_its_cut(self):
        body = inspect.getsource(RD.RemediationDispatcher.dispatch_route_params_ignored_1203pd)
        self.assertIn("join_capped", body, "#1034: a capped list must declare its cut")

    def test_a_failure_announces_itself(self):
        """Driven, not read. A mutation inserted `return` in front of the `warn_once_1201`
        call: the string stayed in the source as dead code, so `"warn_once_1201" in body`
        passed while nothing announced anything. The only honest check is to break the
        detector and watch for the announcement."""
        import env_generator.llm_generator.multi_agent.runtime.scaffolder as SC
        import env_generator.llm_generator.multi_agent.runtime.message_format as MF
        said = []
        orig_det, orig_warn = SC.route_params_ignored_1202uw, MF.warn_once_1201
        try:
            SC.route_params_ignored_1202uw = lambda *_a, **_k: (_ for _ in ()).throw(
                RuntimeError("no"))
            MF.warn_once_1201 = lambda *a, **k: said.append(a)
            with tempfile.TemporaryDirectory() as d:
                _run(_Orch(d))
        finally:
            SC.route_params_ignored_1202uw = orig_det
            MF.warn_once_1201 = orig_warn
        self.assertTrue(said, "#1201: a guard that fails must not fail silently")
        self.assertIn("1203pd", " ".join(str(x) for x in said[0]))


if __name__ == "__main__":
    unittest.main()
