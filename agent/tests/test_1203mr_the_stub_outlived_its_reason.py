r"""#1203mr: the auto-stub is permanent, and its own guarantee expires the moment it lands.

`repair_frontend_missing_local_exports` promises

    "MAXIMALLY conservative: only stub a name that appears NOWHERE in the target module's
     source (so a parser miss can never cause a duplicate-declaration build break)"

and calls itself idempotent. Both halves hold AT WRITE TIME -- the name is re-checked against
a fresh read, twice, and #1203jv added an `unrepairable` branch for the case where something
named `n` is already present. Neither half holds afterwards: the stub is permanent, so once
the lane declares the name itself there are two `export const <n>` and Rollup hard-fails with
`Identifier already declared` -- precisely the break the sentence says cannot happen.

r190, live: `src/lib/staticData.js` line 11 is the lane's real `export const seededComments =
[` and line 19 is this module's stub, under its own `// auto-reconciled missing exports`
comment. EIGHT consecutive `docker build FAILED`, api_smoke blocked, a remediation task
dispatched. The lane then deleted the duplicate itself, so the run recovered; the cost was
build cycles rather than the run.

RATE, stated plainly because it is small: the marker appears in 3 files across the corpus and
1 of those 3 carries the collision. The argument for fixing it is CATEGORY, not frequency --
a hard build failure -- and the retraction is bounded: only lines this module wrote, matched
on the text this module emits, and only when the name is really declared elsewhere in the
same file. A file with no collision comes out byte-identical.
"""
import io
import os
import tempfile
import unittest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as FS

# r190's two lines, verbatim
REAL = "export const seededComments = [\n  { id: 'c-01', text: 'nice' },\n];\n"
STUB = ("\n// auto-reconciled missing exports (lane import/export drift).\n"
        "export const seededComments = (...args) => { console.error('[auto-stub] "
        "seededComments is imported but its module does not export it - MISSING "
        "IMPLEMENTATION, not an empty result. Returning [] so the page still renders.'); "
        "return []; };\n")
COMPONENT_STUB = ("\n// auto-reconciled missing exports (lane import/export drift).\n"
                  "export const PlusSquareIcon = (props) => null;  // auto-stub component\n")


def _tree(**files):
    t = tempfile.mkdtemp()
    os.makedirs(os.path.join(t, "src", "lib"))
    for name, text in files.items():
        io.open(os.path.join(t, "src", "lib", name.replace("__", ".")), "w",
                encoding="utf-8").write(text)
    return t


def _read(t, name):
    return io.open(os.path.join(t, "src", "lib", name), encoding="utf-8").read()


class TheLanesDeclarationWins(unittest.TestCase):
    def test_r190s_collision_is_repaired(self):
        t = _tree(staticData__js=REAL + STUB)
        got = FS.retract_stale_auto_stubs_1203mr(t)
        self.assertEqual(got.get("retracted"), [("staticData.js", ["seededComments"])])
        after = _read(t, "staticData.js")
        self.assertEqual(after.count("export const seededComments"), 1)
        self.assertIn("export const seededComments = [", after)
        self.assertNotIn("[auto-stub] seededComments", after)

    def test_the_component_stub_form_too(self):
        real = "export const PlusSquareIcon = () => <svg/>;\n"
        t = _tree(icons__jsx=real + COMPONENT_STUB)
        FS.retract_stale_auto_stubs_1203mr(t)
        after = _read(t, "icons.jsx")
        self.assertEqual(after.count("export const PlusSquareIcon"), 1)
        self.assertNotIn("auto-stub component", after)

    def test_it_is_idempotent(self):
        t = _tree(staticData__js=REAL + STUB)
        FS.retract_stale_auto_stubs_1203mr(t)
        once = _read(t, "staticData.js")
        self.assertEqual(FS.retract_stale_auto_stubs_1203mr(t).get("retracted"), [])
        self.assertEqual(_read(t, "staticData.js"), once)


class TheConservativeHalfIsNotUndone(unittest.TestCase):
    """The stub exists to keep Rollup from failing on a genuinely missing export. Removing one
    that is still doing its job would re-create the failure it was written for."""

    def test_a_stub_with_no_real_declaration_is_untouched(self):
        t = _tree(staticData__js=STUB.lstrip("\n"))
        before = _read(t, "staticData.js")
        self.assertEqual(FS.retract_stale_auto_stubs_1203mr(t).get("retracted"), [])
        self.assertEqual(_read(t, "staticData.js"), before)

    def test_a_file_with_no_stub_at_all_is_byte_identical(self):
        t = _tree(staticData__js=REAL)
        before = _read(t, "staticData.js")
        FS.retract_stale_auto_stubs_1203mr(t)
        self.assertEqual(_read(t, "staticData.js"), before)

    def test_only_this_modules_own_emission_shape_is_removed(self):
        """A lane line that merely mentions a stub is not ours to delete."""
        lane = ("export const seededComments = [];\n"
                "// TODO: the auto-stub for seededComments used to live here\n"
                "export function seededCommentsHelper() { return 1; }\n")
        t = _tree(staticData__js=lane)
        before = _read(t, "staticData.js")
        FS.retract_stale_auto_stubs_1203mr(t)
        self.assertEqual(_read(t, "staticData.js"), before)

    def test_another_names_stub_survives_its_neighbour_being_retracted(self):
        t = _tree(staticData__js=REAL + STUB + COMPONENT_STUB)
        got = FS.retract_stale_auto_stubs_1203mr(t)
        self.assertEqual(got.get("retracted"), [("staticData.js", ["seededComments"])])
        after = _read(t, "staticData.js")
        self.assertIn("PlusSquareIcon", after, "an unrelated, still-needed stub was removed")


class ItRunsBeforeTheStubbingAndStaysTotal(unittest.TestCase):
    def test_the_repair_pass_retracts_first(self):
        import ast
        import inspect
        fn = next((n for n in ast.walk(ast.parse(inspect.getsource(FS)))
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "repair_frontend_missing_local_exports"), None)
        self.assertIsNotNone(fn)
        calls = [c for c in ast.walk(fn)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        names = [c.func.id for c in calls]
        self.assertIn("retract_stale_auto_stubs_1203mr", names,
                      "the retraction is defined but the repair pass never calls it")

    def test_the_docstring_no_longer_claims_what_it_cannot(self):
        """#1203j2: the parenthesis is true at write time only, and now says so."""
        doc = FS.repair_frontend_missing_local_exports.__doc__ or ""
        self.assertIn("#1203mr", doc)
        self.assertIn("AT WRITE TIME", doc)

    def test_it_never_raises(self):
        for bad in (None, "/nonexistent/zz", 7, object()):
            self.assertIsInstance(FS.retract_stale_auto_stubs_1203mr(bad), dict)

    def test_the_crash_path_announces(self):
        import ast
        import inspect
        fn = next((n for n in ast.walk(ast.parse(inspect.getsource(FS)))
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "retract_stale_auto_stubs_1203mr"), None)
        self.assertIsNotNone(fn)
        for h in [x for x in ast.walk(fn) if isinstance(x, ast.ExceptHandler)]:
            inner = {c.func.id for c in ast.walk(h)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            if "warn_once_1201" in inner:
                return
        self.fail("no except handler announces — a failed retraction would be silent (#1202ah)")

    def test_the_write_is_a_declared_clobber(self):
        """The target is LANE-OWNED, so #1202cw refuses the write unless `clobber_ok` names
        the ticket that argued for it — and an empty one means the retraction silently does
        not happen.

        Read off the KEYWORD ARGUMENT, not the source text: my first version asserted
        `"clobber_ok" in src` and `"#1203mr" in src`, and mutation MR6c emptied the value
        while leaving both strings in the file (the word `clobber_ok` is still there and the
        ticket appears elsewhere in the function). The fixtures cannot catch this
        behaviourally, because a tmp path is not lane-owned and the write succeeds either
        way, so the argument itself is what has to be pinned.
        """
        import ast
        import inspect
        fn = next((n for n in ast.walk(ast.parse(inspect.getsource(FS)))
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "retract_stale_auto_stubs_1203mr"), None)
        self.assertIsNotNone(fn)
        found = []
        for call in [c for c in ast.walk(fn) if isinstance(c, ast.Call)]:
            for kw in call.keywords:
                if kw.arg != "clobber_ok":
                    continue
                parts, stack = [], [kw.value]
                while stack:
                    cur = stack.pop()
                    if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                        parts.append(cur.value)
                    elif isinstance(cur, ast.BinOp):
                        stack.extend([cur.right, cur.left])
                    elif isinstance(cur, ast.JoinedStr):
                        stack.extend(cur.values)
                found.append("".join(parts))
        self.assertTrue(found, "nothing passes clobber_ok — #1202cw would refuse the write")
        for text in found:
            self.assertTrue(
                text.strip(),
                "clobber_ok is EMPTY, so #1202cw refuses and the retraction silently does "
                "not happen on the lane-owned file it exists for")
            self.assertIn("#1203mr", text,
                          "the declared clobber does not name the ticket that argued for it")


if __name__ == "__main__":
    unittest.main()
