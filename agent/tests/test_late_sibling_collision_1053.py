r"""#1053: the #638 shim is never re-evaluated, so the collision it fixes re-forms.

#638 measured the same-stem collision across 21 of 45 delivered frontends and shipped the
fix. The fix is real. It just runs in one place only — the gap-fill's MISSING-file branch:

    if p.exists() and p.read_text().strip(): continue     <- returns here, forever
    ...
    _shim = _reexport_shim_638(p)                          <- only reached when p is MISSING

So the shim answers "does this filename exist" exactly once, and a sibling that appears
LATER is never seen. r171, with timestamps on every link:

    11:36:06  GitOps writes services/api.js   3303 B, DEFINES window.NetflixAPI
              (#638 checks for a sibling, finds none, correctly writes the full baseline)
    11:42:49  frontend writes services/api.jsx 1457 B, does NOT define it
              (6m43s later — the collision forms AFTER detection already ran)
              App.jsx imports './services/api.jsx'  <- the one without the definition

    => window.NetflixAPI undefined          (76 occurrences in the r171 log)
    => nine UI flows cannot run             (45 occurrences)
    => validation_ui_evidence_failed + deliverability_ui_flow_failed never clear
    => nine runs, zero deliveries

DIRECTION MATTERS, and it is the reverse of #638's. #638 runs when the baseline is absent, so
it makes the BASELINE the shim and the lane's file the implementation. Here the baseline
already exists and is the module that defines the global, and #638's own constraint is
verbatim that it must keep resolving: *"Skipping the write is NOT safe — projected code
imports `../services/api.js` by exact name"*. So the LATE sibling becomes the re-export.

Getting that backwards would produce a cycle (`api.js` re-exports `api.jsx` re-exports
`api.js`), which is why a file that is already a shim is never converted in either direction.
"""
from pathlib import Path

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _reexport_shim_638 as shim_638,
    _reexport_late_sibling_1053 as late,
)

_NAMED = "export function getTitles() {}\nexport function listGenres() {}\n"
_WITH_DEFAULT = _NAMED + "export default { getTitles, listGenres };\n"
_REAL = "window.NetflixAPI = {};\n" + _NAMED


def _svc(tmp_path):
    d = tmp_path / "src" / "services"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(d, name, body):
    (d / name).write_text(body, encoding="utf-8")
    return d / name


# --- the r171 case ---------------------------------------------------------------------------

def test_a_sibling_that_appears_later_is_converted(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.js", _REAL)
    _write(d, "api.jsx", _NAMED)
    out = late(base)
    assert out is not None
    sib, text = out
    assert sib.name == "api.jsx"
    assert "export * from './api.js';" in text


def test_the_baseline_stays_the_implementation(tmp_path):
    """#638's constraint: projected code imports api.js by exact name."""
    d = _svc(tmp_path)
    base = _write(d, "api.js", _REAL)
    _write(d, "api.jsx", _NAMED)
    sib, _text = late(base)
    assert base.read_text() == _REAL
    assert sib.name != "api.js"


def test_a_default_export_is_forwarded_when_the_baseline_has_one(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.js", _WITH_DEFAULT)
    _write(d, "api.jsx", _NAMED)
    _sib, text = late(base)
    assert "export { default } from './api.js';" in text


def test_a_missing_default_is_NOT_forwarded(tmp_path):
    """Re-exporting a default that does not exist is a build error."""
    d = _svc(tmp_path)
    base = _write(d, "api.js", _NAMED)
    _write(d, "api.jsx", _NAMED)
    _sib, text = late(base)
    assert "export { default }" not in text


def test_an_mjs_sibling_works_too(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.js", _REAL)
    _write(d, "api.mjs", _NAMED)
    sib, _t = late(base)
    assert sib.name == "api.mjs"


# --- no cycles, ever -------------------------------------------------------------------------

def test_a_baseline_that_is_ALREADY_a_638_shim_is_left_alone(tmp_path):
    """#638 ran first: api.js is the shim, api.jsx is the implementation. Converting the
    sibling here would make each re-export the other."""
    d = _svc(tmp_path)
    _write(d, "api.jsx", _NAMED)
    base = _write(d, "api.js", shim_638(d / "api.js"))
    assert late(base) is None


def test_a_sibling_that_is_already_a_shim_is_left_alone(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.js", _REAL)
    _write(d, "api.jsx", "export * from './api.js';\n")
    assert late(base) is None


def test_a_second_pass_changes_nothing(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.js", _REAL)
    _write(d, "api.jsx", _NAMED)
    sib, text = late(base)
    sib.write_text(text, encoding="utf-8")
    assert late(base) is None


# --- leave everything else exactly as it was -------------------------------------------------

def test_no_sibling_means_nothing_happens(tmp_path):
    d = _svc(tmp_path)
    assert late(_write(d, "api.js", _REAL)) is None


def test_an_empty_sibling_is_not_an_implementation(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.js", _REAL)
    _write(d, "api.jsx", "   \n")
    assert late(base) is None


def test_a_non_module_baseline_is_untouched(tmp_path):
    d = _svc(tmp_path)
    base = _write(d, "api.css", "body{}")
    _write(d, "api.jsx", _NAMED)
    assert late(base) is None


def test_a_broken_path_returns_None():
    assert late(Path("/nonexistent/does/not/exist/api.js")) is None


def test_an_empty_baseline_is_not_an_implementation(tmp_path):
    """Nothing to re-export TO."""
    d = _svc(tmp_path)
    base = _write(d, "api.js", "  \n")
    _write(d, "api.jsx", _NAMED)
    assert late(base) is None


# --- end to end, through the function the runtime actually calls -----------------------------
#
# §4 of the r171 handoff: "#1013 attached a guard to scaffold_missing_local_pages, which
# Scaffolder.scaffold_frontend_pages() NEVER calls. A real guard on dead code." So this
# exercises `scaffold_frontend_baseline` itself — the function reached from
# framework_validation.py (per tick), orchestrator.py x2 and scaffolder.py. The per-tick call
# is the one that matters here: the collision forms 6m43s AFTER the first write, so only a
# re-check on a later pass can see it.

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    scaffold_frontend_baseline,
)


def _api(fe):
    return fe / "src" / "services" / "api.js"


def test_the_r171_sequence_end_to_end(tmp_path):
    fe = tmp_path / "app" / "frontend"
    scaffold_frontend_baseline(fe)                    # 11:36:06 — baseline lands, no sibling
    base = _api(fe)
    assert base.is_file() and base.read_text().strip()
    before = base.read_text()

    sib = base.with_suffix(".jsx")                    # 11:42:49 — the lane writes the sibling
    sib.write_text(_NAMED, encoding="utf-8")

    scaffold_frontend_baseline(fe)                    # the next tick

    assert "export * from './api.js';" in sib.read_text()   # sibling now re-exports
    assert base.read_text() == before                       # baseline untouched


def test_a_run_with_no_collision_is_unchanged(tmp_path):
    fe = tmp_path / "app" / "frontend"
    scaffold_frontend_baseline(fe)
    snapshot = {p: p.read_text(encoding="utf-8", errors="ignore")
                for p in (fe / "src").rglob("*") if p.is_file()}
    scaffold_frontend_baseline(fe)
    after = {p: p.read_text(encoding="utf-8", errors="ignore")
             for p in (fe / "src").rglob("*") if p.is_file()}
    assert after == snapshot


def test_the_conversion_is_reported(tmp_path):
    fe = tmp_path / "app" / "frontend"
    scaffold_frontend_baseline(fe)
    _api(fe).with_suffix(".jsx").write_text(_NAMED, encoding="utf-8")
    rep = scaffold_frontend_baseline(fe)
    assert any("re-export" in w for w in (rep.get("written") or [])), rep
