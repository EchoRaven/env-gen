r"""#760: the second throwing auto-stub, found because #753 fixed only the first.

`frontend_scaffold` has two import/export repair passes that invent a missing export.
#753 fixed `repair_frontend_api_exports` after r149's console showed
`isAuthenticated not implemented (auto-stub)` taking down 9 screens. The other pass,
`repair_frontend_missing_local_exports`, had the identical defect and was left behind.

It is worse in one respect: its stub is **not async**, so the throw is SYNCHRONOUS — it kills
the caller at the call site rather than surfacing one tick later as an unhandled rejection.

**The function's own asymmetry is the argument.** Two lines above the throw:

    if n[:1].isupper():
        lines.append(f"export const {n} = (props) => null;  // auto-stub component")
    else:
        ... throw ...

A capitalised name — a COMPONENT — already gets a deliberately non-fatal `=> null`. The same
code chose gentleness for components and fatality for plain functions, and #753 established
which of those a crashed React tree deserves. Components keep `=> null` here, untouched.
"""
import inspect
import pathlib
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _repair(target_src: str, importer_src: str, target_name="helpers.js"):
    td = tempfile.mkdtemp()
    root = pathlib.Path(td)
    src = root / "src"
    (src / "pages").mkdir(parents=True)
    (src / target_name).write_text(target_src, encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(importer_src, encoding="utf-8")
    rep = fs.repair_frontend_missing_local_exports(root)
    return rep, (src / target_name).read_text(encoding="utf-8")


# --- the defect ---------------------------------------------------------------------------------

def test_a_missing_function_export_no_longer_throws():
    _rep, out = _repair("export const other = 1;\n",
                        "import { formatDuration } from '../helpers';\n")
    assert "throw new Error" not in out
    assert "not implemented (auto-stub)'" not in out


def test_it_says_the_implementation_is_missing():
    _rep, out = _repair("export const other = 1;\n",
                        "import { formatDuration } from '../helpers';\n")
    assert "console.error(" in out
    assert "MISSING IMPLEMENTATION, not an empty result" in out
    assert "formatDuration is imported but its module does not export it" in out


def test_the_shape_is_inferred_like_753():
    _rep, out = _repair("export const other = 1;\n",
                        "import { isKids, listGenres, getOne } from '../helpers';\n")
    assert "export const isKids = (...args) => { console.error(" in out
    assert "return false; }" in out       # predicate
    assert "return []; }" in out          # list-ish
    assert "return null; }" in out        # everything else


def test_it_reuses_753s_helper_rather_than_a_second_copy():
    src = inspect.getsource(fs.repair_frontend_missing_local_exports)
    assert "_stub_empty_value_753(n)" in src


# --- the component branch is untouched -------------------------------------------------------------

def test_a_capitalised_name_still_gets_the_null_component():
    _rep, out = _repair("export const other = 1;\n",
                        "import { HeroBillboard } from '../helpers';\n")
    assert "export const HeroBillboard = (props) => null;" in out
    assert "console.error" not in out, "the component branch was already non-fatal"


def test_both_kinds_in_one_repair():
    _rep, out = _repair("export const other = 1;\n",
                        "import { HeroBillboard, formatDuration } from '../helpers';\n")
    assert "(props) => null" in out
    assert "console.error(" in out
    assert "throw" not in out


# --- the surrounding repair still behaves -----------------------------------------------------------

def test_an_already_exported_name_is_left_alone():
    rep, out = _repair("export const formatDuration = () => 1;\n",
                       "import { formatDuration } from '../helpers';\n")
    assert "auto-stub" not in out


def test_a_declared_but_unexported_binding_is_re_exported_not_stubbed():
    """The outlook run-7 case the function documents: a stub there is a duplicate declaration
    and breaks the vite build."""
    rep, out = _repair("const AuthContext = createContext();\n",
                       "import { AuthContext } from '../helpers';\n")
    assert "auto-stub" not in out
    assert "export { AuthContext }" in out


def test_a_name_that_appears_anywhere_is_not_stubbed():
    """The conservative guard: a parser miss must never cause a duplicate declaration."""
    rep, out = _repair("// formatDuration lives here somewhere\n",
                       "import { formatDuration } from '../helpers';\n")
    assert "auto-stub" not in out


# --- provenance ----------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(fs.repair_frontend_missing_local_exports)
    i = src.index("#761: the SECOND throwing stub")
    return " ".join(l.strip().lstrip("#").strip()
                    for l in src[i:src.index("_empty761 =", i)].split("\n"))


def test_it_records_why_this_one_is_worse():
    p = _prov()
    assert "not async, so the throw is SYNCHRONOUS" in p
    assert "kills the caller at the call" in p


def test_it_records_the_asymmetry_as_the_argument():
    p = _prov()
    assert "already gets `=> null`, deliberately non-fatal" in p
    assert "chose gentleness for components and fatality for functions" in p


def test_it_credits_the_run_that_exposed_the_class():
    p = _prov()
    assert "r149" in p and "9 screens" in p


def test_no_throwing_stub_survives_anywhere_in_the_module():
    """The whole point: #753 fixed one of two sites. A third must not appear unnoticed."""
    src = inspect.getsource(fs)
    assert "throw new Error('{n} not implemented" not in src
    assert "throw new Error('{name} not implemented" not in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
