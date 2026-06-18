"""Guard: the frontend finish-gate blocks a WRONG-ROOT app, passes a correct one.

Run #5: the frontend authored its pages via execute_bash heredocs to repo-root
./src (bash bypasses the write-tool path routing), so app/frontend/src stayed a
blank shell and most pages were untracked → the delivered frontend would be
hollow, yet finish() succeeded. frontend_canonical_root blocks finish on that
exact mismatch. Tight trigger — a correctly-built app/frontend/ passes, so it
never wedges a real finish. Also pins it's wired into the frontend lane config.
"""

import sys
import types
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.agents.runtime.preconditions import (  # noqa: E402
    frontend_canonical_root, resolve_precondition,
)


def _agent_with_base(base: Path):
    return types.SimpleNamespace(workspace=types.SimpleNamespace(base_dir=base))


def _mk_pages(d: Path, names):
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("export default function X(){return null}\n")


class FrontendCanonicalRootTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fcr_"))

    def test_blocks_wrong_root_richer_than_canonical(self):
        # repo-root ./src/pages rich, canonical app/frontend/src/pages empty → block
        _mk_pages(self.tmp / "src" / "pages", ["Home.jsx", "Watch.jsx", "Search.jsx"])
        (self.tmp / "app" / "frontend" / "src").mkdir(parents=True)
        err = frontend_canonical_root(_agent_with_base(self.tmp), "finish", {})
        self.assertIsNotNone(err)
        self.assertIn("finish blocked", err)
        self.assertIn("app/frontend/src", err)
        self.assertIn("execute_bash", err)  # names the actual root-cause habit

    def test_passes_correct_canonical_app(self):
        # pages live under app/frontend/src/pages, no repo-root tree → pass (no wedge)
        _mk_pages(self.tmp / "app" / "frontend" / "src" / "pages", ["Home.jsx", "Watch.jsx", "Search.jsx"])
        self.assertIsNone(frontend_canonical_root(_agent_with_base(self.tmp), "finish", {}))

    def test_passes_when_no_pages_anywhere(self):
        # nothing built yet → vacuously passes (a different gate handles 'nothing built')
        (self.tmp / "app" / "frontend" / "src").mkdir(parents=True)
        self.assertIsNone(frontend_canonical_root(_agent_with_base(self.tmp), "finish", {}))

    def test_passes_single_stray_page(self):
        # one stray page is below the >=2 threshold → no block (avoids noise)
        _mk_pages(self.tmp / "src" / "pages", ["Stray.jsx"])
        self.assertIsNone(frontend_canonical_root(_agent_with_base(self.tmp), "finish", {}))

    def test_no_workspace_is_noop(self):
        self.assertIsNone(frontend_canonical_root(types.SimpleNamespace(), "finish", {}))

    def test_registered_in_registry(self):
        self.assertIs(resolve_precondition("frontend_canonical_root"), frontend_canonical_root)


if __name__ == "__main__":
    unittest.main()
