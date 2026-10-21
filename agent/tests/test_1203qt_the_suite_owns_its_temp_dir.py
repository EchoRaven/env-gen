"""#1203qt / #1203qu: the verification machinery does not get to corrupt the thing it verifies.

Two guards, both for failures that present as defects in the code under test:

  * `--basetemp` is not "put the temp dirs here". pytest's own tmpdir.py does
    `if basetemp.exists(): rm_rf(basetemp)` before creating it, so a SECOND pytest handed
    the same path deletes the first one's temp dirs mid-run. The symptom is a
    FileNotFoundError out of `json_store._save_raw`'s `os.replace` -- the temp file vanished
    between the write and the rename -- and on 2026-10-20 one such failure passed 4/4 when
    re-run alone. The flock refuses a second SUITE; it cannot see a hand-typed
    `python -m pytest ... --basetemp=<shared path>`, which bypasses suite.sh and so bypasses
    the lock. So suite.sh owns a basetemp of its own.

  * `mutate.py` edits its target in place and restores it on the way out -- if it gets
    there. A timeout or a killed parent leaves the mutant ON DISK. Three were found sitting
    in the tree that day, each behind a single `M` in git status and each a live defect; one
    was left by `mutation_verdicts.py` itself. So that tool restores what it finds dirty.

The shell is EXECUTED here, not read. `test_1203gc` pins suite.sh's default roots by regex
(with a loud assertion when the shape moves), which is right for a thing with no observable
output; this block has one, so driving it is strictly stronger.

LOCAL-ONLY (agent/tests/ is gitignored).
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
REPO = AGENT_DIR.parent
SUITE_SH = REPO / "scripts" / "suite.sh"

sys.path.insert(0, str(REPO / "scripts"))


def _basetemp_block() -> str:
    """suite.sh's basetemp `case` plus the cleanup, sliced by LANDMARK.

    Not a fixed-width window (#943): the slice runs from the ticket comment to the pytest
    invocation, and fails loudly if either landmark moves."""
    src = SUITE_SH.read_text(encoding="utf-8")
    i = src.find("# #1203qt:")
    assert i >= 0, "suite.sh no longer carries the #1203qt basetemp block"
    j = src.find('"$PY" -m pytest', i)
    assert j > i, "the #1203qt block no longer sits immediately before the pytest call"
    return src[i:j]


def _argv_after_block(args, env_root=None):
    """The argv suite.sh would hand pytest, by RUNNING its own case block."""
    block = _basetemp_block()
    pre = 'SUITE_BASETEMP_ROOT=%s\n' % env_root if env_root else ''
    script = (pre + 'set -- ' + ' '.join("'%s'" % a for a in args) + '\n'
              + block + '\nprintf "%s\\n" "$@"\necho "OWN=$_own_basetemp"')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if l.strip()]
    own = next((l[4:] for l in lines if l.startswith("OWN=")), "")
    return [l for l in lines if not l.startswith("OWN=")], own


class SuiteOwnsItsBasetemp(unittest.TestCase):

    def test_a_basetemp_is_injected_when_the_caller_gave_none(self):
        argv, own = _argv_after_block(["tests", "-q"], env_root="/tmp/qt_probe")
        self.assertTrue(own, "no basetemp was injected")
        self.assertTrue(any(a.startswith("--basetemp=") for a in argv), argv)
        self.assertIn(own, " ".join(argv))

    def test_two_runs_do_not_share_the_path(self):
        """The whole point: a shared path means the second run rm_rf's the first one's."""
        _a1, own1 = _argv_after_block(["tests"], env_root="/tmp/qt_probe")
        _a2, own2 = _argv_after_block(["tests"], env_root="/tmp/qt_probe")
        self.assertTrue(own1 and own2)
        self.assertNotEqual(own1, own2,
                            "two invocations got the same basetemp: %r" % own1)

    def test_an_explicit_basetemp_is_left_alone(self):
        argv, own = _argv_after_block(["tests", "--basetemp=/tmp/caller_chose"],
                                      env_root="/tmp/qt_probe")
        self.assertEqual("", own, "injected over the caller's explicit --basetemp")
        self.assertEqual(1, sum(1 for a in argv if a.startswith("--basetemp")), argv)
        self.assertIn("--basetemp=/tmp/caller_chose", argv)

    def test_the_cleanup_runs_only_on_success(self):
        """A failing run's temp tree is the evidence for the failure, and /data is a shared
        disk nobody reclaims (#1202ap counted 5 orphaned partial writes on it)."""
        src = SUITE_SH.read_text(encoding="utf-8")
        i = src.find('"$PY" -m pytest')
        tail = src[i:]
        m = re.search(r'if \[ -n "\$_own_basetemp" \] && \[ "\$rc" = "0" \]', tail)
        self.assertIsNotNone(
            m, "the cleanup no longer requires BOTH an injected path and rc=0:\n%s" % tail[:400])
        self.assertLess(tail.find("rc=$?"), m.start(), "cleanup reads rc before it is set")


def _tmpdir_after_block(args, env_tmpdir=None, root=None):
    """What suite.sh does to TMPDIR, by RUNNING its own block.

    `env_tmpdir=None` means TMPDIR is UNSET for the child (`env -u`), which is the case that
    matters -- that is when mkdtemp() falls through to /tmp."""
    block = _basetemp_block()
    pre = 'SUITE_TMPDIR_ROOT=%s\n' % root if root else ''
    # `set -u` BECAUSE PRODUCTION HAS IT. suite.sh runs under `set -uo pipefail`, and the
    # first version of this helper drove the block in a plain `bash -c` without it -- a more
    # permissive shell than the real one. So `[ -n "$TMPDIR" ]` passed five green tests here
    # and then aborted the suite with `TMPDIR: unbound variable` on its first real run, on
    # the unset-TMPDIR path these tests are entirely about. Driving the shell is only
    # stronger than reading it if the shell is the same shell.
    script = ('set -u\n' + pre + 'set -- ' + ' '.join("'%s'" % a for a in args) + '\n'
              + block + '\necho "TMPDIR=${TMPDIR:-}"\necho "OWNTMP=$_own_tmpdir"')
    cmd = ["bash", "-c", script]
    if env_tmpdir is None:
        cmd = ["env", "-u", "TMPDIR"] + cmd
    else:
        cmd = ["env", "TMPDIR=%s" % env_tmpdir] + cmd
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    g = lambda k: next((l[len(k) + 1:] for l in out.splitlines() if l.startswith(k + "=")), "")
    return g("TMPDIR"), g("OWNTMP")


class SuiteOwnsItsTmpdir(unittest.TestCase):
    """#1203qy: --basetemp governs the FIXTURES; 299 test files call tempfile.mkdtemp()
    directly, and those honour TMPDIR. On 2026-10-20 that had already put 1,474,363 entries
    and 177G into /tmp, leaving `/` with 77M -- the failure that makes the harness lose every
    command's stdout while the commands still run, so a scan returns nothing and reads
    exactly like a clean result."""

    def test_tmpdir_is_pointed_off_the_root_filesystem(self):
        root = "/data/common/haibotong/pytest_tmp"
        got, own = _tmpdir_after_block(["tests", "-q"], env_tmpdir=None, root=root)
        self.assertTrue(own, "TMPDIR was left unset: mkdtemp() would land in /tmp")
        self.assertTrue(got.startswith(root),
                        "TMPDIR is %r, not under %r -- mkdtemp() still fills /" % (got, root))
        self.assertNotEqual("/tmp", got)

    def test_two_runs_get_different_tmpdirs(self):
        root = "/data/common/haibotong/pytest_tmp"
        _g1, o1 = _tmpdir_after_block(["tests"], env_tmpdir=None, root=root)
        _g2, o2 = _tmpdir_after_block(["tests"], env_tmpdir=None, root=root)
        self.assertTrue(o1 and o2)
        self.assertNotEqual(o1, o2, "both runs share a TMPDIR: %r" % o1)

    def test_a_caller_who_set_tmpdir_keeps_it(self):
        got, own = _tmpdir_after_block(["tests"], env_tmpdir="/tmp/caller_picked_this")
        self.assertEqual("/tmp/caller_picked_this", got, "overrode the caller's TMPDIR")
        self.assertEqual("", own, "claimed ownership of a TMPDIR it did not create")

    def test_the_tmpdir_cleanup_also_requires_success(self):
        src = SUITE_SH.read_text(encoding="utf-8")
        i = src.find('"$PY" -m pytest')
        tail = src[i:]
        m = re.search(r'if \[ -n "\$_own_tmpdir" \] && \[ "\$rc" = "0" \]', tail)
        self.assertIsNotNone(m, "the TMPDIR cleanup no longer requires BOTH an owned path "
                                "and rc=0:\n%s" % tail[:500])
        self.assertLess(tail.find("rc=$?"), m.start(), "cleanup reads rc before it is set")

    def test_a_failed_mkdir_warns_instead_of_falling_back_quietly(self):
        """The user's standing rule: no fallback that masks a failure. Falling back to /tmp
        without saying so is exactly the condition this block prevents."""
        block = _basetemp_block()
        self.assertIn("WARNING", block,
                      "no warning when the temp root cannot be created")
        i = block.find("WARNING")
        self.assertIn("NOT cleaned", block[i:i + 400],
                      "the warning does not say the consequence")


class TheVerdictsToolRestoresWhatItDirties(unittest.TestCase):
    """The guard restores to the SNAPSHOT it read, never to HEAD.

    My first version of it ran `git checkout -- <target>` on a dirty file, reasoning that
    dirty meant "mutate.py was killed and left a mutant". Dirty means no such thing -- it is
    just as likely to be somebody's uncommitted patch, and on 2026-10-20 it silently
    discarded an uncommitted change in heal_pipeline.py. These pin the replacement so the
    HEAD-based version cannot come back."""

    def _mv(self):
        import mutation_verdicts as mv
        return mv

    def test_the_guard_exists_and_takes_a_snapshot(self):
        mv = self._mv()
        self.assertTrue(hasattr(mv, "_restore_from_snapshot"),
                        "the restore guard is gone; a killed mutate.py would leave the mutant")
        import inspect
        params = list(inspect.signature(mv._restore_from_snapshot).parameters)
        self.assertEqual(2, len(params),
                         "the guard must take the target AND the bytes read before the run, "
                         "or it cannot tell a mutant from an author's patch: %s" % params)

    def test_it_never_shells_out_to_restore(self):
        """`git checkout --` is what destroyed uncommitted work. It must not come back.

        #1203qk/my-own-lesson: the FIRST version of this test matched the text "checkout"
        and failed -- fed by the docstring, which quotes the forbidden command in order to
        explain it. A source-text assertion cannot tell an explanation from a call. So ask
        the AST instead: inside this function, nothing is invoked that could run a command.
        That is also the property that matters -- restoring must be a file write and nothing
        else."""
        import ast
        import inspect
        fn = ast.parse(inspect.getsource(self._mv()._restore_from_snapshot)).body[0]
        called = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Attribute):
                    base = f.value.id if isinstance(f.value, ast.Name) else ""
                    called.add("%s.%s" % (base, f.attr) if base else f.attr)
                elif isinstance(f, ast.Name):
                    called.add(f.id)
        shells = {"subprocess.run", "subprocess.call", "subprocess.check_output",
                  "subprocess.Popen", "os.system", "os.popen", "run", "system", "popen",
                  "check_output", "Popen"}
        self.assertEqual(set(), called & shells,
                         "the restore guard runs a command (%s); restoring via git discards "
                         "the author's uncommitted patch" % sorted(called & shells))
        # `fh.write(before)` records as "fh.write", not "write" -- match the attribute.
        self.assertTrue(any(c.split(".")[-1] == "write" for c in called),
                        "the guard never writes: it cannot be putting the snapshot back: %s"
                        % sorted(called))

    def test_an_unchanged_file_is_not_touched(self):
        mv = self._mv()
        # #1203qw: resolve from REPO, not from cwd. The suite runs pytest with cwd=agent/,
        # so the bare relative path raised FileNotFoundError there while passing when
        # run by hand from the repo root.
        target = str(REPO / "scripts" / "mutation_verdicts.py")
        with open(target, "rb") as fh:
            before = fh.read()
        self.assertEqual("", mv._restore_from_snapshot(target, before),
                         "reported a restore for a file that never changed")

    def test_a_missing_snapshot_declines_rather_than_guessing(self):
        mv = self._mv()
        self.assertEqual("", mv._restore_from_snapshot(str(REPO / "scripts" / "mutation_verdicts.py"), None))
        self.assertEqual("", mv._restore_from_snapshot("", b"x"))

    def test_the_guard_sits_in_a_finally(self):
        """It has to run even when the subprocess timed out -- that is the case that leaves
        the mutant behind."""
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(self._mv()))
        in_finally = any(
            "_restore_from_snapshot" in ast.dump(stmt)
            for n in ast.walk(tree) if isinstance(n, ast.Try)
            for stmt in n.finalbody)
        self.assertTrue(in_finally,
                        "the restore is not called from a finally: a timeout would skip it")


if __name__ == "__main__":
    unittest.main()
