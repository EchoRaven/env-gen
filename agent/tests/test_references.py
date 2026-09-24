import base64
import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))


class TestReferences(unittest.TestCase):
    def setUp(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from live_monitor_server import create_project_call
        self.project_id = create_project_call(self.root, {"name": "refs-test"})["id"]
        self.workspace = self.root / self.project_id

    def tearDown(self):
        from live_monitor_server import _HUB_REGISTRY_CACHE, _SSE_HUB_CACHE
        _HUB_REGISTRY_CACHE.clear()
        _SSE_HUB_CACHE.clear()
        self._tmp.cleanup()

    def _b64(self, raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    def test_list_references_empty(self):
        from live_monitor_server import list_references_call
        result = list_references_call(self.root, self.project_id)
        self.assertEqual(result, {"files": []})

    def test_upload_text_file_saves_and_lists(self):
        from live_monitor_server import upload_reference_call, list_references_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "spec.md",
            "content_base64": self._b64(b"# Design Spec\n\nHello world\n"),
        })
        self.assertNotIn("error", result, result)
        self.assertEqual(result["name"], "spec.md")
        self.assertEqual(result["category"], "doc")
        listed = list_references_call(self.root, self.project_id)["files"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "spec.md")
        self.assertIn("preview", listed[0])
        self.assertIn("Design Spec", listed[0]["preview"])

    def test_upload_python_categorized_as_python(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "mcp_server.py",
            "content_base64": self._b64(b"def hello(): return 'world'\n"),
        })
        self.assertEqual(result["category"], "python")

    def test_upload_image_categorized_as_image(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "screenshot.png",
            "content_base64": self._b64(b"\x89PNG\r\n\x1a\nfake-png-bytes"),
        })
        self.assertEqual(result["category"], "image")

    def test_upload_yaml_categorized_as_spec(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "openapi.yaml",
            "content_base64": self._b64(b"openapi: 3.0.0\n"),
        })
        self.assertEqual(result["category"], "spec")

    def test_upload_rejects_path_traversal(self):
        from live_monitor_server import upload_reference_call
        for bad in ["../escape.txt", "subdir/file.txt", "/absolute.txt"]:
            result = upload_reference_call(self.root, self.project_id, {
                "filename": bad,
                "content_base64": self._b64(b"x"),
            })
            self.assertIn("error", result, f"Should reject {bad}: {result}")

    def test_upload_rejects_empty_filename(self):
        from live_monitor_server import upload_reference_call
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "  ",
            "content_base64": self._b64(b"x"),
        })
        self.assertIn("error", result)

    def test_upload_size_cap_enforced(self):
        from live_monitor_server import upload_reference_call
        big = b"x" * (11 * 1024 * 1024)  # 11 MB
        result = upload_reference_call(self.root, self.project_id, {
            "filename": "big.bin",
            "content_base64": self._b64(big),
        })
        self.assertIn("error", result)
        self.assertIn("size", result["error"].lower())

    def test_delete_reference_removes_file(self):
        from live_monitor_server import upload_reference_call, delete_reference_call, list_references_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "to-delete.md", "content_base64": self._b64(b"bye"),
        })
        result = delete_reference_call(self.root, self.project_id, "to-delete.md")
        self.assertNotIn("error", result, result)
        self.assertEqual(list_references_call(self.root, self.project_id)["files"], [])

    def test_delete_unknown_returns_error(self):
        from live_monitor_server import delete_reference_call
        result = delete_reference_call(self.root, self.project_id, "nope.md")
        self.assertIn("error", result)

    def test_upload_regenerates_index_md(self):
        from live_monitor_server import upload_reference_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "a.md", "content_base64": self._b64(b"file a"),
        })
        upload_reference_call(self.root, self.project_id, {
            "filename": "b.py", "content_base64": self._b64(b"# file b\n"),
        })
        index = self.workspace / "references" / "INDEX.md"
        self.assertTrue(index.exists())
        content = index.read_text()
        self.assertIn("a.md", content)
        self.assertIn("b.py", content)
        self.assertIn("python", content)
        self.assertIn("doc", content)

    def test_delete_regenerates_index_md(self):
        from live_monitor_server import upload_reference_call, delete_reference_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "x.md", "content_base64": self._b64(b"x"),
        })
        delete_reference_call(self.root, self.project_id, "x.md")
        index = self.workspace / "references" / "INDEX.md"
        # INDEX.md still exists but is empty (or notes "no references")
        if index.exists():
            content = index.read_text()
            self.assertNotIn("x.md", content)

    def test_overwrite_existing_filename(self):
        from live_monitor_server import upload_reference_call, list_references_call
        upload_reference_call(self.root, self.project_id, {
            "filename": "spec.md", "content_base64": self._b64(b"v1 content"),
        })
        upload_reference_call(self.root, self.project_id, {
            "filename": "spec.md", "content_base64": self._b64(b"v2 content"),
        })
        files = list_references_call(self.root, self.project_id)["files"]
        self.assertEqual(len(files), 1)
        self.assertIn("v2", files[0]["preview"])


if __name__ == "__main__":
    unittest.main()
