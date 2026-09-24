r"""#1202tr: the fabricated-fallback repair rewrites LANE files and was invisible to the census.

`repair_fabricated_fallbacks` (#496/#1202mp) replaces a fabricated fallback literal with an
honest em-dash -- `{user.name || 'Jane Cooper'}` becomes `{(user.name ?? '—')}` -- by rewriting
the lane's page and component sources IN PLACE. That is a framework write onto lane-owned work,
which #1202cw exists to route and record, and it went straight to `Path.write_text`.

So those writes reached neither of the two things the choke point does: the census that #1011
measured at ~22,000 overwrites and that `run_budget.json` now carries, and the provenance scrub.

WHAT MAKES THIS WORTH A TICKET rather than a tidy-up: #1202cw's sweep
(`test_no_runtime_module_writes_app_sources_outside_the_choke_point`) was already GENERAL -- it
enumerates every runtime module with a raw write and demands each be guarded or exempt. This
module was exempt, with the stated reason "audit output". The rule was right; the FACT fed into
it was false. That is the failure mode an exemption list has and a rule does not: it asserts
something falsifiable and then nothing ever re-checks it.

MEASURED against the real function and the real predicate, not a reading of the code: replaying
`repair_fabricated_fallbacks` over copies of all 170 corpus frontends rewrites 87 files across
31 runs, and `path_is_lane_owned_1202cw` calls 87 of 87 lane-owned.

The module's OTHER write (the auth-fetch shim into `index.html`) stays raw and is marked
`# raw:`, because `path_is_lane_owned_1202cw` says index.html is framework-owned -- checked,
not assumed.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import frontend_audit as FA            # noqa: E402
from multi_agent.runtime.path_routed_workspace import (         # noqa: E402
    lane_clobbers_1202cw, path_is_lane_owned_1202cw,
)

FAKE = "export default function P(){ return <b>{user.name || 'Jane Cooper'}</b> }"
AUDIT_PY = LLM_DIR / "multi_agent" / "runtime" / "frontend_audit.py"


def _page(name="Feed.jsx"):
    src = Path(tempfile.mkdtemp()) / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    f = src / "pages" / name
    f.write_text(FAKE, encoding="utf-8")
    return src, f


def test_the_fixture_is_really_lane_owned():
    """Non-vacuity (#1202tm): if the fixture path were not lane-owned, the census would be
    empty for a reason that has nothing to do with this fix."""
    _src, f = _page()
    assert path_is_lane_owned_1202cw(f), f


def test_the_repair_still_repairs():
    """Routing through the guard must not cost the repair itself."""
    src, f = _page()
    out = FA.repair_fabricated_fallbacks(src)
    assert out["repaired"] == ["Feed.jsx"], out
    assert "Jane Cooper" not in f.read_text(encoding="utf-8")
    assert "??" in f.read_text(encoding="utf-8")


def test_the_repair_is_recorded_as_a_declared_clobber():
    """The bug: 87 lane-file rewrites across 31 corpus runs reached no ledger at all."""
    src, _f = _page("Profile.jsx")
    FA.repair_fabricated_fallbacks(src)
    declared = lane_clobbers_1202cw()["declared"]
    assert any(k.endswith("app/frontend/src/pages/Profile.jsx") for k in declared), \
        sorted(declared)[:20]


def test_it_does_not_silently_bypass_when_the_guard_is_missing(monkeypatch):
    """#1201 and the user's rule on fallbacks that hide failure: if the choke point cannot be
    imported, the lane's file is left ALONE and the reason is said out loud -- the one thing it
    must never do is quietly go back to writing raw."""
    src, f = _page("Silent.jsx")
    monkeypatch.setattr(FA, "_fw_write_1202cw", None)
    out = FA.repair_fabricated_fallbacks(src)
    assert out["repaired"] == [], out
    assert f.read_text(encoding="utf-8") == FAKE      # untouched, not raw-written


def test_the_framework_owned_write_stays_raw_and_says_so():
    """index.html is framework-owned by the real predicate, so it keeps its raw write -- but
    the marker has to be there, or the sweep cannot tell it from an unnoticed bypass."""
    assert not path_is_lane_owned_1202cw("/x/run/app/frontend/index.html")
    line = [l for l in AUDIT_PY.read_text(encoding="utf-8").split("\n")
            if "idx.write_text(" in l]
    assert len(line) == 1 and "# raw:" in line[0], line


def test_the_module_is_classified_as_a_projector():
    """The correction itself: it must not drift back onto the framework-only list."""
    ratchet = (ROOT / "tests"
               / "test_1202cw_clobbering_lane_work_is_a_declared_exception.py").read_text(
        encoding="utf-8")
    head = ratchet.split("_FRAMEWORK_ONLY_WRITERS_1202TD = {")[0]
    assert '"frontend_audit.py"' in head, "frontend_audit.py is no longer in PROJECTORS"
    body = ratchet.split("_FRAMEWORK_ONLY_WRITERS_1202TD = {")[1].split("}")[0]
    assert "frontend_audit.py" not in body, "it is exempt again as a framework-only writer"
