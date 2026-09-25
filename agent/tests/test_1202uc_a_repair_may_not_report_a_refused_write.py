r"""#1202uc: the route repair reported success 38 times for a write that was refused.

`repair_frontend_unmatchable_routes_1202sd` rewrites a `<Route path>` React Router cannot
compile -- `/@:username`, where the `:` does not follow a `/`, so compilePath extracts no
param and the path matches only its own literal spelling. The page is then unreachable.

It called `_fw_write_1202cw(f, new)` with NO `clobber_ok` and then appended to its `touched`
list without looking at the return value. App.jsx is LANE-OWNED, so #1202cw refused the write
-- correctly, that is its entire job -- and the repair reported it as done anyway.

MEASURED in r133 (delivered, $416.73): "#1202sd rewrote 1 <Route path>" was logged 38 times
over 1h45m, always the same route, while the registry still held `/@:username` and the
DELIVERED App.jsx still carried `path="/@:username"`. `profile_own_page` shipped unreachable
and the log said, every tick for the life of the run, that it had been fixed.

TWO SEPARATE DEFECTS, and the second is the general one:
  * the clobber was never declared, so the write could not succeed;
  * the RETURN VALUE WAS IGNORED, so the mechanism could not tell success from refusal. A
    guard that answers "no" is useless if the caller does not listen -- and #1202cw's whole
    design is that it answers "no" by default.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    repair_frontend_unmatchable_routes_1202sd as _repair,
)
from multi_agent.runtime.path_routed_workspace import (  # noqa: E402
    path_is_lane_owned_1202cw,
)

SCAFFOLD = LLM_DIR / "multi_agent" / "runtime" / "frontend_scaffold.py"


def _app(src_text):
    """★ Under `app/frontend/...`, because that is what makes App.jsx LANE-OWNED.

    The first version of this fixture used a bare temp dir. `_app_relative_1202cw` then
    resolved nothing, the path was not lane-owned, #1202cw allowed the write, and two of the
    tests below passed against the UNFIXED code -- green for a reason that had nothing to do
    with what they claim to test. Reproduce the production shape or the guard never engages.
    """
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "App.jsx").write_text(src_text, encoding="utf-8")
    assert path_is_lane_owned_1202cw(fe / "src" / "App.jsx"), "fixture is not lane-owned"
    return fe


def test_the_target_really_is_lane_owned():
    """Premise. If App.jsx were framework-owned the write would never have been refused."""
    assert path_is_lane_owned_1202cw("/x/run/app/frontend/src/App.jsx")


def test_the_rewrite_reaches_the_file():
    """The bug: r133 delivered `path="/@:username"` after 38 reports that it was rewritten."""
    fe = _app('<Routes><Route path="/@:username" element={<P/>} /></Routes>')
    out = _repair(fe)
    text = (fe / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "/@:" not in text, text
    assert 'path="/:username"' in text, text
    assert out.get("repaired") and not out.get("refused"), out


def test_a_report_of_success_means_the_bytes_changed():
    """★ The general rule. Anything this repair counts as repaired must be on disk."""
    fe = _app('<Routes><Route path="/@:username" element={<P/>} /></Routes>')
    out = _repair(fe)
    text = (fe / "src" / "App.jsx").read_text(encoding="utf-8")
    for entry in (out.get("repaired") or []):
        name = entry.split(" (")[0]
        assert name == "App.jsx"
        assert "/@:" not in text, "reported repaired while the tell is still in the file"


def test_a_refused_write_is_reported_as_refused_not_repaired():
    """The discriminator: when the guard says no, the repair must say so too."""
    import multi_agent.runtime.frontend_scaffold as FS
    fe = _app('<Routes><Route path="/@:username" element={<P/>} /></Routes>')
    real = FS._fw_write_1202cw
    try:
        FS._fw_write_1202cw = lambda *a, **k: False      # the guard refuses
        out = _repair(fe)
    finally:
        FS._fw_write_1202cw = real
    assert out.get("repaired") == [], out
    assert out.get("refused") == ["App.jsx"], out


def test_the_clobber_is_declared_with_a_ticket():
    """#1202cw: `clobber_ok` is an argument, not a switch -- it must cite its decision."""
    src = SCAFFOLD.read_text(encoding="utf-8")
    fn = src[src.index("def repair_frontend_unmatchable_routes_1202sd"):]
    fn = fn[:fn.index("\ndef ", 10)]
    m = re.search(r'clobber_ok="([^"]{0,200})', fn)
    assert m, "the repair writes a lane-owned file without declaring why"
    assert re.search(r"#\d+", m.group(1)), m.group(1)


def test_a_path_router_can_already_match_is_left_alone():
    """No churn on routes that compile: the repair must be a no-op there."""
    ok = '<Routes><Route path="/users/:id" element={<P/>} /></Routes>'
    fe = _app(ok)
    out = _repair(fe)
    assert (fe / "src" / "App.jsx").read_text(encoding="utf-8") == ok
    assert not out.get("repaired"), out
