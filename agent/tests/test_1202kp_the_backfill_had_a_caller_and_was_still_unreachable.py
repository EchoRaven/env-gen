"""#1202kp: #1202ka had a caller and was still unreachable on the path that needed it.

`_backfill_drafts_from_registry_1202ka` fills a kickoff section the lanes REGISTERED but never
transcribed into the meeting. It sits at the top of the drafts pipeline in `try_synthesize`.
The quorum check runs EARLIER and returns first:

    missing = _missing_attendees(decisions, _quorum_attendees)
    if missing:
        return {"status": "awaiting", ...}     # <- returns here
    ...
    drafts = _collect_drafts(decisions)
    ...
    if reconcile:
        drafts, notes = _backfill_drafts_from_registry_1202ka(hubs, drafts)   # <- never reached

So on the reconcile path — the one that exists to converge deterministically instead of
aborting — synthesis answered `awaiting` without ever asking the registry. `grep -c` finds the
call site and a wiring audit passes, which is precisely why the rule is "prove REACHABILITY,
not presence".

tiktok-r116, live: M1 kickoff timed out after 1203s with `Missing=['backend']` and
`residual findings=[]` — no validation complaint, just a missing speaker. In that same window
the backend lane made 1541 tool calls including 88 `registryhub_register_endpoint` and 37
`registryhub_register_table`, and at the abort its ledger held 21 endpoints, 11 tables and 13
ui_pages. It did the work and never transcribed the decision. r112 and r113 died the same way
within an hour of each other.

WHAT IS VERIFIED, replayed against r116's REAL ledger: the backfill supplies backend and
frontend, `missing=['backend']` becomes nobody, and the kickoff proceeds instead of aborting.

WHAT IS NOT: that r116 would have delivered. It would have entered implementation with a
contract built from its own registrations; everything after that is unknown.

The verifier has no registry-backed section, so a missing verifier still blocks — the abort
path is narrowed, not removed.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_LLM = _AGENT / "env_generator" / "llm_generator"
for _p in (str(_LLM), str(_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ast          # noqa: E402
import inspect      # noqa: E402
import textwrap     # noqa: E402
import types        # noqa: E402

from multi_agent.runtime.kickoff.run_kickoff import (   # noqa: E402
    _backfill_drafts_from_registry_1202ka,
    _section_supplied_by_registry_1202kp,
)


def _rh(endpoints=None, tables=None, pages=None):
    class RH:
        def get_endpoints(self):  return endpoints or {}
        def list_tables(self):    return tables or {}
        def list_ui_pages(self):  return pages or {}
    return types.SimpleNamespace(registryhub=RH())


def _r116_like():
    """r116's shape: the lane registered real work, recorded no section."""
    eps = {f"GET /api/x{i}": {"method": "GET", "path": f"/api/x{i}"} for i in range(21)}
    tbl = {f"t{i}": {"name": f"t{i}", "schema": {"columns": [{"name": "id", "type": "int"}]}}
           for i in range(11)}
    pgs = {f"p{i}": {"name": f"p{i}", "route": f"/p{i}"} for i in range(13)}
    return _rh(eps, tbl, pgs)


# --- the reachability defect ----------------------------------------------------------------

def test_the_quorum_check_now_asks_the_registry_first():
    """★ The fix, read from the parse tree: the `awaiting` return must be preceded by a
    reconcile-guarded probe, or #1202ka stays unreachable exactly as before."""
    from multi_agent.runtime.kickoff import run_kickoff as RK
    src = textwrap.dedent(inspect.getsource(RK.try_synthesize))
    tree = ast.parse(src)
    probe_line = ret_line = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_backfill_drafts_from_registry_1202ka"):
            probe_line = node.lineno if probe_line is None else min(probe_line, node.lineno)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if (isinstance(k, ast.Constant) and k.value == "status"
                        and isinstance(v, ast.Constant) and v.value == "awaiting"):
                    ret_line = node.lineno
    assert probe_line and ret_line, (probe_line, ret_line)
    assert probe_line < ret_line, (
        "the registry probe must run BEFORE the `awaiting` return — that ordering IS the bug")

    # ...and it must be REACHABLE. Position alone is not reachability: an `if False:` around
    # the call keeps the node exactly where it is and restores the original defect, which is
    # the whole lesson this fix is named for. Require a live guard that reads `missing`.
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "_section_supplied_by_registry_1202kp" not in ast.dump(
                ast.Module(body=node.body, type_ignores=[])):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        consts = [c for c in ast.walk(node.test) if isinstance(c, ast.Constant)]
        assert "missing" in names, f"the probe guard must read `missing`: {ast.unparse(node.test)}"
        assert not (len(consts) == 1 and consts[0].value is False), "the probe is disabled"
        return
    raise AssertionError("the probe is not inside a guarded branch at all")


def test_the_probe_only_runs_when_reconciling():
    """★ Scope: the normal path must still wait for the lanes to speak. Only the last-resort
    reconcile may substitute the registry."""
    from multi_agent.runtime.kickoff import run_kickoff as RK
    src = textwrap.dedent(inspect.getsource(RK.try_synthesize))
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.If):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "_section_supplied_by_registry_1202kp" in body:
            g = ast.unparse(node.test)
            assert "reconcile" in g and "missing" in g, g
            return
    raise AssertionError("the #1202kp probe is not guarded by `reconcile`")


# --- what counts as supplied ------------------------------------------------------------------

def test_r116s_real_shape_clears_the_missing_backend():
    """★ The case."""
    drafts, notes = _backfill_drafts_from_registry_1202ka(_r116_like(), {})
    assert notes, "the registry had the work; the backfill must find it"
    assert _section_supplied_by_registry_1202kp("backend", drafts) is True
    still = [a for a in ["backend"] if not _section_supplied_by_registry_1202kp(a, drafts)]
    assert still == [], "backend should no longer count as missing"


def test_a_missing_verifier_still_blocks():
    """★ The abort path is narrowed, not removed: the verifier's section has no registry
    counterpart, so it can never be substituted."""
    drafts, _ = _backfill_drafts_from_registry_1202ka(_r116_like(), {})
    assert _section_supplied_by_registry_1202kp("verifier", drafts) is False


def test_backend_needs_BOTH_endpoints_and_tables():
    """★ Half a contract is not a section. Endpoints with no data model would synthesize a
    contract the data-model cross-checks then reject — an abort one step later, with the
    kickoff clock already spent."""
    eps = {"GET /api/x": {"method": "GET", "path": "/api/x"}}
    drafts, _ = _backfill_drafts_from_registry_1202ka(_rh(eps, {}, {}), {})
    assert _section_supplied_by_registry_1202kp("backend", drafts) is False


def test_an_empty_registry_supplies_nothing():
    """★ The floor: a lane that is genuinely silent, with nothing registered, still blocks."""
    drafts, notes = _backfill_drafts_from_registry_1202ka(_rh(), {})
    assert notes == []
    for a in ("backend", "frontend", "verifier"):
        assert _section_supplied_by_registry_1202kp(a, drafts) is False


def test_a_lane_that_DID_speak_is_never_overridden():
    """#1202ka fills EMPTY sections only — the registry substitutes for silence, it does not
    outvote a decision the lane actually recorded."""
    spoken = {"backend": {"endpoints": [{"method": "POST", "path": "/api/mine"}],
                          "data_model": {"tables": [{"name": "mine"}]}}}
    drafts, _ = _backfill_drafts_from_registry_1202ka(_r116_like(), spoken)
    assert drafts["backend"]["endpoints"] == [{"method": "POST", "path": "/api/mine"}]


def test_the_probe_cannot_turn_a_salvage_into_a_new_failure():
    """A fault in the probe must leave the old `awaiting` answer, not raise into the driver."""
    from multi_agent.runtime.kickoff import run_kickoff as RK
    src = textwrap.dedent(inspect.getsource(RK.try_synthesize))
    # #943: the INNERMOST try containing the probe, from the parse tree — a byte window here
    # would drift the moment the comment above the probe grows, which it already has.
    cands = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Try)
             and "_section_supplied_by_registry_1202kp" in ast.unparse(n)]
    assert cands, "the probe is not wrapped in a try"
    inner = min(cands, key=lambda n: len(ast.unparse(n)))
    assert any(isinstance(h.type, ast.Name) and h.type.id == "Exception"
               for h in inner.handlers), "the probe must not raise into the driver"
