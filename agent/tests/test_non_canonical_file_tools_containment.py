"""Adversarial containment tests for non-canonical file tools — Phase 0.2
Fix 4 (reviewer audit required-fix #4).

The non-canonical reference-image tools used to build paths manually
(enumerating ``self.workspace.root.parent``, ``repo_root``, ``Path.cwd()``,
``self.screenshot_lib / raw``, etc.) without going through the contained
``workspace.resolve()`` from fix #3. Effect: an agent that supplied
``source='/etc/passwd'`` got the file copied INTO the workspace (host-secret
exfiltration); an agent that supplied ``project='/tmp'`` got the host
directory enumerated.

This file exercises the closed bypass. Every test here MUST fail before
the fix and pass after it.

Covered offenders:
  * ``CopyReferenceImageTool._resolve_source_image``
  * ``ListReferenceImagesTool._resolve_reference_project``
  * ``ViewImageTool.execute`` (already went through ``_resolve_workspace_path``,
    but kept here as a regression gate).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workspace import Workspace  # noqa: E402
from tools.file_tools import (  # noqa: E402
    CopyReferenceImageTool,
    ListReferenceImagesTool,
    ViewImageTool,
)


class _Fixture(unittest.TestCase):
    """Tmp workspace + tmp screenshot-lib + tmp outside-the-workspace area.

    Layout:
      <tmp>/ws/                  <- Workspace root
      <tmp>/ws/screenshots/      <- legitimate inside-workspace area
      <tmp>/lib/                 <- bundled screenshot library
      <tmp>/lib/proj_a/img.png   <- legitimate library image
      <tmp>/outside/secret.txt   <- exfiltration target (host secret)
    """

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        tmp = Path(self._td.name)
        self.ws_root = tmp / "ws"
        self.ws_root.mkdir()
        (self.ws_root / "screenshots").mkdir()
        (self.ws_root / "screenshots" / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.workspace = Workspace(self.ws_root)

        self.lib = tmp / "lib"
        self.lib.mkdir()
        (self.lib / "proj_a").mkdir()
        (self.lib / "proj_a" / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        self.outside = tmp / "outside"
        self.outside.mkdir()
        (self.outside / "secret.txt").write_text("HOST SECRET")
        # Also place a real PNG outside, in case the copy tool sniffs the
        # extension at any layer.
        (self.outside / "stolen.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    def tearDown(self) -> None:
        self._td.cleanup()


# ---------------------------------------------------------------------------
# CopyReferenceImageTool — _resolve_source_image
# ---------------------------------------------------------------------------


class CopyReferenceImageContainment(_Fixture):

    def _tool(self) -> CopyReferenceImageTool:
        return CopyReferenceImageTool(workspace=self.workspace, screenshot_lib=self.lib)

    # 1
    def test_copy_reference_image_rejects_etc_passwd(self):
        """Absolute /etc/passwd MUST NOT be readable as a source. The
        bypass we are closing: prior code returned ``Path('/etc/passwd')``
        from the candidate list because ``self.screenshot_lib / '/etc/passwd'``
        collapses to ``/etc/passwd``.
        """
        tool = self._tool()
        result = tool.execute(source="/etc/passwd", destination="screenshots/leak.txt")
        self.assertFalse(result.success, f"expected failure, got {result}")
        # And critically: nothing landed in the workspace.
        self.assertFalse(
            (self.ws_root / "screenshots" / "leak.txt").exists(),
            "host file MUST NOT have been copied into workspace",
        )

    # 2
    def test_copy_reference_image_rejects_dotdot_escape(self):
        """``../outside/stolen.png`` traverses out of the workspace and
        out of the screenshot library. Must be rejected; no file
        materialises in the workspace.
        """
        tool = self._tool()
        result = tool.execute(
            source="../outside/stolen.png",
            destination="screenshots/stolen.png",
        )
        # Either resolve() raised or _resolve_source_image returned the
        # sentinel non-existent path. Either way: tool reports failure
        # and no destination is created.
        self.assertFalse(result.success, f"expected failure, got {result}")
        self.assertFalse(
            (self.ws_root / "screenshots" / "stolen.png").exists(),
            "outside-workspace file MUST NOT be readable",
        )

    # 3
    def test_copy_reference_image_rejects_absolute_outside(self):
        """Absolute path to the explicit ``outside/secret.txt`` host file.
        Same defense as #1 but with a freshly-created tmp target, so the
        test is robust regardless of /etc/passwd readability.
        """
        tool = self._tool()
        result = tool.execute(
            source=str(self.outside / "secret.txt"),
            destination="screenshots/secret.txt",
        )
        self.assertFalse(result.success, f"expected failure, got {result}")
        self.assertFalse(
            (self.ws_root / "screenshots" / "secret.txt").exists(),
            "outside-workspace file MUST NOT be copied into workspace",
        )

    # 4
    def test_copy_reference_image_accepts_legit_path_inside_workspace(self):
        """The legitimate path: an image already inside the workspace
        gets copied to a new workspace location. This must still work
        AFTER the fix — the lockdown must not break valid use.
        """
        tool = self._tool()
        result = tool.execute(
            source="screenshots/ref.png",
            destination="screenshots/ref_copy.png",
        )
        self.assertTrue(result.success, f"expected success, got {result}")
        self.assertTrue((self.ws_root / "screenshots" / "ref_copy.png").exists())

    # 5
    def test_copy_reference_image_accepts_bundled_library_path(self):
        """Legit path: a project-relative reference image from the
        bundled, hard-coded screenshot library copies into the workspace.
        Must still work AFTER the fix — only ``..``/absolute escapes are
        forbidden, the library itself is allowed.
        """
        tool = self._tool()
        result = tool.execute(
            source="proj_a/img.png",
            destination="screenshots/img.png",
        )
        self.assertTrue(result.success, f"expected success, got {result}")
        self.assertTrue((self.ws_root / "screenshots" / "img.png").exists())


# ---------------------------------------------------------------------------
# ListReferenceImagesTool — _resolve_reference_project
# ---------------------------------------------------------------------------


class ListReferenceImagesContainment(_Fixture):

    def _tool(self) -> ListReferenceImagesTool:
        return ListReferenceImagesTool(workspace=self.workspace, screenshot_lib=self.lib)

    # 6
    def test_list_reference_images_rejects_arbitrary_dir(self):
        """Absolute path to the outside directory MUST NOT list its
        contents. Prior code enumerated ``Path.cwd().parent / raw`` etc.
        and would happily return the resolved outside path.
        """
        tool = self._tool()
        result = tool.execute(project=str(self.outside))
        # Either we get a clear failure, OR the project simply isn't
        # found in the bundled library — either way, the secret.txt
        # directory must NOT appear in the output.
        if result.success:
            data = result.data or {}
            for entry in (data.get("projects") or {}).values():
                names = [img.get("name") for img in entry]
                self.assertNotIn(
                    "secret.txt",
                    names,
                    "outside-workspace dir contents MUST NOT be listed",
                )
                self.assertNotIn(
                    "stolen.png",
                    names,
                    "outside-workspace dir contents MUST NOT be listed",
                )
            # And the source attribution (if present) must not point outside.
            src = str(data.get("source") or "")
            self.assertNotIn(
                str(self.outside),
                src,
                f"source MUST NOT be the outside dir; got {src!r}",
            )
        else:
            # explicit rejection is acceptable
            self.assertFalse(result.success)

    # 7
    def test_list_reference_images_rejects_dotdot_escape(self):
        """``../outside`` MUST NOT be listable as a project."""
        tool = self._tool()
        result = tool.execute(project="../outside")
        if result.success:
            data = result.data or {}
            src = str(data.get("source") or "")
            self.assertNotIn(str(self.outside), src)
            for entry in (data.get("projects") or {}).values():
                names = [img.get("name") for img in entry]
                self.assertNotIn("stolen.png", names)
                self.assertNotIn("secret.txt", names)
        else:
            self.assertFalse(result.success)

    # 8
    def test_list_reference_images_accepts_legit_workspace_dir(self):
        """``screenshots`` is a valid inside-workspace directory and
        must still be listable after the fix.
        """
        tool = self._tool()
        result = tool.execute(project="screenshots")
        self.assertTrue(result.success, f"expected success, got {result}")
        data = result.data or {}
        # The legitimate ``ref.png`` we wrote in setUp() should appear.
        all_names: list[str] = []
        for entry in (data.get("projects") or {}).values():
            all_names.extend(img.get("name") for img in entry)
        self.assertIn("ref.png", all_names)

    # 9
    def test_list_reference_images_ignores_bundled_library_project(self):
        """Design change (regression guard): ``list_reference_images`` now ALWAYS
        lists the current env's staged ``workspace/screenshots`` and IGNORES the
        ``project`` arg — its ``tool_definition`` exposes no parameters. The bundled
        demo library is intentionally NOT surfaced here (surfacing unrelated repos
        confuses agents into viewing the wrong project's screenshots); bundled images
        remain reachable only via the explicit ``copy_reference_image`` tool. This
        is strictly MORE restrictive than the old ``_resolve_reference_project``
        behavior — the containment tests above pass precisely because ``project`` is
        ignored. So ``proj_a/img.png`` must NOT appear; the workspace's own
        ``ref.png`` is what's returned.
        """
        tool = self._tool()
        result = tool.execute(project="proj_a")
        self.assertTrue(result.success, f"expected success, got {result}")
        data = result.data or {}
        all_names: list[str] = []
        for entry in (data.get("projects") or {}).values():
            all_names.extend(img.get("name") for img in entry)
        # the bundled-library image is NOT surfaced by list_reference_images ...
        self.assertNotIn("img.png", all_names)
        # ... only the current env's staged workspace screenshots are listed.
        self.assertIn("ref.png", all_names)


# ---------------------------------------------------------------------------
# ViewImageTool — regression gate (already routed via _resolve_workspace_path)
# ---------------------------------------------------------------------------


class ViewImageContainment(_Fixture):

    def _tool(self) -> ViewImageTool:
        return ViewImageTool(workspace=self.workspace)

    # 10
    def test_view_image_rejects_outside_workspace(self):
        """Absolute path to a host file MUST be rejected — the workspace
        resolver only allows in-workspace files.
        """
        tool = self._tool()
        result = tool.execute(path=str(self.outside / "stolen.png"))
        self.assertFalse(result.success, f"expected failure, got {result}")

    # 11
    def test_view_image_rejects_dotdot_escape(self):
        """``../outside/stolen.png`` must be rejected."""
        tool = self._tool()
        result = tool.execute(path="../outside/stolen.png")
        self.assertFalse(result.success, f"expected failure, got {result}")


if __name__ == "__main__":
    unittest.main()
