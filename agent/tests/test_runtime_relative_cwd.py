"""PR2.2 / Loop B ⑫: ``_compute_relative_cwd`` must not leak host
paths.

``PathRoutedWorkspace.relative()`` returns ``str(ap)`` — the absolute
path — when the path resolves outside both ``code_root`` and
``base_root`` (path_routed_workspace.py:528). The original
``_relative_cwd`` wrapped that in ``./``, producing ``./<host-abspath>``
which ``_scrub_output`` couldn't catch (different prefix). This file
pins:

  1. Workspace-relative paths come back as ``./<rel>``.
  2. Out-of-root paths come back as the sentinel
     ``./ (workspace root)`` — host prefix never surfaces.
  3. ``ExecuteBashTool`` and ``RunBackgroundTool`` route through the
     same helper (dedup invariant from Loop B ⑫ + reviewer ⑤).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ComputeRelativeCwdTests(unittest.TestCase):
    def setUp(self):
        from tools.runtime_tools import _compute_relative_cwd
        self._fn = _compute_relative_cwd

    def test_workspace_relative_returns_dot_prefixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sub = root / "app" / "backend"
            sub.mkdir(parents=True)
            ws = SimpleNamespace(relative=lambda p: str(Path(p).resolve().relative_to(root)))
            self.assertEqual(self._fn(ws, sub), "./app/backend")

    def test_out_of_root_returns_sentinel_not_abspath(self):
        """The exact Loop B ⑫ case: ``relative()`` returns the
        absolute path. Helper must NOT pass that through as
        ``./<abspath>`` — substitute the safe sentinel instead."""
        outside = Path("/tmp/some-other-place").resolve()
        # Simulate the real PathRoutedWorkspace.relative() out-of-root
        # behavior: returns str(ap) when neither code_root nor base_root
        # contains the path.
        ws = SimpleNamespace(relative=lambda p: str(Path(p).resolve()))
        result = self._fn(ws, outside)
        self.assertEqual(result, "./ (workspace root)")
        # Critically, the host path must NOT appear in the result.
        self.assertNotIn(str(outside), result)

    def test_root_itself_returns_workspace_root_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            ws = SimpleNamespace(relative=lambda p: str(Path(p).resolve().relative_to(root)))
            self.assertEqual(self._fn(ws, root), "./ (workspace root)")

    def test_no_relative_method_fallback_uses_code_root(self):
        """Plain WorkspaceManager (test stubs) doesn't expose
        ``relative()`` — fall back to a direct relative_to."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            sub = root / "x" / "y"
            sub.mkdir(parents=True)
            ws = SimpleNamespace(code_root=str(root), base_root=str(root))
            self.assertEqual(self._fn(ws, sub), "./x/y")

    def test_relative_method_exception_returns_sentinel(self):
        """Any failure path → safe sentinel; never an exception or
        partial host path."""
        ws = SimpleNamespace(relative=lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertEqual(self._fn(ws, Path("/tmp/anywhere")), "./ (workspace root)")


class BashToolsShareTheSameHelper(unittest.TestCase):
    """Loop B ⑫ + reviewer ⑤ dedup invariant: ExecuteBashTool's
    ``_relative_cwd`` and RunBackgroundTool's open-coded path must both
    route through ``_compute_relative_cwd`` so the abspath-fallback
    fires in BOTH bash sites — not just one."""

    def test_execute_bash_tool_delegates(self):
        """``ExecuteBashTool._relative_cwd`` is a thin wrapper that
        passes ``self.workspace`` + ``work_dir`` to the module helper."""
        import tools.runtime_tools as rt_mod
        from tools.runtime_tools import ExecuteBashTool

        captured = {}
        orig = rt_mod._compute_relative_cwd

        def spy(ws, wd):
            captured["called"] = True
            captured["ws"] = ws
            captured["wd"] = wd
            return "./sentinel"

        rt_mod._compute_relative_cwd = spy
        try:
            inst = object.__new__(ExecuteBashTool)
            inst.workspace = SimpleNamespace()
            result = inst._relative_cwd(Path("/anywhere"))
        finally:
            rt_mod._compute_relative_cwd = orig
        self.assertTrue(captured.get("called"))
        self.assertEqual(result, "./sentinel")

    def test_run_background_does_not_open_code_relative_logic(self):
        """No site in runtime_tools.py should open-code the
        ``workspace.relative()`` + ``relative_to(code_root)`` ladder
        anymore. The single source of truth lives in
        ``_compute_relative_cwd``."""
        import tools.runtime_tools as rt_mod
        src = Path(rt_mod.__file__).read_text(encoding="utf-8")
        # The ladder-shape that should ONLY appear inside the helper:
        # an `if hasattr(... , "relative")` followed (within ~10 lines)
        # by `relative_to(`. Count occurrences across the whole file —
        # must be exactly 1 (the helper itself).
        ladder_signature = 'hasattr(workspace, "relative")'
        # The helper uses the workspace param; tool methods use
        # self.workspace. If the open-coded version returned, it
        # would use `self.workspace` — count those instead.
        open_coded_signature = 'hasattr(self.workspace, "relative")'
        self.assertNotIn(
            open_coded_signature,
            src,
            "RunBackgroundTool used to open-code the relative-cwd "
            "ladder; it must now route through _compute_relative_cwd.",
        )
        # Exactly one helper-level check expected.
        self.assertEqual(
            src.count(ladder_signature), 1,
            f"Expected exactly 1 `{ladder_signature}` (the helper). "
            f"Found {src.count(ladder_signature)}."
        )


if __name__ == "__main__":
    unittest.main()
