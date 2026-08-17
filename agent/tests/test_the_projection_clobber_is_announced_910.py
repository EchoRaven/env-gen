r"""#910: the projector deletes the lane's page in silence.

`scaffold_pages_from_contract` replaces a page with its reference projection when

    _cand_ok and (not _marked or _stale_thin_projection_583(_existing, _cand))

`_marked` means *"the existing page carries MY marker"*. So `not _marked` — the lane wrote it —
clobbers **unconditionally on content**. #583 added a candidate-vs-existing comparison, but only
for a page the projector had already marked; there is no analogous test for the lane's.

Measured on r153's own delivered git history, where `merge agent/frontend → integration` and
`framework delivery: … + projections` alternate for **30 revisions of BrowseHomePage.jsx alone**:

    BrowseHomePage     479 -> 166 lines   (-313, twice)     browse_home         0.80
    LanguagesPage      324 -> 100         (-224)            browse_by_languages 0.60
    NewAndPopularPage  326 -> 130         (-196, four times) new_and_popular    0.62
    LoginPage          186 ->  72         (-114)            login               0.60
    PlayerPage         170 ->  94         ( -76)            player              0.35

The lane's BrowseHomePage rendered its own `<TopNav>`/`<Tile>`; the projection renders no
components at all — the mechanism behind #909's 70% orphan rate.

★ Whether the projector SHOULD defer to a substantially richer lane page is a genuine question with
a fidelity payoff and a real regression risk (this markup is what the visual gate has been scoring
all along), so it stays a user decision. What is not defensible is deleting 313 lines of lane work
without a word. This ticket only adds the word.

★ Driven through a real scaffold with a log sink, not asserted against source text. The previous
version of this very block called `logger.warning(...)` — and `frontend_scaffold` has no
module-level `logger`, so it raised `NameError` inside the `except Exception: pass` wrapping it and
the line could never have fired. A guard around an observability call hides bugs in the
observability call; the only way to know it works is to make it speak.
"""
import logging
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


def _run(existing_body: str, caplog):
    """Scaffold over an existing page and return (warnings, final body)."""
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    pages = fe / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "BrowseHomePage.jsx").write_text(existing_body, encoding="utf-8")
    orig_load = fs._load_design_for_projection
    fs._load_design_for_projection = lambda _fd: _DESIGN
    try:
        with caplog.at_level(logging.WARNING,
                             logger="env_generator.llm_generator.multi_agent.runtime"
                                    ".frontend_scaffold"):
            fs.scaffold_pages_from_contract(fe, [
                {"name": "browse_home", "route": "/browse", "component": "BrowseHomePage",
                 "apis_used": ["GET /api/titles"],
                 "path": "app/frontend/src/pages/BrowseHomePage.jsx"},
            ])
    finally:
        fs._load_design_for_projection = orig_load
    return ([r.getMessage() for r in caplog.records if "PROJECTION CLOBBER" in r.getMessage()],
            (pages / "BrowseHomePage.jsx").read_text(encoding="utf-8"))


def _lane_page(n_lines: int) -> str:
    body = ["export default function BrowseHomePage() {", "  return (", "    <div>",
            "      <TopNav />", "      <Tile />"]
    body += [f"      {{/* lane row {i} */}}" for i in range(n_lines)]
    body += ["    </div>", "  );", "}"]
    return "\n".join(body)


def test_clobbering_a_larger_lane_page_is_announced(caplog):
    """The defect: a 300-line lane page replaced by a shorter projection, silently."""
    warnings, _ = _run(_lane_page(300), caplog)
    assert warnings, "the clobber must say so"
    assert "BrowseHomePage" in warnings[0]


def test_the_message_carries_both_sizes_and_the_component_count(caplog):
    """An operator needs the magnitude, not just the event — 479->166 is the finding."""
    warnings, _ = _run(_lane_page(300), caplog)
    nums = re.findall(r"\d+", warnings[0])
    assert len(nums) >= 3, warnings[0]
    assert "component tag" in warnings[0]


def test_the_clobber_still_happens(caplog):
    """★ Non-regression, and the point of the ticket: #910 adds a LOG, not a behaviour change.
    If someone later makes the projector defer to the lane, that is a separate decision and this
    test is where it gets noticed."""
    _, final = _run(_lane_page(300), caplog)
    assert "lane row" not in final, "the projection must still win until that decision is made"


def test_a_page_the_projector_already_marked_is_not_reported(caplog):
    """`_marked` pages go through #583's comparison instead — that path is not this one."""
    marked = ('<div data-projected="ref">\n' + "\n".join(
        f"  {{/* prior projection {i} */}}" for i in range(400)) + "\n</div>")
    warnings, _ = _run(marked, caplog)
    assert not warnings, warnings


def test_a_smaller_lane_page_is_not_reported(caplog):
    """Replacing a 4-line stub with a real projection is the projector doing its job; reporting it
    would bury the case that matters (#845 — a line that fires every tick stops being read)."""
    warnings, _ = _run("export default () => <div />", caplog)
    assert not warnings, warnings


def test_the_announcement_cannot_break_the_scaffold():
    """It sits inside the page-writing loop. The first version called a `logger` this module does
    not define, and the enclosing `except Exception: pass` hid it completely."""
    import inspect
    src = inspect.getsource(fs.scaffold_pages_from_contract)
    i = src.index("PROJECTION CLOBBER")
    block = src[i - 700:i + 700]
    assert "except Exception:" in block
    assert "logger.warning" not in block, "this module has no module-level `logger`"
    assert 'getLogger(__name__)' in block



# --------------------------------------------------------------------------- #910b

def _run_auth(existing_body: str, caplog):
    """The AUTH branch — unconditional, and the one that provably loops."""
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    pages = fe / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "LoginPage.jsx").write_text(existing_body, encoding="utf-8")
    orig_load = fs._load_design_for_projection
    fs._load_design_for_projection = lambda _fd: _DESIGN
    try:
        with caplog.at_level(logging.WARNING,
                             logger="env_generator.llm_generator.multi_agent.runtime"
                                    ".frontend_scaffold"):
            fs.scaffold_pages_from_contract(fe, [
                {"name": "login", "route": "/login", "component": "LoginPage",
                 "apis_used": [], "path": "app/frontend/src/pages/LoginPage.jsx"},
            ])
    finally:
        fs._load_design_for_projection = orig_load
    return [r.getMessage() for r in caplog.records if "AUTH PAGE OVERWRITE" in r.getMessage()]


_R134_LANE_LOGIN = """import React from 'react';
import AuthShell from '../components/AuthShell';
import AuthForm from '../components/AuthForm';

export default function LoginPage() {
  return (
    <AuthShell>
      <AuthForm />
    </AuthShell>
  );
}
"""


def test_the_unconditional_auth_overwrite_is_announced(caplog):
    """★ r134's real shape. Its LoginPage.jsx alternates between exactly two byte-identical
    states for 41 cycles — this 11-line component-based page and the framework's 72-line inline
    form — and #910's announcement covered only the design-screen branch, not this one."""
    warnings = _run_auth(_R134_LANE_LOGIN, caplog)
    assert warnings, "the unconditional overwrite must say so"
    assert "LoginPage" in warnings[0]
    assert "component tag" in warnings[0]


def test_an_empty_or_absent_auth_page_is_not_reported(caplog):
    """Writing the auth form where there was nothing is the branch doing its job — reporting it
    would fire on every clean run and stop being read (#845)."""
    assert not _run_auth("", caplog)


def test_rewriting_an_identical_page_is_not_reported(caplog):
    """The scaffold is idempotent and runs every delivery tick; only a real REPLACEMENT is news.
    #899 learned this the expensive way — 34 of r153's 35 stage lines were the same no-change
    entry."""
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    orig_load = fs._load_design_for_projection
    fs._load_design_for_projection = lambda _fd: _DESIGN
    spec = [{"name": "login", "route": "/login", "component": "LoginPage", "apis_used": [],
             "path": "app/frontend/src/pages/LoginPage.jsx"}]
    try:
        fs.scaffold_pages_from_contract(fe, spec)          # first write
        with caplog.at_level(logging.WARNING,
                             logger="env_generator.llm_generator.multi_agent.runtime"
                                    ".frontend_scaffold"):
            fs.scaffold_pages_from_contract(fe, spec)      # idempotent re-run
    finally:
        fs._load_design_for_projection = orig_load
    assert not [r for r in caplog.records if "AUTH PAGE OVERWRITE" in r.getMessage()]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
