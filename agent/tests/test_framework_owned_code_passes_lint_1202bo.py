r"""#1202bo: framework-owned code that fails the framework's own lint gate.

Found by supervising r33. The backend lane reported, and could do nothing about it:

    Backend is blocked on validation lint failure in framework-owned
    app/backend/oauth_store.py (Ruff E702 lines 297-298). Attempted exact edit
    was denied because the file is framework/runtime-owned

    ❌ lint FAILED: L297 [E702] Multiple statements on one line (semicolon);
                    L298 [E702]

Both lines come verbatim from `oauth_as_templates/oauth_store.py.tmpl`, and the same
shape sits in `canonical_rows.ENFORCE_ROUTINE_SRC`, which is emitted into seed_data.py.
The write guard denies lane edits to both files, so no lane can ever clear this — it is
the framework failing its own gate and blocking delivery on it.

This pins the general rule rather than the two lines: no code the framework emits into a
lane-unwritable file may carry a construct the lint gate rejects.
"""
import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_RUNTIME = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime")
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

# `x = ...; y = ...` — E702. Matched on emitted CODE lines only; prose semicolons in
# comments and docstrings are not what Ruff flags.
_E702 = re.compile(r"^\s+[A-Za-z_]\w* *=.*; *[A-Za-z_]\w* *=", re.M)

_EMITTERS = {
    "oauth_as_templates/oauth_store.py.tmpl": "emitted verbatim as app/backend/oauth_store.py",
    "oauth_as_templates/oauth_routes.py.tmpl": "emitted verbatim as app/backend/oauth_routes.py",
    "oauth_as_templates/jwt_manager.py.tmpl": "emitted verbatim as app/backend/jwt_manager.py",
}


class FrameworkOwnedCodePassesLintTests(unittest.TestCase):
    def test_no_emitted_template_carries_e702(self):
        for rel, what in _EMITTERS.items():
            f = _RUNTIME / rel
            if not f.is_file():
                continue
            hits = _E702.findall(f.read_text(encoding="utf-8"))
            self.assertEqual(
                hits, [],
                f"{rel} ({what}) emits a semicolon-joined statement. Ruff flags it E702, "
                f"the file is framework-owned so no lane may edit it, and r33 blocked on "
                f"exactly this: {hits[:2]}")

    def test_the_enforce_routine_source_carries_no_e702(self):
        """Belt-and-braces, and the docstring says why it is only that.

        #1202bo's commit message said this text is "emitted into seed_data.py". It is
        not: measured across the corpus, `_enforce_user_bootstrap_rows` appears in zero
        of 98 seed_data.py files, nothing in the framework references
        ENFORCE_ROUTINE_SRC outside its own module, and no oauth template contains it.
        It has been unreferenced since fix(#72) added it on 2026-07-03. The header
        claiming otherwise misled me first (#1202bq corrects it).

        Kept anyway: if the wiring is ever reconnected, this is already clean.
        """
        from multi_agent.runtime.canonical_rows import ENFORCE_ROUTINE_SRC
        self.assertEqual(_E702.findall(ENFORCE_ROUTINE_SRC), [])

    def test_the_real_emitter_is_the_one_the_corpus_shows(self):
        """The measurement that matters: 118 of 119 delivered artifacts carried the
        E702 shape in oauth_store.py, and only a run built after the fix is clean."""
        tmpl = (_RUNTIME / "oauth_as_templates" / "oauth_store.py.tmpl")
        self.assertTrue(tmpl.is_file())
        self.assertIn("_bootstrap_user_rows", tmpl.read_text(encoding="utf-8"),
                      "the emitter this fix is actually about is not this template")

    def test_the_detector_would_catch_the_r33_line(self):
        """Non-vacuity: the pattern must match the exact line that blocked the run."""
        self.assertTrue(_E702.search(
            '                t = s.get("table"); owner = s.get("owner_col")\n'))

    def test_prose_semicolons_are_not_flagged(self):
        """Docstrings say things like 'a single path; ensure_schema here is...'."""
        self.assertEqual(_E702.findall(
            "    # allow explicit injection; when omitted it is resolved\n"
            '    """Prefers DATABASE_URL (what the backend uses); falls back to..."""\n'), [])


if __name__ == "__main__":
    unittest.main()
