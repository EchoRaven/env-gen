"""#485 — CJS→ESM api.js repair (netflix r58, live; also r5/r51/r54).

A frontend lane authors services/api.js in CommonJS (`const api = {...};
module.exports = api; module.exports.getToken = getToken;`). Under Vite's ESM build
esbuild shims `module`, so the CJS assignment is DEAD and a default-import consumer
(`import api from '../services/api'; api.isAuthed()`) receives an EMPTY object —
`api.isAuthed is not a function` white-screens EVERY auth-gated page (r58: 10/12 pages;
delivery gate BLOCKED on deliverability_ui_flow_failed). Worse, the existing
repair_frontend_default_api_import finds no ESM named exports on a CJS file and appends
a bogus `export default {};`, cementing the empty object. repair_frontend_cjs_module_exports
converts the CJS exports to ESM so the default import resolves to the REAL api object —
comment out the dead module.exports lines, upgrade the empty default to
`export default api`, and re-export CJS-attached members as ESM named exports (ONLY
identifiers actually declared top-level, so the Vite build can never break)."""
import tempfile
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    repair_frontend_cjs_module_exports)


def _run(files: dict) -> dict:
    """Write {relpath: text} under a temp frontend/src, run the repair, return
    {relpath: new_text}."""
    tmp = tempfile.mkdtemp()
    fe = Path(tmp) / "app" / "frontend"
    src = fe / "src"
    for rel, txt in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    repair_frontend_cjs_module_exports(fe)
    return {rel: (src / rel).read_text(encoding="utf-8") for rel in files}


# ---- real r54 pattern: bare `module.exports = api` + props + bogus empty default ----
_R54_API = '''\
function getToken() { return localStorage.getItem("t"); }
function isAuthed() { return Boolean(getToken()); }
function login() {}
const api = {
  getToken: getToken,
  isAuthed: isAuthed,
  login: login,
};
module.exports = api;
module.exports.default = api;
module.exports.getToken = getToken;
module.exports.isAuthed = isAuthed;
module.exports.login = login;

export default {};
'''


def test_r54_bare_cjs_with_bogus_empty_default():
    out = _run({"services/api.js": _R54_API})["services/api.js"]
    # the empty default is upgraded to the real api object
    assert "export default {};" not in out
    assert "export default api;" in out, out
    # the dead CJS statements are commented, never executed under ESM
    assert "\nmodule.exports = api;" not in out
    assert "// [cjs->esm] module.exports = api;" in out
    # every CJS-attached member that is declared top-level is re-exported as ESM
    assert "isAuthed" in out and "export {" in out
    # named import of isAuthed now resolves (was the white-screen root cause)
    import re
    named = re.search(r"export \{ ([^}]*) \};", out)
    assert named and "isAuthed" in named.group(1), out


# ---- real r51 pattern: UMD one-liner guard, NO ESM default at all ----
_R51_API = '''\
function getToken() { return null; }
var api = {
  getToken: getToken,
};
if (typeof module !== 'undefined' && module.exports) { module.exports = api; module.exports.default = api; }
if (typeof window !== 'undefined') { window.__api = api; }
'''


def test_r51_umd_guard_gets_esm_default():
    out = _run({"services/api.js": _R51_API})["services/api.js"]
    # UMD guard line is neutralized (commented) and a real ESM default is added
    assert "// [cjs->esm] if (typeof module" in out, out
    assert "export default api;" in out, out
    # the harmless window.__api line (module.exports absent) is untouched
    assert "if (typeof window !== 'undefined') { window.__api = api; }" in out


# ---- already-ESM file: byte-identical (no regression on a correct file) ----
_ESM_API = '''\
function isAuthed() { return true; }
const api = { isAuthed };
export { isAuthed };
export default api;
'''


def test_already_esm_is_byte_identical():
    before = _ESM_API
    out = _run({"services/api.js": before})["services/api.js"]
    assert out == before, "correct ESM file must never be touched"


# ---- idempotent: running twice yields the same output ----
def test_idempotent():
    once = _run({"services/api.js": _R54_API})["services/api.js"]
    # feed the converted output back through
    tmp = tempfile.mkdtemp()
    src = Path(tmp) / "app" / "frontend" / "src"
    (src / "services").mkdir(parents=True)
    (src / "services" / "api.js").write_text(once, encoding="utf-8")
    repair_frontend_cjs_module_exports(Path(tmp) / "app" / "frontend")
    twice = (src / "services" / "api.js").read_text(encoding="utf-8")
    assert twice == once, "second pass must be a no-op (idempotent)"


# ---- safety: a module.exports whose default is NOT a declared top-level ident,
#      and with no re-exportable members, is left byte-identical (never strip
#      exports without an ESM replacement). ----
def test_undeterminable_default_left_untouched():
    src = 'module.exports = makeApi();\n'  # makeApi() not a declared identifier
    out = _run({"services/api.js": src})["services/api.js"]
    assert out == src, "no safe conversion possible → leave the file alone"


# ---- safety: only re-export members whose source is declared top-level ----
def test_named_export_only_for_declared_identifiers():
    src = '''\
function isAuthed() { return true; }
const api = { isAuthed };
module.exports = api;
module.exports.isAuthed = isAuthed;
module.exports.ghost = ghost;
'''
    out = _run({"services/api.js": src})["services/api.js"]
    assert "export default api;" in out
    import re
    named = re.search(r"export \{ ([^}]*) \};", out)
    # isAuthed is declared → exported; `ghost` is undeclared → MUST NOT be exported
    assert named and "isAuthed" in named.group(1)
    assert "ghost" not in (named.group(1) if named else ""), \
        "an undeclared identifier must never be ESM-exported (would break the build)"


# ---- generalizes beyond api.js: any frontend src CJS file is converted ----
def test_applies_to_any_frontend_src_file():
    src = '''\
function helper() { return 1; }
module.exports = helper;
'''
    out = _run({"utils/helper.js": src})["utils/helper.js"]
    assert "export default helper;" in out, out


# ---- a file with NO module.exports is byte-identical ----
def test_no_cjs_is_byte_identical():
    src = "export const x = 1;\nexport default { x };\n"
    out = _run({"components/Foo.jsx": src})["components/Foo.jsx"]
    assert out == src


# ---- #485b: OBJECT-LITERAL form `module.exports = {login, register, ...}` (r59 crash) ----
_R59_MULTILINE_OBJ = '''\
function login() {}
function register() {}
function isAuthed() { return true; }
const getToken = () => localStorage.getItem("t");

module.exports = {
  login,
  register,
  isAuthed,
  getToken,
};
'''


def test_r59_multiline_object_literal_export():
    """r59: `module.exports = {login, register, isAuthed, ...}` + `import * as api;
    api.login()` → bundle crash. Must become `export default {...}` (default import) AND
    `export { login, register, isAuthed, getToken }` (namespace import), with the
    multi-line body never left dangling (no syntax corruption)."""
    out = _run({"services/api.js": _R59_MULTILINE_OBJ})["services/api.js"]
    assert "export default {" in out, out
    assert "module.exports = {" not in out or "// [cjs->esm] module.exports = {" in out
    import re
    named = re.search(r"export \{ ([^}]*) \};", out)
    assert named, "namespace-import consumers need ESM named exports; none emitted\n" + out
    names = {n.strip() for n in named.group(1).split(",")}
    assert {"login", "register", "isAuthed", "getToken"} <= names, out
    # the multi-line object body must not be left dangling (would be a SyntaxError)
    assert "\n  login,\n  register," in out, "object body preserved as a valid literal\n" + out


def test_object_literal_single_line():
    src = ('function a(){}\nfunction b(){}\n'
           'module.exports = { a, b };\n')
    out = _run({"services/api.js": src})["services/api.js"]
    assert "export default { a, b };" in out, out
    import re
    named = re.search(r"export \{ ([^}]*) \};", out)
    assert named and {"a", "b"} <= {n.strip() for n in named.group(1).split(",")}


def test_object_literal_key_value_pairs():
    src = ('function login(){}\nconst reg = () => {}\n'
           'module.exports = { login: login, register: reg };\n')
    out = _run({"services/api.js": src})["services/api.js"]
    assert "export default {" in out
    import re
    named = re.search(r"export \{ ([^}]*) \};", out)
    got = named.group(1) if named else ""
    # `register: reg` → named export `reg as register`; `login: login` → `login`
    assert "reg as register" in got and "login" in got, out


def test_object_literal_nested_is_skipped_safely():
    """A NESTED object value can't be flat-sliced → the pattern must NOT match → the file
    is left byte-identical (never corrupted). A missed conversion is safe; corruption is not."""
    src = ('const cfg = {};\n'
           'module.exports = { a, opts: { deep: 1 } };\n')
    out = _run({"services/api.js": src})["services/api.js"]
    assert out == src, "nested object literal must be left untouched (no corruption)\n" + out


def test_object_literal_only_exports_declared_keys():
    """A key whose source isn't declared top-level must NOT be named-exported (build-safe)."""
    src = ('function real(){}\n'
           'module.exports = { real, ghost };\n')
    out = _run({"services/api.js": src})["services/api.js"]
    import re
    named = re.search(r"export \{ ([^}]*) \};", out)
    got = named.group(1) if named else ""
    assert "real" in got and "ghost" not in got, out
    # default still exports the whole object literal (runtime shape preserved)
    assert "export default { real, ghost };" in out, out


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
