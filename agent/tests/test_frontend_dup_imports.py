"""Guard: FIX #190 — dedupe colliding frontend import bindings at heal time.

§3-6 (gmrun3/5/7/8/11 + tiktok-r1): heal/codegen re-emits an import that already
exists → esbuild "Identifier 'api' has already been declared" → npm build fails
→ docker_up wedges (recovers sometimes, aborts other times — nondeterministic).
Conservative text surgery, parse-level only:
 - an import line whose EVERY introduced binding is already bound → dropped
   (exact duplicate lines are the common case);
 - a pure-named import line with SOME collisions → collided names removed;
 - anything trickier (mixed default+named partial collision) → left alone,
   reported in `conflicts` for the log (never guess semantics).
"""

import sys
import tempfile
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    dedupe_import_bindings, repair_frontend_duplicate_imports,
)


class DedupeImportBindingsTests(unittest.TestCase):
    def test_exact_duplicate_line_dropped(self):
        src = ("import api from '../services/api';\n"
               "import React from 'react';\n"
               "import api from '../services/api';\n"
               "export default function A() { return null; }\n")
        out, changed, conflicts = dedupe_import_bindings(src)
        self.assertTrue(changed)
        self.assertEqual(out.count("import api from"), 1)
        self.assertEqual(conflicts, [])

    def test_same_default_binding_different_source_dropped(self):
        src = ("import api from './api';\n"
               "import api from '../lib/api';\n")
        out, changed, _ = dedupe_import_bindings(src)
        self.assertTrue(changed)
        self.assertEqual(out.count("import api"), 1)
        self.assertIn("./api", out)          # first wins
        self.assertNotIn("../lib/api", out)

    def test_named_partial_collision_rewritten(self):
        src = ("import { Home, User } from 'lucide-react';\n"
               "import { User, Bell } from 'lucide-react';\n")
        out, changed, _ = dedupe_import_bindings(src)
        self.assertTrue(changed)
        # second line keeps only the new binding
        self.assertIn("Bell", out)
        self.assertEqual(out.count("User"), 1)

    def test_alias_counts_as_the_binding(self):
        src = ("import { Inbox as InboxIcon } from 'lucide-react';\n"
               "import { Mail as InboxIcon } from 'lucide-react';\n")
        out, changed, _ = dedupe_import_bindings(src)
        self.assertTrue(changed)
        self.assertEqual(out.count("InboxIcon"), 1)

    def test_mixed_default_plus_named_partial_left_alone(self):
        src = ("import React from 'react';\n"
               "import React, { useState } from 'react';\n")
        out, changed, conflicts = dedupe_import_bindings(src)
        # default collides but named part is new — too tricky, report only
        self.assertIn("useState", out)
        self.assertTrue(conflicts)

    def test_no_collisions_untouched(self):
        src = ("import React from 'react';\n"
               "import { useState } from 'react';\n"
               "const x = 1;\n")
        out, changed, conflicts = dedupe_import_bindings(src)
        self.assertFalse(changed)
        self.assertEqual(out, src)
        self.assertEqual(conflicts, [])

    def test_namespace_import_collision_dropped(self):
        src = ("import * as api from './api';\n"
               "import * as api from './api';\n")
        out, changed, _ = dedupe_import_bindings(src)
        self.assertTrue(changed)
        self.assertEqual(out.count("import * as api"), 1)


class RepairDirTests(unittest.TestCase):
    def test_repairs_files_under_src_and_reports(self):
        d = Path(tempfile.mkdtemp())
        (d / "src").mkdir(parents=True)
        f = d / "src" / "LoginPage.jsx"
        f.write_text("import api from './api';\nimport api from './api';\n"
                     "export default function LoginPage() { return null; }\n")
        rep = repair_frontend_duplicate_imports(d)
        self.assertTrue(rep["repaired"])
        self.assertEqual(f.read_text().count("import api"), 1)
        rep2 = repair_frontend_duplicate_imports(d)
        self.assertFalse(rep2.get("repaired"))  # idempotent

    def test_missing_dir_graceful(self):
        rep = repair_frontend_duplicate_imports(Path(tempfile.mkdtemp()) / "nope")
        self.assertFalse(rep.get("repaired"))


if __name__ == "__main__":
    unittest.main()
