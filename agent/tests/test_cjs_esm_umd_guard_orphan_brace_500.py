"""#500 (netflix r79, 2026-08-05) — CJS→ESM conversion left an ORPHAN `}` that broke
the Vite build. repair_frontend_cjs_module_exports comments out every line carrying the
`module.exports` marker, but a MULTI-LINE UMD guard —

    if (typeof module !== 'undefined' && module.exports) {
      module.exports = api;
    }

— has its closing `}` on a line with NO marker, so the old line-commenter left it
DANGLING: `npm run build` → "Unexpected }" → docker_up fails → delivery wedged (r79:
verifier P0 task_096ecf0828, "api.js:125 stray `}` from CJS→ESM auto-conversion drift";
I killed the deliver tail mid-recovery). FIX: track the brace depth a commented CJS line
opens and comment through its matching close, so a guarded / multi-line CJS block is
neutralized in FULL (valid ESM). These tests reproduce the wedge (result must be
brace-balanced + build-parseable) and lock the byte-identical guarantee for the forms
that already worked (plain member assigns, single-line UMD, object literals)."""
import re
import types
import sys
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "frontend_scaffold.py")


def _load():
    # frontend_scaffold imports siblings via relative import; load it under a stub package.
    pkg = types.ModuleType("fs_pkg500")
    pkg.__path__ = []
    sys.modules["fs_pkg500"] = pkg
    import env_generator.llm_generator.multi_agent.runtime.message_format as _mf1034
    sys.modules["fs_pkg500.message_format"] = _mf1034  # #1034: leaf helper, no deps
    # #911: `frontend_scaffold` gained a MODULE-LEVEL sibling import
    # (`from .flow_coverage import _is_navigable_page`), so the synthetic package needs that
    # sibling present or collection dies here. Deliberately module-level in the real file: its
    # call site sits inside a `try:` whose handler is *"never raise into the orchestrator"* and
    # returns an empty result, so a function-local import that failed would silently turn the
    # whole scaffold into a no-op. Bound to the REAL function so the exec'd copy behaves
    # identically rather than against a stub that could drift.
    from env_generator.llm_generator.multi_agent.runtime.flow_coverage import (
        _is_navigable_page as _real_is_navigable_page)
    _fc = types.ModuleType("fs_pkg500.flow_coverage")
    _fc._is_navigable_page = _real_is_navigable_page
    sys.modules["fs_pkg500.flow_coverage"] = _fc
    mod = types.ModuleType("fs_pkg500.frontend_scaffold")
    mod.__package__ = "fs_pkg500"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


FS = _load()


def _run(tmp_path, api_src):
    fe = tmp_path / "frontend"
    (fe / "src" / "services").mkdir(parents=True)
    (fe / "src" / "services" / "api.js").write_text(api_src, encoding="utf-8")
    out = FS.repair_frontend_cjs_module_exports(fe)
    txt = (fe / "src" / "services" / "api.js").read_text(encoding="utf-8")
    return out, txt


def _active_lines(txt):
    """Lines NOT commented out (the code Vite actually parses)."""
    return [ln for ln in txt.split("\n")
            if ln.strip() and not ln.lstrip().startswith(("//", "*"))]


def _braces_balanced(txt):
    active = "\n".join(_active_lines(txt))
    return active.count("{") == active.count("}")


_UMD_MULTILINE = """\
const api = { isAuthed, login };
function isAuthed() { return true; }
function login() { return null; }
if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
export default api;
"""


def test_multiline_umd_guard_no_orphan_brace(tmp_path):
    # THE r79 bug: the guard's closing `}` must NOT survive as an active orphan.
    out, txt = _run(tmp_path, _UMD_MULTILINE)
    assert _braces_balanced(txt), "orphan brace survived:\n" + txt
    # the api object + default export are untouched; the whole guard block is commented.
    active = "\n".join(_active_lines(txt))
    assert "module.exports" not in active, active
    assert "export default api;" in active
    # a lone active `}` line (the orphan) must not exist
    assert not any(ln.strip() == "}" for ln in _active_lines(txt)), txt


def test_multiline_member_function_assignment(tmp_path):
    # `module.exports.getToken = function () { ... }` spanning lines — the body + close
    # must be commented in full, not half-commented into a syntax error.
    src = ("function getToken() { return 't'; }\n"
           "module.exports.getToken = function () {\n"
           "  return getToken();\n"
           "};\n"
           "module.exports = api;\n"
           "const api = { getToken };\n")
    out, txt = _run(tmp_path, src)
    assert _braces_balanced(txt), txt
    assert "module.exports" not in "\n".join(_active_lines(txt))


def test_singleline_umd_guard_still_whole_line_commented(tmp_path):
    # single-line UMD form was already handled — must stay handled (balanced, marker gone).
    src = ("const api = { login };\n"
           "function login() {}\n"
           "if (typeof module !== 'undefined' && module.exports) { module.exports = api; }\n"
           "export default api;\n")
    out, txt = _run(tmp_path, src)
    assert _braces_balanced(txt), txt
    assert "module.exports" not in "\n".join(_active_lines(txt))
    assert "export default api;" in "\n".join(_active_lines(txt))


def test_plain_member_assignments_byte_identical_behavior(tmp_path):
    # the r54 form (N flat `module.exports.X = Y;` lines, all balanced) — each commented
    # independently, no continuation; the named re-export is emitted as before.
    src = ("function login() {}\nfunction logout() {}\n"
           "const api = { login, logout };\n"
           "module.exports = api;\n"
           "module.exports.login = login;\n"
           "module.exports.logout = logout;\n")
    out, txt = _run(tmp_path, src)
    assert _braces_balanced(txt), txt
    active = "\n".join(_active_lines(txt))
    assert "module.exports" not in active
    # ESM named re-export for the top-level members is present
    assert "export {" in active and "login" in active and "logout" in active


def test_already_esm_file_untouched(tmp_path):
    # no ACTIVE module.exports → file left byte-identical (idempotent).
    src = ("const api = { login };\nfunction login() {}\n"
           "export { login };\nexport default api;\n")
    out, txt = _run(tmp_path, src)
    assert txt == src, txt
    assert out["repaired"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
