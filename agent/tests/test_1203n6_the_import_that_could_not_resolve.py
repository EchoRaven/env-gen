r"""#1203n6: the import that could not resolve under the root the framework actually runs on.

THIS TREE IS IMPORTED UNDER TWO ROOTS. `orchestrator.py` and `_paths.setup_paths()` put
`LLM_GENERATOR_DIR` on `sys.path` on purpose -- `_paths`' own docstring says "memory, tools,
etc. (from LLM_GENERATOR_DIR)" -- so at RUNTIME the subtree is `multi_agent.runtime.*`, while
the suite imports the same files as `env_generator.llm_generator.multi_agent.runtime.*`.

A `from ...tools.X import Y` is three levels up. Under the suite's root that lands on
`llm_generator` and resolves. Under the runtime's root `multi_agent` IS the top level, so it
raises -- reproduced verbatim, both roots, before this patch:

    ROOT A (sys.path=[agent])                          relative ...tools  -> OK
    ROOT B (sys.path=[agent, agent/env_generator/llm_generator])
                                                       relative ...tools  -> ImportError:
                                                         attempted relative import beyond
                                                         top-level package
    both roots                                         absolute tools.X   -> OK

WHAT IT COST. `_ui_auth_flow` carried such an import ABOVE its own `try`, deliberately, "so
an ImportError is loud". It was not loud: `run_test_user_validation`'s outer
`except Exception` turned it into `summary = {"verdict": "ERROR", "error": ...}` and
`describe_non_pass_1038` never read `error`, so the delivery log printed

    TEST-USER validation (v1.0.0): ERROR — None/None journey steps passed; no cause
    recorded — the verdict was not PASS but nothing was flagged broken, missing or
    MCP-incomplete (report a framework defect)

MEASURED over all 186 persisted test-user reports: the 6 ERROR reports are every report in
r189, r190 and r191, and all 6 carry the same `error` string. The ten reports in r183-r188 are
10/10 `ISSUES` with real journey counts (3/2, 6/6, 7/6, ...). #1203iu landed the import at
2026-10-13 22:28; r189 started 2026-10-15 14:02. So the test-user validation -- the API
journey, the MCP surface check and the browser walk -- has contributed NOTHING to every run
since, and the log blamed the reader for it. The phrase "report a framework defect" was right.
Zero occurrences of "beyond top-level package" in any run log: the reason only ever reached
the report file, under a key with no consumer (#1139's shape).

Its own comment claimed "#802 checks that this very import resolves". #802 parametrises every
function-level import in the tree and resolves it -- under the SUITE's root only. The guard
could not see the root that runs. `TheRootRatchet` below is the check that can.
"""
import ast
import pathlib
import unittest
from unittest import mock

from env_generator.llm_generator.multi_agent.runtime.test_user_validation import (
    describe_non_pass_1038,
)

_RUNTIME = pathlib.Path(
    "env_generator/llm_generator/multi_agent/runtime").resolve()
_SUBTREE = pathlib.Path("env_generator/llm_generator/multi_agent").resolve()
_LG = _SUBTREE.parent


def _top_level_packages():
    return sorted(d.name for d in _LG.iterdir()
                  if d.is_dir() and (d / "__init__.py").exists())


def _cascade_covers(node, tree):
    """#1203nc: an escape is ALLOWED when its enclosing `try` re-imports the same names
    absolutely in a handler -- the idiom tools/canonical_file_tools/shared.py documents, and
    the only shape that works for a MODULE-LEVEL import, which has no later moment to retry
    from. agents/__init__.py is the proof in both directions: under the runtime root the
    relative form is above the top level, and under the suite root the absolute form cannot
    work either, because llm_generator/__init__.py imports `.agents` before anything has put
    LLM_GENERATOR_DIR on sys.path."""
    want = {a.asname or a.name for a in node.names}
    tail = (node.module or "").split(".")[-1]
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        if not any(n is node for n in ast.walk(t) if isinstance(n, ast.ImportFrom)):
            continue
        for h in t.handlers:
            for n in ast.walk(h):
                if (isinstance(n, ast.ImportFrom) and n.level == 0 and n.module
                        and n.module.split(".")[-1] == tail
                        and want <= {a.asname or a.name for a in n.names}):
                    return True
    return False


def _escaping_imports(include_cascaded=False):
    """Every relative import that goes above its own TOP-LEVEL package. With the default it
    returns only the ones with NO absolute fallback, which must be empty.

    #1203n6 swept multi_agent/ only; #1203nc swept the rest and found 8 more, of which 5
    already cascade correctly and 3 did not -- one of them firing on every run. The
    `include_cascaded` arm exists so a test can pin the SWEEP'S SCOPE: with every site fixed,
    the uncovered list is empty whatever the scope, so narrowing it back would otherwise go
    unnoticed (mutation NC6 came back MISSED on exactly that)."""
    out = []
    tops = set(_top_level_packages())
    for f in sorted(_LG.rglob("*.py")):
        rel = f.relative_to(_LG)
        if not rel.parts or rel.parts[0] not in tops:
            continue
        pkg_depth = len(rel.parts) - 1              # multi_agent/runtime/x.py -> 2
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level and n.level > pkg_depth:
                if _cascade_covers(n, tree) and not include_cascaded:
                    continue
                out.append((str(rel), n.lineno, "." * n.level + (n.module or "")))
    return out


class TheRootRatchet(unittest.TestCase):
    """The check #802 could not make: no relative import may escape the `multi_agent` top
    level, because that is a root this tree is really imported under."""

    def test_nothing_escapes_the_multi_agent_root(self):
        esc = _escaping_imports()
        self.assertEqual(esc, [], "these imports raise `attempted relative import beyond "
                                  "top-level package` under the runtime's root: %r" % (esc,))

    def test_the_detector_sees_the_shape_it_is_for(self):
        """#1203l6's lesson: prove the instrument fires before trusting a zero. Fed the exact
        line #1203iu shipped, under the exact package depth it shipped at."""
        src = "def f():\n    from ...tools.browser._manager import page_error_fields_1202br\n"
        tree = ast.parse(src)
        node = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)][0]
        self.assertEqual(node.level, 3)
        self.assertGreater(node.level, 2, "multi_agent/runtime/x.py has package depth 2")

    def test_the_sweep_actually_reads_files(self):
        self.assertGreater(len(list(_SUBTREE.rglob("*.py"))), 100)


class TheWholeTreeRatchet1203nc(unittest.TestCase):
    """#1203nc: #1203n6 swept multi_agent/ only. The rest of the tree had 8 more escapes --
    5 already cascading to an absolute form (correct, and the only shape a module-level
    import can use), and 3 that did not:

        tools/code_tools.py:58        `_jc1203jx`      FIRING on every run
        memory/generator_memory.py    the files list   latent (0 emissions in r189-r191)
        agents/__init__.py:8          module level     latent (nothing imports it that way)

    The firing one cost the backend lane its lint details: 11 messages across r189/r190/r191
    reading "Found 52 issues: (details unavailable)", withholding 124 issues in total, from
    the agent whose job is to fix them. r185, before #1203jx introduced the wrapper, said
    "Found 78 issues: L11: [F401] `sqlalchemy.or_` imported but unused; L13: ...".
    """

    def test_nothing_in_the_tree_escapes_uncovered(self):
        esc = _escaping_imports()
        self.assertEqual(esc, [], "these raise `attempted relative import beyond top-level "
                                  "package` under the runtime root, with no absolute "
                                  "fallback: %r" % (esc,))

    def test_the_sweep_reaches_outside_multi_agent(self):
        """Pins the SCOPE, not just the package list: real escaping imports outside
        multi_agent/ must be among what the sweep examined."""
        tops = set(_top_level_packages())
        self.assertIn("tools", tops)
        self.assertIn("memory", tops)
        self.assertIn("agents", tops)
        outside = [e for e in _escaping_imports(include_cascaded=True)
                   if not e[0].startswith("multi_agent/")]
        self.assertGreaterEqual(len(outside), 4,
                                "the sweep is not looking outside multi_agent/: %r" % (outside,))
        self.assertTrue({e[0].split("/")[0] for e in outside} & {"tools", "agents", "memory"},
                        sorted({e[0].split("/")[0] for e in outside}))

    def test_the_cascade_allowance_is_not_vacuous(self):
        """If nothing were being allowed, `test_nothing_escapes` would be passing for the
        wrong reason. There really are escaping imports in the tree that cascade."""
        allowed = _escaping_imports(include_cascaded=True)
        self.assertGreaterEqual(len(allowed), 4, allowed)   # 6 at the time of writing
        self.assertEqual(_escaping_imports(), [])

    def test_the_detector_fires_on_the_shape_it_is_for(self):
        """Both shapes, fed to the real predicate. The uncovered one must be reported and the
        cascading one must not -- otherwise a zero says nothing."""
        uncovered = ast.parse(
            "def f():\n    from ..multi_agent.runtime.message_format import join_capped\n")
        node = [n for n in ast.walk(uncovered) if isinstance(n, ast.ImportFrom)][0]
        self.assertFalse(_cascade_covers(node, uncovered))
        cascading = ast.parse(
            "try:\n"
            "    from ..multi_agent.runtime.message_format import join_capped\n"
            "except ImportError:\n"
            "    from multi_agent.runtime.message_format import join_capped\n")
        node2 = [n for n in ast.walk(cascading) if isinstance(n, ast.ImportFrom)][0]
        self.assertTrue(_cascade_covers(node2, cascading))

    def test_a_handler_that_imports_DIFFERENT_names_is_not_a_cascade(self):
        src = ("try:\n"
               "    from ..multi_agent.runtime.message_format import join_capped\n"
               "except ImportError:\n"
               "    from multi_agent.runtime.message_format import something_else\n")
        tree = ast.parse(src)
        node = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)][0]
        self.assertFalse(_cascade_covers(node, tree))


class TheLintDetailsComeBack1203nc(unittest.TestCase):
    def test_the_wrapper_returns_a_capped_list_not_the_apology(self):
        from env_generator.llm_generator.tools.code_tools import _jc1203jx
        got = _jc1203jx(["L11: [F401] unused", "L13: [F401] unused", "L805: [E402] late"],
                        3, cap=2)
        self.assertNotEqual(got, "(details unavailable)")
        self.assertIn("L11", got)
        self.assertIn("1 more", got)

    def test_it_agrees_with_the_one_owner_of_the_rule(self):
        """#1032: no second implementation of the remainder rule."""
        from env_generator.llm_generator.tools.code_tools import _jc1203jx
        from env_generator.llm_generator.multi_agent.runtime.message_format import join_capped
        items = ["a", "b", "c", "d"]
        self.assertEqual(_jc1203jx(items, 4, cap=2), join_capped(items, 4, cap=2))

    def test_the_import_sits_above_the_try(self):
        """#1203it's placement: an ImportError must be loud, not become the apology."""
        import inspect
        from env_generator.llm_generator.tools import code_tools
        tree = ast.parse(inspect.getsource(code_tools._jc1203jx).lstrip())
        fn = [n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_jc1203jx"][0]
        guarded = {i.lineno for t in ast.walk(fn) if isinstance(t, ast.Try)
                   for i in ast.walk(t) if isinstance(i, ast.ImportFrom)}
        imports = [i.lineno for i in ast.walk(fn) if isinstance(i, ast.ImportFrom)]
        self.assertTrue(imports, "the import is gone")
        self.assertFalse(set(imports) & guarded, "the import went back inside the try")

    def test_the_memory_sibling_reaches_the_owner_too(self):
        """On the AST, not the source text: my own #1203nc comment there discusses the very
        import this asserts, and a text match would be fed by it."""
        import inspect
        from env_generator.llm_generator.memory import generator_memory
        tree = ast.parse(inspect.getsource(generator_memory))
        got = [(n.level, n.module) for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom)
               and (n.module or "").endswith("runtime.message_format")]
        self.assertTrue(got, "the message_format import is gone from generator_memory")
        self.assertTrue(all(lvl == 0 for lvl, _ in got),
                        "a relative form is back: %r" % (got,))


class TheErrorNamesItsCause(unittest.TestCase):
    _REAL = {"verdict": "ERROR",
             "error": "ImportError: attempted relative import beyond top-level package"}

    def test_the_r190_summary_names_the_import_error(self):
        msg = describe_non_pass_1038(dict(self._REAL), {})
        self.assertIn("attempted relative import beyond top-level package", msg)

    def test_it_no_longer_says_no_cause_recorded(self):
        msg = describe_non_pass_1038(dict(self._REAL), {})
        self.assertNotIn("no cause recorded", msg)

    def test_it_no_longer_blames_the_reader(self):
        msg = describe_non_pass_1038(dict(self._REAL), {})
        self.assertNotIn("report a framework defect", msg)

    def test_an_error_beside_a_broken_list_keeps_both(self):
        msg = describe_non_pass_1038(
            {"verdict": "ERROR", "error": "RuntimeError: boom", "broken": ["GET /api/x"]}, {})
        self.assertIn("RuntimeError: boom", msg)
        self.assertIn("GET /api/x", msg)

    def test_the_fallback_sentence_survives_for_a_report_with_no_error(self):
        """#1035's rule, unchanged: the cause slot must never render empty."""
        msg = describe_non_pass_1038({"verdict": "PARTIAL"}, {})
        self.assertIn("no cause recorded", msg)

    def test_an_empty_error_string_is_not_a_cause(self):
        for blank in ("", None, "   "):
            with self.subTest(error=repr(blank)):
                msg = describe_non_pass_1038({"verdict": "ERROR", "error": blank}, {})
                self.assertIn("no cause recorded", msg)

    def test_a_non_mapping_summary_does_not_raise(self):
        for bad in (None, "nope", 7, []):
            with self.subTest(summary=repr(bad)):
                self.assertIsInstance(describe_non_pass_1038(bad, {}), str)

    def test_the_error_is_capped(self):
        msg = describe_non_pass_1038({"verdict": "ERROR", "error": "X" * 5000}, {})
        self.assertLess(len(msg), 1200)


class BothHalvesInOneRun(unittest.TestCase):
    """#1139's shape needs BOTH halves checked together: the error path must WRITE the key and
    the describer must READ it. Asserting each alone is how #1139 shipped a key with no
    consumer. This drives the real `except Exception` in `run_test_user_validation` and feeds
    its real summary to the real describer -- offline, no app, no network."""

    def _errored_report(self):
        import tempfile
        from env_generator.llm_generator.multi_agent.runtime import test_user_validation as T
        with tempfile.TemporaryDirectory() as d:
            # `business_endpoints` that cannot be iterated -- raises inside the try, which is
            # the same handler the ImportError went through.
            return T.run_test_user_validation(
                pathlib.Path(d), object(), version="1.0.0",
                base_url="http://127.0.0.1:9", compose_file=None, llm=None)

    def test_the_handler_writes_the_key_the_describer_reads(self):
        rep = self._errored_report()
        summ = rep.get("summary") or {}
        self.assertEqual(summ.get("verdict"), "ERROR")
        self.assertTrue(str(summ.get("error") or "").strip(),
                        "the error path stopped recording the reason")
        msg = describe_non_pass_1038(summ, rep.get("mcp") or {})
        self.assertIn("TypeError", msg)
        self.assertNotIn("no cause recorded", msg)

    def test_the_delivery_line_no_longer_blames_the_reader(self):
        rep = self._errored_report()
        msg = describe_non_pass_1038(rep.get("summary") or {}, rep.get("mcp") or {})
        self.assertNotIn("report a framework defect", msg)
        self.assertIn("Not a verdict about the app", msg)


class ItSaysOnlyWhatIsTrue1203n8(unittest.TestCase):
    """#1203n8: #1203n6's own first wording was false, and the reports on disk say so.

    The three steps run in order inside one try -- journey, MCP surface, auth-flow walk -- so
    an error at the third does not mean the first two did not run. MEASURED on all 6 ERROR
    reports in r189/r190/r191: every one carries a POPULATED `api` and `mcp` and NO `ui`.
    r190's journey had found `POST /api/comments -> 404` in all three of its reports: a real
    app finding, collected and then thrown away because the summary was never assembled.

    So "no journey, MCP or UI evidence was produced" was a false sentence in the framework
    (#1203j2) -- mine, added the same day. It must not come back."""

    _REAL = {"verdict": "ERROR",
             "error": "ImportError: attempted relative import beyond top-level package"}

    def test_it_does_not_claim_nothing_was_produced(self):
        msg = describe_non_pass_1038(dict(self._REAL), {})
        self.assertNotIn("no journey", msg)
        self.assertNotIn("evidence was produced", msg)

    def test_it_says_the_verdict_is_what_was_missing(self):
        msg = describe_non_pass_1038(dict(self._REAL), {})
        self.assertIn("derive a verdict", msg)

    def test_it_points_at_where_the_collected_evidence_is(self):
        msg = describe_non_pass_1038(dict(self._REAL), {})
        self.assertIn("test_user_reports", msg)
        self.assertIn("unjudged", msg)

    def test_the_r190_report_shape_is_what_it_describes(self):
        """The shape the claim rests on: summary ERROR with api and mcp already collected."""
        rep = {"version": "1.0.0",
               "api": {"steps": [{"action": "create comments", "method": "POST",
                                  "path": "/api/comments", "status": 404, "ok": False}],
                       "actor": "alpha"},
               "mcp": {"server_found": True, "tools_expected": 12, "tools_found": 11,
                       "complete": False},
               "summary": dict(self._REAL)}
        self.assertNotIn("ui", rep)
        msg = describe_non_pass_1038(rep["summary"], rep["mcp"])
        self.assertNotIn("evidence was produced", msg)
        self.assertIn("attempted relative import", msg)


class TheOwnerIsReachedAtRuntime(unittest.TestCase):
    """Not "the literal matches" -- the owner's value must actually arrive. Both duplicates
    happened to equal their owner today, so an equality test would have passed while the
    import was dead."""

    def test_the_gitignore_takes_the_owners_scratch_dirs(self):
        import tempfile
        from env_generator.llm_generator.multi_agent.runtime.scaffolder import (
            ensure_base_gitignore,
        )
        import tools.file_tools as ft
        with mock.patch.object(ft, "FRAMEWORK_SCRATCH_DIRS",
                               (".agents", "sentinel_1203n6")):
            with tempfile.TemporaryDirectory() as d:
                ensure_base_gitignore(d)
                body = (pathlib.Path(d) / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("sentinel_1203n6", body,
                      "the hand-written copy is still in use, or the import did not resolve")

    def test_the_viewport_comes_from_the_owner(self):
        from env_generator.llm_generator.multi_agent.runtime import (
            test_user_runner, visual_fidelity,
        )
        from tools.browser._bootstrap import CANONICAL_VIEWPORT_646 as owner
        self.assertEqual(test_user_runner._VIEWPORT, dict(owner))
        self.assertEqual(visual_fidelity._VIEWPORT, dict(owner))

    def test_no_literal_viewport_fallback_remains(self):
        """#1032 says these two cannot drift. With the import dead the duplicate was the ONLY
        value in use, so the claim was false; it is true again only if the copy is gone."""
        for mod in ("test_user_runner.py", "visual_fidelity.py"):
            src = (_RUNTIME / mod).read_text(encoding="utf-8")
            tree = ast.parse(src)
            for n in ast.walk(tree):
                if not isinstance(n, ast.Assign):
                    continue
                names = [t.id for t in n.targets if isinstance(t, ast.Name)]
                if "_CV646" in names and isinstance(n.value, ast.Dict):
                    self.fail("%s still carries a literal viewport fallback at L%d"
                              % (mod, n.lineno))


class TheLoudImportsStayLoud(unittest.TestCase):
    """#1203it/#1203iu placed two of these imports ABOVE their own `try` on purpose: an
    ImportError must not degrade into "(unreadable)" or into no probe at all. Fixing the form
    must not quietly wrap them."""

    def _import_nodes(self, path, func, want="tools.browser._manager"):
        """The heal-path import in the same functions SHOULD be inside a try -- it only runs
        from an except. So this narrows to the probe's own module, not `tools.browser`."""
        tree = ast.parse((_RUNTIME / path).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func:
                guarded = {s.lineno for t in ast.walk(n) if isinstance(t, ast.Try)
                           for s in ast.walk(t) if isinstance(s, ast.ImportFrom)}
                return [(i.lineno, i.lineno in guarded) for i in ast.walk(n)
                        if isinstance(i, ast.ImportFrom) and (i.module or "").endswith(want)]
        return []

    def test_the_heal_import_IS_guarded_and_that_is_right(self):
        """The control for the two above: the heal import runs only from an except, so being
        inside a try is correct. Without this, the pair of assertions above could be read as
        "no tools import may ever be guarded"."""
        got = self._import_nodes("test_user_validation.py", "_ui_auth_flow",
                                 want="tools.browser._bootstrap")
        self.assertTrue(got, "the heal import is gone")
        self.assertTrue(all(g[1] for g in got), "the heal import left its except path")

    def test_the_page_error_reader_is_unguarded(self):
        got = self._import_nodes("test_user_runner.py", "_page_error_entry_1203iu")
        self.assertTrue(got, "the page-error import is gone")
        self.assertFalse([g for g in got if g[1]], "it was wrapped in a try: %r" % (got,))

    def test_the_auth_flow_probe_import_is_unguarded(self):
        got = self._import_nodes("test_user_validation.py", "_ui_auth_flow")
        self.assertTrue(got, "the page-error import is gone from test_user_validation")
        self.assertFalse([g for g in got if g[1]],
                         "it was wrapped in a try, so an ImportError degrades to no probe "
                         "at all -- the placement #1203it paid for: %r" % (got,))


if __name__ == "__main__":
    unittest.main()
