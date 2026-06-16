"""Smoke tests for vision_tools (Cutover 18)."""

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class VisionToolsClassAttributesTests(unittest.TestCase):
    def test_extract_components_has_class_level_NAME(self) -> None:
        from tools.vision_tools import ExtractComponentsTool
        self.assertEqual(ExtractComponentsTool.NAME, "extract_components")

    def test_compare_with_screenshot_inits_jinja(self) -> None:
        from tools.vision_tools import CompareWithScreenshotTool
        from workspace import Workspace
        tmp = Path(tempfile.mkdtemp(prefix="vision_jinja_"))
        try:
            tool = CompareWithScreenshotTool(workspace=Workspace(tmp))
            # _jinja must be initialized at construction (None placeholder)
            self.assertTrue(hasattr(tool, "_jinja"))
            self.assertIsNone(tool._jinja)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class VisionToolsMissingFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="vision_smoke_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_analyze_image_handles_missing_file_gracefully(self) -> None:
        from tools.vision_tools import AnalyzeImageTool
        from workspace import Workspace
        # Pass a dummy llm_client so the tool reaches the file-resolution path
        # (without it, the tool short-circuits on missing-LLM before checking
        # the file, masking the real missing-file behavior we want to verify).
        tool = AnalyzeImageTool(llm_client=object(), workspace=Workspace(self.tmp))
        result = _run_async(tool.execute(image_path="does/not/exist.png"))
        self.assertFalse(result.success)
        err = (result.error_message or "").lower()
        # Tool reports "could not read image: <path>" when resolution fails.
        self.assertTrue(
            "could not read" in err or "not found" in err or "cannot read" in err,
            f"expected file-rejection error, got: {result.error_message!r}",
        )


if __name__ == "__main__":
    unittest.main()
