"""#1088 — the gate asked the lane to delete files the framework rewrites every cycle.

`backend/schemas.py` is written by `backend_skeleton` on every scaffold (``w()`` is an
unconditional ``write_text``), and its own first line says what it is:

    \"\"\"Framework-generated placeholder. The projected handlers return plain dicts;
    Pydantic response models are not required for the standard-CRUD skeleton.\"\"\"

Nothing imports it — the projected handlers return dicts, exactly as the docstring says — so
`scan_dead_files` reports it in **66 of 83** generated apps, the single largest entry left
after #1084/#1085. The remediation then tells the lane to "remove or wire up the dead
artifacts": removing is futile (the next scaffold writes it back) and wiring a schemas module
the framework itself calls unnecessary is make-work. That is #201's wall — *"a FRAMEWORK stub
is regenerated every cycle, so the remedy is non-actionable and it walls forever"* — for a
file the framework creates and declares.

The same is true of every projected frontend stub, whose header states it outright:

    // framework-generated page (frontend_page_projector) — edits are overwritten

Measured over the corpus, 315 of the 670 remaining dead files declare framework authorship in
their header, and the exemption cannot hide lane work: **311 of those 315 are ≤10 lines** —
untouched stubs — 3 are projected pages and exactly one is over 60 lines (r81's 63-line
reference-structured FYPFeed.jsx, also framework-written; it is the page #1080 fixed).

The marker is read from the HEADER only. A lane file that happens to mention the phrase
further down is not exempt — the #222 lesson (a lane that strips or copies markers) cuts both
ways, and liveness is decided by the import graph for everything the lane owns.
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

_SCHEMAS = ('"""Framework-generated placeholder. The projected handlers return plain dicts;\n'
            'Pydantic response models are not required for the standard-CRUD skeleton."""\n')
_PROJECTED_PAGE = ("// framework-generated page (frontend_page_projector) — edits are overwritten\n"
                   "export default function Orphan() { return <div>x</div>; }\n")
_LANE_ORPHAN = "export default function LaneOrphan() { return <div>x</div>; }\n"


def _dead(files: dict) -> set:
    root = Path(mkdtemp())
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return {d["path"] for d in scan_dead_files(root)}


class TheFrameworkOwnsWhatItWrites(unittest.TestCase):

    def test_the_real_schemas_py_is_not_the_lanes_dead_code(self):
        dead = _dead({"backend/main.py": "import models\napp = None\n",
                      "backend/models.py": "class User: pass\n",
                      "backend/schemas.py": _SCHEMAS})
        self.assertNotIn("backend/schemas.py", dead)

    def test_a_projected_page_stub_is_not_either(self):
        dead = _dead({"frontend/src/App.jsx": "export default function App(){return null;}\n",
                      "frontend/src/pages/Orphan.jsx": _PROJECTED_PAGE})
        self.assertNotIn("frontend/src/pages/Orphan.jsx", dead)


class TheLanesOwnOrphansStillRead(unittest.TestCase):

    def test_an_unmarked_orphan_is_still_dead(self):
        dead = _dead({"frontend/src/App.jsx": "export default function App(){return null;}\n",
                      "frontend/src/components/LaneOrphan.jsx": _LANE_ORPHAN})
        self.assertIn("frontend/src/components/LaneOrphan.jsx", dead)

    def test_the_marker_only_counts_in_the_header(self):
        """#222's lesson cuts both ways — a mention buried in a real file exempts nothing."""
        body = ("export default function Big() {\n"
                + "  // filler\n" * 60
                + "  // framework-generated page — edits are overwritten\n"
                + "  return null;\n}\n")
        dead = _dead({"frontend/src/App.jsx": "export default function App(){return null;}\n",
                      "frontend/src/components/Big.jsx": body})
        self.assertIn("frontend/src/components/Big.jsx", dead)

    def test_an_unimported_lane_backend_module_is_still_dead(self):
        dead = _dead({"backend/main.py": "import models\napp = None\n",
                      "backend/models.py": "class User: pass\n",
                      "backend/lane_helper.py": "def helper(): pass\n"})
        self.assertIn("backend/lane_helper.py", dead)


if __name__ == "__main__":
    unittest.main()
