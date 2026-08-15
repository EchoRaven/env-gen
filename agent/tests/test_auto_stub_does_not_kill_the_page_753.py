r"""#753: the framework's own repair stub crashed every page that imported it.

`repair_frontend_api_exports` reconciles names a component imports from `api.js` against what
`api.js` exports. An unmatched name got a stub that THROWS. The comment already in that function
records the same defect once before: stubbing `apiGet`/`apiPost` "made every projected page throw
'apiGet not implemented (auto-stub)'", and it was patched for those two names only.

The general case still bit, and r149 is the worked example. It is also the first run in which the
evidence could be seen at all, because #740 only started keeping the browser console this session:

    #740 the browser reported 2 distinct uncaught/console error(s) during this capture:
    uncaught: isAuthenticated not implemented (auto-stub) (on 9 screen(s): browse_by_languages,
    browse_home, games, genre_category ...); uncaught: getActiveProfileId not ...

The costs are not symmetric. A throw takes down the whole React tree: the page renders nothing,
so it cannot be judged, cannot be visually remediated, and before #750 it shipped. A loud no-op
costs one broken feature on a page that still renders, and the lane still learns because the
console.error is captured by #740 and reaches the remediation text.

This is not the fabricated-fallback rule being relaxed — that rule is about an app inventing
product DATA to look complete. This is the framework's own repair for an import/export drift it
just detected; it invents no rows and says on every call that the implementation is MISSING.
"""
import inspect
import pathlib
import re
import tempfile

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


def _tree(root: pathlib.Path, api_src: str, page_src: str):
    """The real layout. My first fixture put api.js at `src/api.js` and imported from
    `'../api'`, and nothing was repaired — `_imported_api_names` only recognises an import
    whose PATH contains `services/api`, which is what the generated apps actually emit (r149's
    frontend was grepping `services/api` when it died). The fixture was wrong, not the code."""
    src = root / "src"
    (src / "services").mkdir(parents=True)
    (src / "pages").mkdir(parents=True)
    (src / "services" / "api.js").write_text(api_src, encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(page_src, encoding="utf-8")
    return src / "services" / "api.js"


def _repair(api_src: str, page_src: str):
    td = tempfile.mkdtemp()
    root = pathlib.Path(td)
    api = _tree(root, api_src, page_src)
    rep = fs.repair_frontend_api_exports(root)
    return rep, api.read_text(encoding="utf-8")


# --- the r149 case ------------------------------------------------------------------------------

def test_an_unmatched_import_no_longer_throws():
    rep, out = _repair("export const getTitles = async () => [];\n",
                       "import { isAuthenticated } from '../services/api';\n")
    assert "isAuthenticated" in (rep.get("stubbed") or []), rep
    assert "throw new Error" not in out
    assert "isAuthenticated not implemented (auto-stub)" not in out


def test_the_stub_says_the_implementation_is_missing():
    _rep, out = _repair("export const x = 1;\n", "import { isAuthenticated } from '../services/api';\n")
    assert "console.error(" in out
    assert "MISSING IMPLEMENTATION, not an empty result" in out
    assert "isAuthenticated is imported but api.js does not export it" in out


def test_the_page_still_gets_a_usable_value():
    _rep, out = _repair("export const x = 1;\n", "import { isAuthenticated } from '../services/api';\n")
    assert "return false;" in out


def test_the_second_r149_name_too():
    _rep, out = _repair("export const x = 1;\n", "import { getActiveProfileId } from '../services/api';\n")
    assert "return null;" in out
    assert "throw" not in out


# --- the shape is inferred, and a wrong guess is no worse than the throw --------------------------

@pytest.mark.parametrize("name,expected", [
    ("isAuthenticated", "false"), ("hasAccess", "false"), ("canPlay", "false"),
    ("shouldRetry", "false"),
    ("listTitles", "[]"), ("searchTitles", "[]"), ("findAll", "[]"), ("getGenres", "[]"),
    ("getActiveProfileId", "null"), ("apiGet", "null"), ("fetchOne", "null"),
])
def test_the_inferred_shape(name, expected):
    assert fs._stub_empty_value_753(name) == expected


def test_a_predicate_named_like_a_plural_is_still_a_predicate():
    """`isKids` must not become [] just because... it does not end in a lowercase s. Pinned so
    the two rules' precedence is explicit rather than incidental."""
    assert fs._stub_empty_value_753("isKids") == "false"


@pytest.mark.parametrize("junk", ["", None, "   "])
def test_a_nameless_stub_is_null(junk):
    assert fs._stub_empty_value_753(junk) == "null"


# --- everything else about the repair is unchanged --------------------------------------------------

def test_an_aliasable_name_is_still_aliased_not_stubbed():
    rep, out = _repair("export const getTitles = async () => [];\n",
                       "import { getTitle } from '../services/api';\n")
    assert rep.get("aliased"), rep
    assert not rep.get("stubbed"), "a near-match must never reach the stub path"


def test_an_existing_binding_is_still_re_exported():
    rep, out = _repair("const api = {a:1};\nexport default api;\n",
                       "import { api } from '../services/api';\n")
    assert "export { api };" in out
    assert not rep.get("stubbed")


def test_a_fully_satisfied_import_is_a_no_op():
    rep, out = _repair("export const getTitles = async () => [];\n",
                       "import { getTitles } from '../services/api';\n")
    assert rep.get("repaired") is False
    assert "auto-stub" not in out


def test_the_report_still_lists_stubbed_names():
    """The caller's contract is unchanged — only the emitted JS differs."""
    rep, _out = _repair("export const x = 1;\n",
                        "import { alpha, beta } from '../services/api';\n")
    assert sorted(rep.get("stubbed") or []) == ["alpha", "beta"]


def test_the_emitted_js_is_still_one_statement_per_name():
    _rep, out = _repair("export const x = 1;\n", "import { alpha, beta } from '../services/api';\n")
    assert out.count("export const alpha") == 1
    assert out.count("export const beta") == 1


# --- provenance ---------------------------------------------------------------------------------------

def _prov() -> str:
    src = inspect.getsource(fs.repair_frontend_api_exports)
    i = src.index("#753: FAIL THE FEATURE")
    blk = src[i:src.index("stubbed.append(name)", i)]
    return " ".join(l.strip().lstrip("#").strip() for l in blk.split("\n"))


def test_the_r149_evidence_is_recorded():
    p = _prov()
    assert "isAuthenticated not implemented (auto-stub) (on 9 screen(s)" in p
    assert "740 only started keeping the browser console this session" in p


def test_the_prior_occurrence_is_credited():
    p = _prov()
    assert "patched for those two names only" in p


def test_the_asymmetry_is_argued_not_asserted():
    p = _prov()
    assert "takes down the WHOLE React tree" in p
    assert "before #750 it shipped" in p


def test_the_fabricated_fallback_rule_is_addressed_head_on():
    """The obvious objection. If this is ever revisited, the distinction must be visible."""
    p = _prov()
    assert "NOT the fabricated-fallback rule relaxed" in p
    assert "it invents no rows" in p


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
