"""Guard: FIX #194 — remove BYTE-IDENTICAL duplicate top-level declarations.

§3-6 second half (gmrun3/5/7/8/11 + tiktok-r1): heal/codegen re-emits a whole
component/const that already exists → esbuild "X already declared" → build FAIL
→ docker_up wedge. The safe subset is deterministic: when two top-level
declarations of the SAME name have IDENTICAL (whitespace-normalized) bodies,
delete the later copy. Different bodies are NEVER guessed — kept + reported
(the lane owns semantics). Extraction is string/template/comment-aware; the
identical-span requirement self-guards against extraction error (a wrong span
practically never matches the first copy byte-for-byte).
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    dedupe_identical_toplevel_blocks, repair_frontend_duplicate_declarations,
)

_COMPONENT = """export default function LoginPage() {
  const [email, setEmail] = useState('');
  return (
    <div className={`login ${email ? 'filled' : ''}`}>
      <span>{'literal } brace'}</span>
    </div>
  );
}
"""

_ARROW = """const api = (path) => {
  return fetch(`/api${path}`, { headers: { 'X': '}' } });
};
"""


class DedupeBlocksTests(unittest.TestCase):
    def test_identical_function_dup_removed(self):
        src = _COMPONENT + "\nconst x = 1;\n\n" + _COMPONENT
        out, removed, conflicts = dedupe_identical_toplevel_blocks(src)
        self.assertEqual(removed, ["LoginPage"])
        self.assertEqual(conflicts, [])
        self.assertEqual(out.count("function LoginPage"), 1)
        self.assertIn("const x = 1;", out)

    def test_identical_arrow_const_dup_removed(self):
        src = _ARROW + "\n" + _ARROW
        out, removed, conflicts = dedupe_identical_toplevel_blocks(src)
        self.assertEqual(removed, ["api"])
        self.assertEqual(out.count("const api"), 1)

    def test_different_bodies_kept_and_reported(self):
        other = _COMPONENT.replace("filled", "changed")
        src = _COMPONENT + "\n" + other
        out, removed, conflicts = dedupe_identical_toplevel_blocks(src)
        self.assertEqual(removed, [])
        self.assertEqual(len(conflicts), 1)
        self.assertIn("LoginPage", conflicts[0])
        self.assertEqual(out, src)  # untouched

    def test_braces_in_strings_and_templates_survive(self):
        # the kept copy must be intact — no truncation at a string-brace
        src = _COMPONENT + "\n" + _COMPONENT
        out, removed, _ = dedupe_identical_toplevel_blocks(src)
        self.assertEqual(removed, ["LoginPage"])
        self.assertIn("literal } brace", out)
        self.assertIn("${email ? 'filled' : ''}", out)

    def test_clean_file_untouched(self):
        src = _COMPONENT + "\n" + _ARROW
        out, removed, conflicts = dedupe_identical_toplevel_blocks(src)
        self.assertEqual((removed, conflicts), ([], []))
        self.assertEqual(out, src)

    def test_line_comments_with_braces_ok(self):
        block = "function helper() {\n  // ignore } this\n  return 1;\n}\n"
        src = block + "\n" + block
        out, removed, _ = dedupe_identical_toplevel_blocks(src)
        self.assertEqual(removed, ["helper"])
        self.assertEqual(out.count("function helper"), 1)


class RepairDirTests(unittest.TestCase):
    def test_dir_repair_and_idempotency(self):
        d = Path(tempfile.mkdtemp())
        (d / "src").mkdir()
        f = d / "src" / "LoginPage.jsx"
        f.write_text(_COMPONENT + "\n" + _COMPONENT)
        rep = repair_frontend_duplicate_declarations(d)
        self.assertTrue(rep["repaired"])
        self.assertEqual(f.read_text().count("function LoginPage"), 1)
        rep2 = repair_frontend_duplicate_declarations(d)
        self.assertFalse(rep2.get("repaired"))


if __name__ == "__main__":
    unittest.main()
