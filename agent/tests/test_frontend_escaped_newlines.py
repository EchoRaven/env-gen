"""Literal ``\\n`` at a statement boundary is un-escaped (outlook run-29, 2026-07-01).

The frontend lane emitted ``}\\n\\nexport function CalendarsPage() {`` — a LITERAL
backslash-n between statements. A backslash outside a string is a JS syntax error → vite
build fails → api_smoke docker_up WEDGES (run-29: 6/6 validation attempts + STUCK
escalation; the lane never located the error). Same escaped-character damage family as the
escaped-backtick repair (#15). The repair rewrites ONLY a ``\\n`` run sitting after
``}``/``;`` and before a top-level declaration keyword or comment; a legit ``\\n`` inside a
string (``split('\\n')``, ``"a\\nb"``) is untouched. ENV-AGNOSTIC + LOCAL-ONLY (gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _unescape_statement_boundary_newlines, repair_frontend_escaped_backticks)


def test_run29_stubs_pattern_repaired():
    src = "export function EventsPage() {\n  return <div/>;\n}\\n\\nexport function CalendarsPage() {\n  return <div/>;\n}\n"
    fixed = _unescape_statement_boundary_newlines(src)
    assert "\\n" not in fixed
    assert "}\n\nexport function CalendarsPage() {" in fixed


def test_semicolon_boundary_and_other_keywords():
    for kw in ("export default App;", "import x from 'y';", "const a = 1;",
               "function f() {}", "class C {}", "let z = 2;", "// comment"):
        src = f"const a = 1;\\n{kw}"
        fixed = _unescape_statement_boundary_newlines(src)
        assert "\\n" not in fixed, (kw, fixed)


def test_legit_escaped_newlines_in_strings_untouched():
    for src in ("const parts = text.split('\\n');",
                'const s = "line1\\nline2";',
                "const re = /\\n+/g;",
                "console.log('a\\nb');"):
        assert _unescape_statement_boundary_newlines(src) == src, src


def test_boundary_followed_by_non_keyword_untouched():
    # `};\n` + something that is NOT a declaration keyword stays as-is (e.g. inside a string)
    src = 'const s = "x};\\nnotakeyword";'
    assert _unescape_statement_boundary_newlines(src) == src


def test_idempotent():
    src = "}\\n\\nexport function A() {}"
    once = _unescape_statement_boundary_newlines(src)
    assert _unescape_statement_boundary_newlines(once) == once


def test_repair_walk_rewrites_file(tmp_path):
    src_dir = tmp_path / "src" / "pages"
    src_dir.mkdir(parents=True)
    f = src_dir / "Stubs.jsx"
    f.write_text("export function A() {\n  return 1;\n}\\n\\nexport function B() {\n  return 2;\n}\n",
                 encoding="utf-8")
    out = repair_frontend_escaped_backticks(tmp_path)
    assert "pages/Stubs.jsx" in (out.get("repaired") or []), out
    txt = f.read_text(encoding="utf-8")
    assert "\\n" not in txt and "}\n\nexport function B()" in txt


def test_repair_walk_skips_clean_file(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    f = src_dir / "ok.jsx"
    body = "const parts = text.split('\\n');\nexport default parts;\n"
    f.write_text(body, encoding="utf-8")
    out = repair_frontend_escaped_backticks(tmp_path)
    assert not out.get("repaired"), out
    assert f.read_text(encoding="utf-8") == body


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---- third shape (run-36): literal \n INSIDE a template-literal ${...} expression ----

def test_run36_template_expr_newline_repaired():
    from multi_agent.runtime.frontend_scaffold import _unescape_template_expr_newlines
    line = ("<button className={`w-full flex ${" + "\\n"
            + "  selected === id ? 'bg-a' : 'bg-b'" + "\\n" + "}`}>x</button>")
    fixed = _unescape_template_expr_newlines(line)
    assert "\\n" not in fixed                      # all literal \n un-escaped
    assert "${\n" in fixed and "'bg-a'" in fixed    # real newline after ${, strings intact


def test_quoted_backslash_n_preserved_on_trigger_line():
    from multi_agent.runtime.frontend_scaffold import _unescape_template_expr_newlines
    line = ("<div className={`${" + "\\n" + " x.split('\\n').length " + "\\n"
            + "}`}>y</div>")
    fixed = _unescape_template_expr_newlines(line)
    assert "split('\\n')" in fixed                 # quoted \n is data — preserved
    assert fixed.count("\\n") == 1                 # only the quoted one remains


def test_non_trigger_lines_untouched():
    from multi_agent.runtime.frontend_scaffold import _unescape_template_expr_newlines
    body = "const parts = text.split('\\n');\nconst s = \"a\\nb\";"
    assert _unescape_template_expr_newlines(body) == body
