"""#1085 — postcss.config.js and eslint.config.js are read by their tool, not imported.

`_ENTRY_POINT_BASENAMES` already encodes the policy: `vite.config.ts`, `vite.config.js`,
`next.config.js` and `tailwind.config.js` are exempt from the dead-file scan because nothing
imports a build config — the toolchain discovers it BY NAME. The list simply never grew.
`postcss.config.js` is the inseparable sibling of the exempt `tailwind.config.js` in the very
same Tailwind setup, and it is flagged dead in 67 of 83 generated apps; `eslint.config.js` in
61. Together that is 128 of the 798 dead-file findings left after #1084, every one of them
false — deleting either file, which is what "dead artifact" asks for, breaks the build.

Enumerating two more names would leave the next tool's config to be discovered the same way,
so the rule is structural instead: a `*.config.{js,cjs,mjs,ts}` file is a tool's config. That
matches the four entries already in the list (they can stay, harmlessly) and covers jest,
vitest, rollup and babel before anyone hits them. Measured on the corpus it removes exactly
those 128 findings and nothing else: `backend/schemas.py` (66, genuinely imported by nobody)
and the unused frontend components are untouched.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.coverage_audit import scan_dead_files  # noqa: E402

_APP_JSX = "export default function App() { return <div>hi</div>; }\n"


def _dead(names) -> set:
    root = Path(mkdtemp())
    fe = root / "frontend" / "src"
    fe.mkdir(parents=True)
    (fe / "App.jsx").write_text(_APP_JSX, encoding="utf-8")
    for n in names:
        p = root / "frontend" / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("export default {};\n", encoding="utf-8")
    return {d["path"] for d in scan_dead_files(root)}


class TheTwoTheCorpusFlags(unittest.TestCase):

    def test_postcss_and_eslint_configs_are_not_dead(self):
        dead = _dead(["postcss.config.js", "eslint.config.js"])
        self.assertNotIn("frontend/postcss.config.js", dead)
        self.assertNotIn("frontend/eslint.config.js", dead)


class TheRuleIsStructural(unittest.TestCase):

    def test_the_already_exempt_ones_stay_exempt(self):
        dead = _dead(["vite.config.js", "tailwind.config.js", "next.config.js"])
        self.assertEqual(dead & {"frontend/vite.config.js", "frontend/tailwind.config.js",
                                 "frontend/next.config.js"}, set())

    def test_a_tool_nobody_has_hit_yet_is_covered(self):
        dead = _dead(["jest.config.ts", "rollup.config.mjs", "babel.config.cjs",
                      "vitest.config.ts"])
        self.assertEqual(dead & {"frontend/jest.config.ts", "frontend/rollup.config.mjs",
                                 "frontend/babel.config.cjs", "frontend/vitest.config.ts"},
                         set())


class RealDeadCodeIsUntouched(unittest.TestCase):

    def test_an_unimported_component_is_still_dead(self):
        dead = _dead(["src/components/Orphan.jsx"])
        self.assertIn("frontend/src/components/Orphan.jsx", dead)

    def test_a_plainly_named_source_file_is_not_exempted(self):
        """`config.js` is a module people import; only `<tool>.config.<ext>` is discovered."""
        dead = _dead(["src/config.js"])
        self.assertIn("frontend/src/config.js", dead)


if __name__ == "__main__":
    unittest.main()
