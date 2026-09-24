"""#1202cv — #520 must not overwrite the lane's nav on zero reference evidence.

`_project_nav_component_src`'s docstring promises it returns None — caller KEEPS the
lane nav — "when App.jsx is unreadable or the design lacks a substantial nav (<4 links),
so a weak/absent decomposition never clobbers a good lane nav". The gate counted
nav_routes, which are derived from App.jsx's ROUTE TABLE and not from the reference at
all. The two agree only while the measurement works.

r41 is what happens when it does not. Its design measured ZERO reference nav labels (the
analyst wrote a description, "Header area with brand logo at left and primary horizontal
navigation links", where #422's parser needs an enumeration). `_filter_nav_to_ref` is
itself gated on >=4 labels, so it returned its input unfiltered; all seven route entries
survived, including the capture-only states /browse/rows, /browse/card-hover and
/browse/rate; the count passed; and the projection replaced a lane nav that was ALREADY
exactly what the judge had asked for. Seven screens share that header. All seven
regressed in one round, and the run ended below its own round-3 peak.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _project_nav_component_src,
    _ref_nav_labels,
)

APP_JSX = "\n".join(
    f'<Route path="{p}" element={{<C{i}/>}} />' for i, p in enumerate(
        ["/browse", "/shows", "/movies", "/games", "/new", "/my-list"]))

ENUMERATED = {"screens": [{"components": [{
    "id": "primary-nav-links",
    "role": "horizontal primary nav: Home, Shows, Movies, Games, New & Popular, My List",
}]}]}

DESCRIBED_ONLY = {"screens": [{"components": [{
    "id": "top-navigation-bar",
    "role": "Header area with brand logo at left and primary horizontal navigation links.",
}]}]}


@pytest.fixture
def frontend(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.jsx").write_text(APP_JSX)
    return tmp_path


def test_zero_measured_labels_keeps_the_lane_nav(frontend):
    """The r41 case. A design that never enumerated the nav is the LEAST justification
    for overriding the lane, and it used to be the case that sailed through."""
    assert _ref_nav_labels(DESCRIBED_ONLY) == []
    assert _project_nav_component_src(frontend, DESCRIBED_ONLY, "NetflixHeader") is None


def test_a_measured_nav_still_projects(frontend):
    """#520 exists because the lane nav did not converge across r91/r92. Fixing the gate
    must not disable the mechanism where it has the evidence it was built on."""
    assert len(_ref_nav_labels(ENUMERATED)) == 6
    out = _project_nav_component_src(frontend, ENUMERATED, "NetflixHeader")
    assert out and "<a href" in out


def test_the_gate_reads_the_reference_not_the_route_table(frontend):
    """A route table alone must never authorise the override — that is precisely the
    quantity that stayed healthy in r41 while the evidence was empty."""
    many_routes = "\n".join(
        f'<Route path="/r{i}" element={{<C{i}/>}} />' for i in range(9))
    (frontend / "src" / "App.jsx").write_text(many_routes)
    assert _project_nav_component_src(frontend, DESCRIBED_ONLY, "NetflixHeader") is None


def test_the_evidence_gate_precedes_the_route_count():
    """Order matters for the next reader: the reference check must come first, so the
    route-derived count can never be what admits a projection."""
    src = Path("env_generator/llm_generator/multi_agent/runtime/"
               "frontend_scaffold.py").read_text()
    body = src[src.index("def _project_nav_component_src"):]
    body = body[:body.index("def ", 40)]
    assert body.index("_ref_nav_labels(design)) < 4") < body.index("len(nav_routes) < 4")
