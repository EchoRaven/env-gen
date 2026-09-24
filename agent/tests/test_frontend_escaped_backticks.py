"""Frontend escaped-backtick repair (outlook run-13, 2026-06-30): the LLM frontend lane
intermittently emits template-literal DELIMITERS as ESCAPED backticks — `className={\\`...\\`}`
instead of `className={`...`}` — which is not valid JSX/JS, so esbuild/Vite fails the transform
→ `npm run build` fails → api_smoke docker_up WEDGES (the lane clears it one file at a time over
many cycles: MessageRow.jsx → FolderList.jsx → Tabs.jsx → InboxPage.jsx). The framework now
un-escapes DELIMITER backticks by construction before every docker_up build.

Proves: every malformed delimiter shape is fixed; a legitimately-escaped backtick inside display
TEXT is PRESERVED (safety); clean code is untouched; the pass is idempotent; and the file-level
repair rewrites only offending frontend files. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _unescape_delimiter_backticks, repair_frontend_escaped_backticks)

BT = "`"          # a real backtick
ESC = "\\`"       # a backslash-escaped backtick (the malformation)


def _mangle(clean: str) -> str:
    """Turn every real delimiter backtick into an escaped one (what the lane emits).
    Valid only for snippets whose backticks are ALL template delimiters (no literal
    escaped backtick already present)."""
    return clean.replace(BT, ESC)


# ─────────────────── every malformed delimiter shape is fixed ───────────────────

def test_jsx_classname_with_interpolation():
    clean = "<div className={`flex px-4 ${sel ? 'bg-x' : ''} py-3`}>"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_standalone_assignment_template():
    clean = "const c = `hi ${n} there`;"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_call_argument_templates():
    clean = "const x = clsx(`a`, `b`);"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_return_template():
    clean = "  return `Bearer ${token}`;"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_ternary_both_branches():
    clean = "const s = cond ? `on` : `off`;"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_array_of_templates():
    clean = "const arr = [`x-${a}`, `y-${b}`];"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_logical_and_className():
    clean = "className={active && `border-blue`}"
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


def test_multiline_realistic_run13_case():
    clean = (
        "    <div\n"
        "      onClick={onClick}\n"
        "      className={`flex px-4 py-3 cursor-pointer ${selected ? 'bg-x' : ''}`}\n"
        "    >")
    assert _unescape_delimiter_backticks(_mangle(clean)) == clean


# ─────────────────────────── safety: preserve legit cases ───────────────────────────

def test_clean_real_backticks_untouched():
    clean = "className={`flex ${a} p-4`}"
    assert _unescape_delimiter_backticks(clean) == clean          # no change at all


def test_no_backticks_untouched():
    s = "const x = 5; return <div className='p-4'>{x}</div>;"
    assert _unescape_delimiter_backticks(s) == s


def test_legit_escaped_backtick_inside_text_is_preserved():
    # a REAL template literal whose TEXT contains a literal backtick (escaped) — the
    # neighbours of the escaped backtick are ordinary chars, so it must NOT be touched.
    s = "const msg = `press the " + ESC + " key to run`;"
    out = _unescape_delimiter_backticks(s)
    assert out == s                                               # preserved verbatim
    assert ESC in out                                            # the escape survives


def test_idempotent():
    bad = _mangle("className={`flex ${a} p-4`}")
    once = _unescape_delimiter_backticks(bad)
    twice = _unescape_delimiter_backticks(once)
    assert once == twice == "className={`flex ${a} p-4`}"


def test_escaped_backslash_before_delimiter_not_touched():
    # `x\\`  = a LITERAL backslash then a real delimiter backtick; the delimiter is NOT
    # escaped (the backslash is escaped), so nothing should change.
    s = "const p = String.raw`a\\\\` + `b`;"   # contains \\ then real `
    # sanity: this snippet has no backslash-directly-before-a-delimiter to fix
    assert _unescape_delimiter_backticks(s) == s


# ─────────────────────────── file-level repair ───────────────────────────

def test_repair_writes_only_offending_files(tmp_path):
    src = tmp_path / "src" / "components"
    src.mkdir(parents=True)
    bad = src / "MessageRow.jsx"
    good = src / "FolderList.jsx"
    css = tmp_path / "src" / "index.css"
    bad.write_text(_mangle("export default () => <div className={`flex ${x} p-4`}>hi</div>;"),
                   encoding="utf-8")
    good.write_text("export default () => <div className={`flex p-4`}>ok</div>;", encoding="utf-8")
    css.write_text("body{color:red}", encoding="utf-8")

    res = repair_frontend_escaped_backticks(tmp_path)
    repaired = res["repaired"]

    assert "components/MessageRow.jsx" in repaired
    assert "components/FolderList.jsx" not in repaired          # already clean
    assert ESC not in bad.read_text(encoding="utf-8")           # fixed on disk
    assert bad.read_text(encoding="utf-8") == (
        "export default () => <div className={`flex ${x} p-4`}>hi</div>;")
    # a second run is a no-op (idempotent, nothing left to repair)
    assert repair_frontend_escaped_backticks(tmp_path)["repaired"] == []


def test_missing_frontend_dir_is_safe(tmp_path):
    assert repair_frontend_escaped_backticks(tmp_path / "nope")["repaired"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── Fix #69 — escaped JSX attribute quotes (outlook run-57, live) ──────────────
def test_unescape_jsx_attr_quotes_repairs_className():
    from multi_agent.runtime.frontend_scaffold import _unescape_jsx_attr_quotes
    src = '<div className=\\"min-h-screen flex bg-[#ffffff]\\"><span id=\\"a\\"/></div>'
    fixed = _unescape_jsx_attr_quotes(src)
    assert '\\"' not in fixed
    assert 'className="min-h-screen flex bg-[#ffffff]"' in fixed
    assert 'id="a"' in fixed


def test_unescape_jsx_attr_quotes_leaves_legit_escaped_string_quote():
    """A genuinely-escaped quote INSIDE a string literal (value carries a backslash
    or another quote) must NOT be touched — safety property."""
    from multi_agent.runtime.frontend_scaffold import _unescape_jsx_attr_quotes
    # a string with an intentional escaped quote — value contains backslash → no match
    src = 'const s = "she said \\"hi\\"";'
    assert _unescape_jsx_attr_quotes(src) == src


def test_unescape_jsx_attr_quotes_noop_on_clean():
    from multi_agent.runtime.frontend_scaffold import _unescape_jsx_attr_quotes
    clean = '<div className="a b c" id="x">hi</div>'
    assert _unescape_jsx_attr_quotes(clean) == clean


def test_repair_pass_fixes_escaped_quote_file(tmp_path):
    """The wired repair pass rewrites a JSON-escaped JSX file (the run-57 docker_up
    wedge cause) so it compiles."""
    from multi_agent.runtime.frontend_scaffold import repair_frontend_escaped_backticks
    src_dir = tmp_path / "src" / "pages"
    src_dir.mkdir(parents=True)
    f = src_dir / "LoginPage.jsx"
    f.write_text(
        'export default function LoginPage(){\n'
        '  return (<div className=\\"min-h-screen bg-[#fff]\\">'
        '<button className=\\"px-4 py-2\\">Log in</button></div>);\n}\n',
        encoding="utf-8")
    out = repair_frontend_escaped_backticks(tmp_path)
    txt = f.read_text(encoding="utf-8")
    assert '\\"' not in txt
    assert 'className="min-h-screen bg-[#fff]"' in txt
    assert "pages/LoginPage.jsx" in [p.replace("\\", "/") for p in out["repaired"]]
