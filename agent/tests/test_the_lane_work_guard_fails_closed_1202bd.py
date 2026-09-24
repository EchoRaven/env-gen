r"""#1202bd: the guard against clobbering lane work must not fail open.

`framework_may_write` exists (#1011) to stop the framework overwriting a file the lane
already wrote. Its own docstring measures what happens when it doesn't: the framework
"deleted the frontend's componentised LoginPage 46 times in r164 while the lane kept
rewriting it".

The last handler answered "I could not read this lane-owned path" with `return True` —
go ahead and overwrite. The two directions are not symmetric:

    refuse   one tick lost; the projection runs again every tick anyway
    allow    the lane's work is gone — netflix-r32's 138-line GenresPage survives in
             neither worktree nor any branch

The narrowness of #1011 must survive this change, so the first three tests pin the
cases that must still be allowed.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace  # noqa: E402


class LaneWorkGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="bd1202_"))
        (self.root / "app" / "frontend" / "src" / "pages").mkdir(parents=True)
        self.ws = PathRoutedWorkspace(base_root=self.root, code_root=self.root,
                                      agent_id="frontend")
        self.page = self.root / "app" / "frontend" / "src" / "pages" / "LoginPage.jsx"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_missing_file_is_still_writable(self):
        """First-run scaffolding must keep working — #1011 is deliberately narrow."""
        self.assertTrue(self.ws.framework_may_write(self.page))

    def test_an_empty_file_is_still_writable(self):
        """A file the lane emptied is repairable, by design."""
        self.page.write_text("")
        self.assertTrue(self.ws.framework_may_write(self.page))

    def test_existing_lane_work_is_still_refused(self):
        self.page.write_text("export default function LoginPage() { return <Form/>; }\n")
        self.assertFalse(self.ws.framework_may_write(self.page))

    def test_an_unreadable_lane_owned_path_is_refused_not_allowed(self):
        """The fix: 'I cannot tell' must not mean 'overwrite it'."""
        self.page.write_text("lane work\n")
        with mock.patch.object(Path, "stat", side_effect=OSError("stat failed")):
            self.assertFalse(
                self.ws.framework_may_write(self.page),
                "an unreadable lane-owned path is still treated as free to clobber")


if __name__ == "__main__":
    unittest.main()
