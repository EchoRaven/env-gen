r"""#1203ml: the build failed four times and nothing in the log said why.

`_compose`'s failure path is a ladder: `_HOST_LEVEL_1202CN` matches the daemon's wording,
then `#1202hr` MEASURES the disk when no wording matched. r189 fell past both -- root had 61G
free, so `#1202hr` correctly said nothing -- and the frontend rebuilt four times with the
cause unnamed.

The cause: `app/frontend` is a 393-406 MB build context of which 391 MB is
`public/assets/real_videos`, and docker tars the whole context before the first instruction.
The transcript is that tar stream breaking: `archive/tar: missed writing 2982288 bytes` over
82 files, `Can't close tar writer`, `Error processing tar file(exit status 1): unexpected EOF`.

Measured by CONTEXT rather than by wording, over the modern corpus:

    context with >100MB of staged media    29 runs    24 hit it (83%)
    context with <=100MB                    3 runs     0 (0%)

Not deterministic -- r187 and r188 carry the same 391 MB and built clean -- so this annotates
and never aborts, and says a retry may succeed.

★ A name that was not there, the fourth time this week: the first draft of the call reached
for `orch`/`project_dir`, and `_compose(compose_file, *args, cwd, timeout)` has neither. The
`except Exception: pass` three lines below would have turned that NameError into silence --
the same shape as #1203md/#1203me/#1203mf. Caught before landing by reading the enclosing
signature rather than trusting it, which is why `test_the_call_uses_only_names_in_scope`
exists: it asserts the argument is derived from `compose_file`, the one path this function
is given.
"""
import ast
import inspect
import os
import unittest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR

TAR_TRANSCRIPT = (
    'time="2026-10-15T14:54:10-05:00" level=error msg="Can\'t add file '
    '/x/app/frontend/public/assets/real_videos/a.mp4 to tar: archive/tar: '
    'missed writing 2982288 bytes"\n'
    'Can\'t close tar writer: archive/tar: missed writing 2982288 bytes\n'
    'Error response from daemon: Error processing tar file(exit status 1): unexpected EOF\n'
)


def _tree():
    return ast.parse(inspect.getsource(VR))


def _project(tmp, media_bytes, media_dir="public/assets/real_videos"):
    """A run tree with `media_bytes` of staged media under app/frontend."""
    d = os.path.join(tmp, "app", "frontend", *media_dir.split("/"))
    os.makedirs(d)
    with open(os.path.join(d, "clip.mp4"), "wb") as fh:
        fh.write(b"\0" * media_bytes)
    return tmp


class ItSpeaksOnlyForTheFailureItExplains(unittest.TestCase):
    def test_a_big_context_and_a_broken_tar_is_named(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = VR.oversized_build_context_1203ml(
                _project(t, 300 * 1024 * 1024), TAR_TRANSCRIPT)
        self.assertIsNotNone(got, "the one case this exists for returned None")
        self.assertIn("frontend", got)
        self.assertIn("real_videos", got)
        self.assertIn("#1203ml", got)
        self.assertIn("retry", got.lower(),
                      "it must say a retry may succeed — the failure is load-dependent")

    def test_a_big_context_that_built_fine_is_not_news(self):
        """#647: no wider than its evidence. r187/r188 carry 391 MB and built clean."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = VR.oversized_build_context_1203ml(
                _project(t, 300 * 1024 * 1024), "some other compose failure")
        self.assertIsNone(got)

    def test_a_broken_tar_with_a_small_context_is_not_blamed_on_size(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = VR.oversized_build_context_1203ml(
                _project(t, 2 * 1024 * 1024), TAR_TRANSCRIPT)
        self.assertIsNone(got, "a 2 MB context was blamed for a broken tar stream")

    def test_could_not_tell_is_not_a_verdict(self):
        """#883: no tree, no app dir, nothing readable -> None, never a guess."""
        self.assertIsNone(VR.oversized_build_context_1203ml("/nonexistent/xyz", TAR_TRANSCRIPT))
        self.assertIsNone(VR.oversized_build_context_1203ml(None, TAR_TRANSCRIPT))
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(VR.oversized_build_context_1203ml(t, TAR_TRANSCRIPT))

    def test_it_names_whichever_directory_is_actually_biggest(self):
        """The media dir name varies by product — tiktok stages `real_videos`, another
        product stages something else — so the sentence must be computed, not written."""
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            got = VR.oversized_build_context_1203ml(
                _project(t, 300 * 1024 * 1024, "public/media/clips"), TAR_TRANSCRIPT)
        self.assertIsNotNone(got)
        self.assertIn("clips", got, "the directory is hardcoded rather than measured")
        self.assertNotIn("real_videos", got)

    def test_it_never_raises(self):
        for bad in (object(), 12, [], {}):
            self.assertIsNone(VR.oversized_build_context_1203ml(bad, TAR_TRANSCRIPT))


class TheCallSiteIsTheThirdRungAndUsesNamesInScope(unittest.TestCase):
    def test_it_is_called(self):
        names = {n.func.id for n in ast.walk(_tree())
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("oversized_build_context_1203ml", names,
                      "defined but never called (#1202w1: a name is not a use)")

    def test_the_call_uses_only_names_in_scope(self):
        """The trap this patch nearly fell into: `_compose` has no `orch`/`project_dir`, and
        the enclosing `except Exception: pass` would swallow the NameError."""
        fn = next((n for n in ast.walk(_tree())
                   if isinstance(n, ast.FunctionDef) and n.name == "_compose"), None)
        self.assertIsNotNone(fn, "_compose is gone — the call site moved")
        bound = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        bound |= {t.id for sub in ast.walk(fn) for t in ast.walk(sub)
                  if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
        call = next((n for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "oversized_build_context_1203ml"), None)
        self.assertIsNotNone(call, "the #1203ml call is not inside _compose any more")
        free = {t.id for a in call.args for t in ast.walk(a)
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Load)}
        unbound = free - bound - set(dir(__builtins__)) - {"Path", "VR"}
        self.assertFalse(
            unbound,
            "the #1203ml call reads name(s) `_compose` does not bind, and the except below "
            "would swallow the NameError: %s" % sorted(unbound))

    def test_the_disk_rung_above_it_is_still_REACHED(self):
        """Not source order -- mutation ML5 proved that is not the property.

        My first version compared `src.index(...)` positions, and `if not _host and False:`
        left both positions untouched while making the disk check dead. What matters is the
        STRUCTURE: the disk check must run under a guard that is exactly `not _host`, and the
        #1203ml call must sit in the `orelse` of `if _host:` so it speaks only when neither
        rung above it did. A full disk is the cause that needs the operator, so it gets the
        first word; this reads it off the tree instead of off the text.
        """
        fn = next((n for n in ast.walk(_tree())
                   if isinstance(n, ast.FunctionDef) and n.name == "_compose"), None)
        self.assertIsNotNone(fn)
        disk_guard = None
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                   and c.func.id == "low_docker_disk_1202hr"
                   for b in node.body for c in ast.walk(b)):
                disk_guard = node
        self.assertIsNotNone(disk_guard, "nothing guards the #1202hr disk measurement")
        self.assertIsInstance(
            disk_guard.test, ast.UnaryOp,
            "the disk check's guard is no longer a bare `not _host` — anything conjoined to "
            "it can switch the rung off while leaving it in place (mutation ML5)")
        self.assertIsInstance(disk_guard.test.op, ast.Not)
        self.assertIsInstance(disk_guard.test.operand, ast.Name)

        host_if = next((n for n in ast.walk(fn)
                        if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                        and n.test.id == "_host"), None)
        self.assertIsNotNone(host_if, "`if _host:` is gone — the ladder was restructured")
        in_orelse = any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id == "oversized_build_context_1203ml"
            for b in host_if.orelse for c in ast.walk(b))
        self.assertTrue(
            in_orelse,
            "#1203ml is not in the `else` of `if _host:`, so it can speak over a host "
            "fault that the operator actually has to clear")

    def test_its_message_does_not_call_it_a_host_fault(self):
        """#1202cn's sentence tells the operator to clear a host condition. An oversized
        context is not that, so the two must not share wording.

        Read off the logger CALL, not a byte window: my first version was
        `src[i:i + 400]`, which the #943 ratchet rejected on sight -- a window sized in
        bytes moves the moment a comment above it grows. The AST has the exact string.
        """
        msgs = []
        for node in ast.walk(_tree()):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            parts, stack = [], [node.args[0]]
            while stack:
                cur = stack.pop()
                if isinstance(cur, ast.Constant) and isinstance(cur.value, str):
                    parts.append(cur.value)
                elif isinstance(cur, ast.BinOp):
                    stack.extend([cur.right, cur.left])
            m = "".join(parts)
            if m.startswith("#1203ml "):
                msgs.append(m)
        self.assertTrue(msgs, "the #1203ml log line is gone")
        for m in msgs:
            self.assertNotIn("HOST failure", m,
                             "#1203ml borrowed #1202cn's host-fault wording: %r" % m[:90])
            self.assertNotIn("operator has to clear", m,
                             "#1203ml tells the operator to clear something they cannot")


if __name__ == "__main__":
    unittest.main()
