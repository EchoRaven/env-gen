"""#1081 — two invalid escape sequences in the package, and a ratchet so there are never more.

`repair_frontend_escaped_backticks`'s docstring documents the shapes it repairs:

    ``className={\`...\`}`` / ``className=\"...\"``

In a non-raw string `\`` is not an escape at all — Python emits
``DeprecationWarning: invalid escape sequence '\`'`` today and this becomes a SyntaxError in
a future version, in the framework's own source. Its neighbour `\"` IS a valid escape, which
is worse in a quieter way: it renders as a bare `"`, so the docstring shows
``className="..."`` — the UNescaped form, the opposite of the shape the function exists to
find. Making the docstring raw fixes both: the warning goes away and line two finally reads
the way line one always did.

Measured first, because the same warning appears in the suite from `<unknown>:65` — a
`compile()` on a STRING, which would be far more serious if the string were framework-emitted
app code. It is not: rendering `render_skeleton_main` (1079 lines), `render_models` and
`render_seed_data` and compiling each yields ZERO invalid escapes. The `<unknown>` warning is
a test fixture compiling its own source, not generated code.

The ratchet is the durable half: 2 sites is small, the class is not — every `"\d"`, `"\s"`,
`"\("` written outside an r-string is a future SyntaxError, and none of them fail a test today.
"""
from __future__ import annotations

import py_compile
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PKG = ROOT / "env_generator" / "llm_generator"


def _invalid_escapes():
    out = []
    tmp = tempfile.mkdtemp()
    for f in sorted(PKG.rglob("*.py")):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                py_compile.compile(str(f), cfile=f"{tmp}/x.pyc", doraise=False)
            except Exception:
                continue
            for w in caught:
                if "invalid escape sequence" in str(w.message):
                    out.append(f"{f.relative_to(PKG)}:{w.lineno} {w.message}")
    return out


class ThePackageHasNone(unittest.TestCase):

    def test_no_module_carries_an_invalid_escape_sequence(self):
        found = _invalid_escapes()
        self.assertEqual(found, [], "\n".join(found))


class TheDocstringShowsTheEscapedShapes(unittest.TestCase):
    """Both lines must display the ESCAPED form — that is what the function looks for."""

    def test_both_shapes_survive_into_the_doc(self):
        from multi_agent.runtime.frontend_scaffold import repair_frontend_escaped_backticks
        doc = repair_frontend_escaped_backticks.__doc__ or ""
        self.assertIn("\\`", doc)
        self.assertIn('\\"', doc, "the \\\" pair still collapses to a bare quote")


class GeneratedPythonIsClean(unittest.TestCase):
    """The measurement that kept this in proportion — pinned so it stays true."""

    def test_the_rendered_backend_compiles_without_escape_warnings(self):
        from multi_agent.runtime.backend_skeleton import (render_models, render_seed_data,
                                                          render_skeleton_main)
        tables = {"videos": {"columns": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "title", "type": "text"}]}}
        eps = [{"method": "GET", "path": "/api/videos"},
               {"method": "GET", "path": "/api/videos/{id}"}]
        for label, src in (("main", render_skeleton_main(eps, tables)),
                           ("models", render_models(tables)),
                           ("seed_data", render_seed_data(tables))):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                compile(src, f"<{label}>", "exec")
            bad = [str(w.message) for w in caught if "invalid escape" in str(w.message)]
            self.assertEqual(bad, [], f"{label}: {bad}")


if __name__ == "__main__":
    unittest.main()
