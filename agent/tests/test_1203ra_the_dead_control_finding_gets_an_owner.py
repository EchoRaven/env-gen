"""#1203ra -- `_page_dead_controls` has been right and unheard.

Measured over every task store on disk: the sentence the audit emits appears in **0 of 26001
tasks across 105 runs**, and all 10 of its log lines are the orchestrator's own UI-PAGE
LIFECYCLE warning -- 0 in a prompt, a task, or any message to a lane.

The silence was hard to see because a SIBLING channel does file work: a broad grep for
"dead control" finds 598 tasks ("Re-verify the failing UI evidence records", "Fix the failing
critical UI flow", "Fix the dead nav link") which all come from the browser walkthrough and
read like coverage. Only the exact static sentence is zero. A wide keyword merges two
producers into one and hides exactly this.

netflix-local-r46 is the cost in one line: the audit caught BOTH landing-page CTAs
(`LandingPage` dead controls: 2 of 2 -- "Get Started" and "Learn More"), repeated it five
times across five passes, never told the frontend lane, and the run shipped them inert. That
is #780's "a finding nobody is assigned" sitting on the standing rule that a built UI must
actually work.

THE AUDIT SIDE IS DRIVEN. The precedent's own test (`test_component_drift_reaches_the_lane_
1202bc`) is entirely source-text assertions -- a 1.00 text-assertion ratio, which is the shape
this session has been closing all day -- so it is deliberately NOT copied. Only the scaffolder
wiring, which lives inside a 524-line method that cannot be driven in a unit test, is asserted
structurally, and then on its AST rather than its spelling.
"""
import ast
import inspect
import sys
import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as FA
from env_generator.llm_generator.multi_agent.runtime import registryhub as R

DEAD = ("export default function P(){\n"
        "  return <div><button className='cta'>Get Started</button></div>;\n}")
WIRED = ("export default function P(){\n"
         "  return <div><button onClick={go}>Get Started</button></div>;\n}")


def _hub(reg):
    class _H:
        def get_ui_pages(self):
            return reg.list_ui_pages()
        def get_ui_components(self):
            return reg.list_ui_components()
        def update_ui_page(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_page(name, route=d.pop("route", ""),
                                        component=d.pop("component", ""),
                                        apis_used=d.pop("apis_used", None),
                                        components=d.pop("components", None),
                                        path=d.pop("path", ""),
                                        status=d.pop("status", ""), agent=agent, **d)
        def update_ui_component(self, name, data, agent=""):
            d = dict(data or {})
            return reg.register_ui_component(name, component=d.pop("component", ""),
                                             apis_used=d.pop("apis_used", None),
                                             status=d.pop("status", ""), agent=agent, **d)
    return _H()


def _sync(tmp_path, page_src):
    reg = R.RegistryHub(tempfile.mkdtemp())
    reg.register_ui_page("p", route="/p", component="P", path="src/pages/P.jsx",
                         agent="frontend")
    src = tmp_path / "app" / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "App.jsx").write_text(
        "import P from './pages/P'\n"
        "export default function App(){return <Route path='/p' element={<P/>}/>}",
        encoding="utf-8")
    (src / "pages" / "P.jsx").write_text(page_src, encoding="utf-8")
    return FA.sync_ui_page_statuses(tmp_path, _hub(reg), reg)


# ------------------------------------------------------------------ the audit side, driven
def test_a_dead_control_is_surfaced_for_the_dispatcher(tmp_path):
    out = _sync(tmp_path, DEAD)
    assert "p" in (out.get("dead_controls") or {}), (
        "the finding is computed and still unreachable: %r" % (out.get("dead_controls"),))


def test_the_surfaced_entry_carries_the_counts(tmp_path):
    """#983: say WHICH and HOW MANY. A task naming only the page sends the lane hunting."""
    reasons = (_sync(tmp_path, DEAD).get("dead_controls") or {}).get("p") or []
    assert reasons, "no reason text surfaced"
    assert any("dead controls" in r for r in reasons)
    assert any("1 of 1" in r for r in reasons), reasons


def test_a_wired_control_surfaces_nothing(tmp_path):
    """THE COUNTER-PROOF. A key that is always populated is as useless as one never
    populated, and both pass a test that only checks the dead case."""
    out = _sync(tmp_path, WIRED)
    assert "p" not in (out.get("dead_controls") or {}), out.get("dead_controls")


def test_surfacing_does_not_change_the_page_verdict(tmp_path):
    """Reported only, exactly like #909 and #918: the page is still held for the same reason
    it was held for before, and the new key is ADDITIVE rather than a replacement."""
    out = _sync(tmp_path, DEAD)
    pending = (out.get("pending") or {}).get("p") or []
    assert any(FA.DEAD_CONTROL_MARK_1203RA in m for m in pending), (
        "the existing pending reason disappeared: %r" % (pending,))
    assert "p" not in (out.get("implemented") or [])


def test_the_producer_emits_the_shared_constant(tmp_path):
    """One source of truth, asserted BEHAVIOURALLY. Recognising a finding by retyping its
    sentence is how a consumer silently stops matching when the producer is reworded, so the
    constant must be what `audit_ui_page` actually puts in `missing` -- not merely a string
    that happens to look like it."""
    page = {"name": "p", "route": "/p", "component": "P", "path": "src/pages/P.jsx"}
    cache = {"/x/src/pages/P.jsx": DEAD}
    _ok, missing = FA.audit_ui_page(Path("/x/src"), page, _src_cache=cache)
    assert any(FA.DEAD_CONTROL_MARK_1203RA in m for m in missing), missing


# ------------------------------------------- the dedupe primitive the wiring depends on
def test_the_dedupe_guard_fires_once_per_changed_value():
    """BOTH HALVES OF THE PRECEDENT (#1139's lesson). `create_task` has no duplicate check --
    #672 only REPORTS a twin -- and the scaffold ran 117 times in r32, so an unguarded finding
    that persists until a lane fixes it files 117 tasks. The corpus prices it: of 838 cancelled
    tasks, 462 (55%) were cancelled as duplicates. So the guard is not decoration, and its
    semantics are driven here rather than assumed."""
    from env_generator.llm_generator.multi_agent.runtime.message_format import (
        state_changed_1202ad as sc)
    key = "test:dead_controls_1203ra:%d" % id(object())
    assert sc(key, ("a",)) is True, "the first sighting must fire"
    assert sc(key, ("a",)) is False, "an unchanged finding must NOT re-file"
    assert sc(key, ("a", "b")) is True, "a changed finding must fire again"


# ------------------------------------------- the wiring: AST, not spelling
def _ra_block():
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    src = Path(inspect.getfile(scaffolder)).read_text(encoding="utf-8")
    i = src.index("#1203ra: FILE THE DEAD CONTROLS")
    j = src.index('"the dead-control task report (#1203ra)"', i)
    return src[i:j]


def test_the_create_task_is_inside_the_dedupe_guard():
    """★ The property that matters, and the one a text assertion cannot see: both strings can
    be present with the call OUTSIDE the guard, which files a task every scaffold pass. Parse
    the block and require the call to be lexically nested in the `if` that tests the guard."""
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    # Parse the WHOLE module and find the nodes. The first version of this test sliced the
    # block out by two string landmarks and parsed the fragment, which cut a statement in
    # half and raised SyntaxError -- a slice is not a parse unit.
    tree = ast.parse(Path(inspect.getfile(scaffolder)).read_text(encoding="utf-8"))
    guards = [n for n in ast.walk(tree)
              if isinstance(n, ast.If) and "_sc1203ra" in ast.dump(n.test)]
    assert guards, "no `if state_changed(...)` guard for the dead-control task"
    guarded = [n for g in guards for n in ast.walk(g)
               if isinstance(n, ast.Call)
               and getattr(n.func, "attr", getattr(n.func, "id", "")) == "create_task"]
    assert guarded, "create_task is not nested inside the `state_changed` guard"

    # and it must not ALSO be filed outside one: a second unguarded call would file a task
    # every scaffold pass while this test still passed on the guarded one.
    ra_calls = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call)
                and getattr(n.func, "attr", getattr(n.func, "id", "")) == "create_task"):
            kw = {k.arg: k for k in n.keywords}
            title = kw.get("title")
            if title is not None and "do nothing when clicked" in ast.dump(title):
                ra_calls.append(n)
    assert len(ra_calls) == len(guarded) == 1, (
        "the dead-control task is filed %d times, %d of them guarded"
        % (len(ra_calls), len(guarded)))

    # AND THE POLARITY, which nesting alone cannot see (#1203r4's shape): `if not
    # state_changed(...)` keeps the call nested and files the task only while the finding is
    # UNCHANGED -- never on the pass that discovers it. Nor may the guard be widened into a
    # tautology, which would file every scaffold pass; 55% of the corpus's 838 cancelled
    # tasks were already cancelled as duplicates.
    g = guards[0]
    assert not isinstance(g.test, ast.UnaryOp), (
        "the dedupe guard is negated, so the task fires only while nothing changed")
    assert not isinstance(g.test, ast.Constant), "the guard is a constant -- always on"
    assert not (isinstance(g.test, ast.BoolOp) and isinstance(g.test.op, ast.Or)), (
        "an `or` in the guard can make it tautological (`if True or state_changed(...)`)")
    assert isinstance(g.test, ast.Call), (
        "the guard must BE the state_changed call, got %s" % type(g.test).__name__)


def test_the_finding_is_read_from_the_audit_result():
    assert '_pa.get("dead_controls")' in _ra_block(), "the surfaced key has no consumer"


def test_it_goes_to_the_lane_that_owns_the_pages():
    b = _ra_block()
    assert 'assignee="frontend"' in b
    assert "create_task" in b


def test_a_failure_to_file_is_announced():
    """A silent `except` here would recreate the exact defect being fixed -- a finding that
    exists and reaches nobody."""
    from env_generator.llm_generator.multi_agent.runtime import scaffolder
    src = Path(inspect.getfile(scaffolder)).read_text(encoding="utf-8")
    i = src.index("#1203ra: FILE THE DEAD CONTROLS")
    j = src.index('_pa.get("implemented")', i)
    assert "warn_once_1201" in src[i:j]
