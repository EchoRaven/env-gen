r"""#914: the decision, implemented and switched OFF.

`scaffold_pages_from_contract` clobbers a lane page unconditionally on content — `not _marked`
means "the existing page is not MY output", and that alone is taken as permission (#910). Whether
it SHOULD defer to a substantially richer, component-based lane page is a real question with
measured evidence on both sides, so this ticket implements the rule and leaves it **off**.

★ The test is not new. It is `_stale_thin_projection_583`'s own first condition, in its own words:

    "the existing file imports NOTHING from `../components/` — a lane that refined a page pulls
     its own components in; a bare projection does not"

#583 applies it only to a page the projector already marked. For a LANE page — where it is the
more obvious question — nothing asks it at all.

Replaying all 1269 net-deleting clobbers in the corpus:

    replaced a page importing ../components/   537   42%   real lane work
    replaced a stub / generic layout           732   58%   the projector's actual purpose

Both directions have scars. FOR the projector: r92 shipped 11 StubPages, r93 wired 3 routes against
an 11-screen reference, r7/r8 scored 0.10–0.15 per screen against a 0.65 bar. AGAINST it: #566j,
r117/r120 — clobbering a real 230-line lane page wedged deliverability into a 75-minute no-deliver
abort. And the asymmetry that stops the corpus from settling it: **every fidelity score in the arc
was earned by the projection**; the lane's pages have never been rendered to a camera.

★ Off, it still LOGS. A run with the flag unset measures the exposure for free — how many pages the
rule would keep and which — with byte-identical output. That is the cheap half of the experiment;
the other half is one run with it on, compared against r153's per-screen baseline.
"""
import logging
import os
import re
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_DESIGN = {"screens": [
    {"name": "browse_home", "route": "/browse", "kind": "page",
     "components": [{"id": "row1-carousel", "role": "first content row of 5 title cards"},
                    {"id": "row2-carousel", "role": "second content row of 5 title cards"}]},
]}

_PAGE = {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
         "apis_used": ["GET /api/titles"],
         "path": "app/frontend/src/pages/BrowseHomePage.jsx"}


def _lane_page(*, imports_components: bool, n: int = 300) -> str:
    head = "import Tile from '../components/Tile.jsx';\n" if imports_components else ""
    body = "\n".join(f"  {{/* lane {i} */}}" for i in range(n))
    tag = "<Tile/>" if imports_components else "<div/>"
    return (f"{head}export default function BrowseHomePage(){{ return (<div>{tag}\n"
            f"{body}\n</div>); }}")


def _scaffold(existing: str, caplog=None):
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    (fe / "src" / "components").mkdir(parents=True)
    target = fe / "src" / "pages" / "BrowseHomePage.jsx"
    target.write_text(existing, encoding="utf-8")
    orig = fs._load_design_for_projection
    fs._load_design_for_projection = lambda _fd: _DESIGN
    try:
        if caplog is not None:
            with caplog.at_level(logging.WARNING,
                                 logger="env_generator.llm_generator.multi_agent.runtime"
                                        ".frontend_scaffold"):
                fs.scaffold_pages_from_contract(fe, [_PAGE])
        else:
            fs.scaffold_pages_from_contract(fe, [_PAGE])
    finally:
        fs._load_design_for_projection = orig
    return target.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- the flag

def test_the_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    assert fs._env_flag_914() is False


def test_the_flag_reads_the_usual_truthy_spellings(monkeypatch):
    for v in ("1", "true", "TRUE", "yes", "y", "on"):
        monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", v)
        assert fs._env_flag_914() is True, v
    for v in ("0", "false", "no", "", "  "):
        monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", v)
        assert fs._env_flag_914() is False, v


def test_the_flag_is_read_per_call_not_at_import(monkeypatch):
    """A run must be startable either way without a reload, and a test must be able to flip it."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    assert fs._env_flag_914() is False
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "1")
    assert fs._env_flag_914() is True


# --------------------------------------------------------------------------- behaviour

def test_default_off_is_byte_identical_to_before(monkeypatch):
    """★ The whole point of shipping it off: the projection still wins, exactly as today."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    out = _scaffold(_lane_page(imports_components=True))
    assert "lane 0" not in out, "with the flag off the projection must still replace the page"


def test_the_flag_keeps_a_component_based_lane_page(monkeypatch):
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "1")
    out = _scaffold(_lane_page(imports_components=True))
    assert "lane 0" in out, "with the flag on the lane's page must survive"
    assert "../components/Tile.jsx" in out


def test_the_flag_does_NOT_protect_a_lane_page_without_components(monkeypatch):
    """★ The 58%. A stub or generic layout is exactly what the projector exists to replace —
    r92 shipped 11 StubPages, r7/r8 scored 0.10-0.15 per screen. The rule must not shelter those."""
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "1")
    out = _scaffold(_lane_page(imports_components=False))
    assert "lane 0" not in out


def test_a_marked_projection_is_unaffected_by_the_flag(monkeypatch):
    """`_marked` pages go through #583's own comparison; #914 is only about unmarked ones."""
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "1")
    marked = ('<div data-projected="ref">\n'
              + "\n".join(f"  {{/* prior {i} */}}" for i in range(400)) + "\n</div>")
    out = _scaffold(marked)
    assert "prior 0" in out, "an existing marked projection is left alone either way"


# --------------------------------------------------------------------------- the free measurement

def test_it_logs_even_when_off(caplog, monkeypatch):
    """★ The cheap half of the experiment: a run with the flag unset measures the exposure with
    byte-identical output. Driven through a real scaffold with a log sink — asserting the source
    string would pass against a line that cannot execute (#910's `logger` NameError)."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    _scaffold(_lane_page(imports_components=True), caplog=caplog)
    msgs = [r.getMessage() for r in caplog.records if "LANE PAGE WITH OWN COMPONENTS" in r.getMessage()]
    assert msgs, "off must still report what it would have kept"
    assert "replacing it" in msgs[0], msgs[0]


def test_the_log_says_which_way_it_went(caplog, monkeypatch):
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "1")
    _scaffold(_lane_page(imports_components=True), caplog=caplog)
    msgs = [r.getMessage() for r in caplog.records if "LANE PAGE WITH OWN COMPONENTS" in r.getMessage()]
    assert msgs and "KEEPING the lane's page" in msgs[0], msgs


def test_the_message_carries_both_sizes(caplog, monkeypatch):
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    _scaffold(_lane_page(imports_components=True), caplog=caplog)
    msg = next(r.getMessage() for r in caplog.records
               if "LANE PAGE WITH OWN COMPONENTS" in r.getMessage())
    assert len(re.findall(r"\d+", msg)) >= 2, msg


def test_a_stub_lane_page_is_not_reported(caplog, monkeypatch):
    """No log for the 58% — a line that fires on every clean run stops being read (#845)."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    _scaffold(_lane_page(imports_components=False), caplog=caplog)
    assert not [r for r in caplog.records if "LANE PAGE WITH OWN COMPONENTS" in r.getMessage()]


def test_a_page_importing_its_own_components_is_never_stale_to_583():
    """#583's first condition, asserted as behaviour: whatever the fresh render looks like, a page
    that pulls its own components in is not a stale thin projection."""
    rich = "<div><ul><li/></ul><h2/><table/><form/></div>"
    assert fs._stale_thin_projection_583(_lane_page(imports_components=True), rich) is False


def test_both_sites_route_through_the_one_predicate(monkeypatch, caplog):
    """★ The rule is not invented here — if #583's condition is ever reworded the two uses must be
    reconciled rather than silently diverging (which is how #905/#906 diverged).

    Enforced with a SPY, not a source string. The previous version of this test asserted the exact
    spelling `'"../components/" in (_existing or "")'` at the #914 call site — and #782 is the
    lesson that a spelling assertion turns the better implementation into a prohibition: extracting
    the shared predicate, which is #906's own remedy for a duplicated criterion, would have failed
    it. A spy delegates to the real predicate, changes no behaviour, and goes red for the thing the
    test actually cares about: either site re-inlining the criterion instead of calling it.
    """
    seen = []
    real = fs._imports_own_components
    monkeypatch.setattr(fs, "_imports_own_components",
                        lambda src: (seen.append(src or ""), real(src))[1])

    lane = _lane_page(imports_components=True)
    assert fs._stale_thin_projection_583(lane, "<div/>") is False
    assert any("lane 0" in s for s in seen), "#583 must ask the shared predicate"

    seen.clear()
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    _scaffold(lane, caplog=caplog)
    assert any("lane 0" in s for s in seen), "#914 must ask the shared predicate"


def test_the_predicate_tolerates_a_missing_page():
    """★ The seam this refactor introduced: #583 guards `not existing` before asking, #914 passes a
    possibly-None `_existing` straight in. The predicate owns the None, so both callers are safe."""
    assert fs._imports_own_components(None) is False
    assert fs._imports_own_components("") is False
    assert fs._imports_own_components("import X from '../components/X.jsx'") is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
