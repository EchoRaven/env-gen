r"""#1202z2: kickoff records what the materials' `visibility` verdict actually did.

Half the runs lose every verdict and nothing on disk says so.

MEASURED over the 180 corpus runs:
  * only 8.5% of tables (179 of 2118) carry `metadata.visibility`, and 136 runs have none
  * the materials are NOT silent: the reference spec declares a verdict for 381 of 1740
    entities (22%), and only 175 of those 381 (46%) reach the table registry
  * restricted to runs dated on/after 2026-09-20, and to spec entities whose name IS a
    registered table, delivery is 28/56 (50%) -- and it is bimodal per run:
        r129 11/11   r131 11/11   r133 3/3   r135 2/2   r137 12/12   r138 4/4
        r127 0/3     r128 0/4     r132 0/3   r134 0/8   r139 0/9     r130 2/7
    All-or-nothing per run is the signature of a code path that runs or does not, not of a
    per-table matching problem.

WHAT IS ALREADY RULED OUT:
  * the loader. `_spec_visibility_1202hh` returns a full map for r132, r134 and r139
    (11, 8 and 9 entries) and every one of those runs stamped ZERO tables.
  * `register_table`. It merges `{**existing.metadata, **new}`, so an ordinary
    re-registration by a lane does not drop a stamp already stored.
The link that loses it lies between those two, and nothing records which -- so this does.

WHY IT MATTERS: the verdict is what stops the shape heuristic demoting published content.
A table with no `visibility` and a users FK beside another entity's FK reads as
per-user-private (#598), the endpoint is projected with an actor, and a route the contract
calls public answers 401. That chain cost r137 its whole run (81 minutes, $190) and r140
95 minutes of M1.1 -- see #1202y9 and #1202z0, which tell the lane about the symptom. This
is the instrument for the cause.

★ OBSERVATION ONLY. It appends after the loop, it is guarded, and it changes no decision --
the same contract as every other run-scoped ledger here (#1202uw, #1202xn, #1202w5).
"""
import ast
import inspect
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402

_SRC = inspect.getsource(RK)


def _finalize_src():
    tree = ast.parse(_SRC)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and "_z2_seen" in ast.dump(n)), None)
    assert fn is not None, "the stamping function no longer mentions _z2_seen"
    return ast.get_source_segment(_SRC, fn) or ""


def test_the_stamp_is_counted_where_it_happens():
    """The ledger must record what the LOOP did, not re-derive it afterwards from the
    registry — a re-derivation would report the registry's final state and miss exactly the
    case this exists for (stamped here, gone later)."""
    src = _finalize_src()
    assert "_z2_seen.append" in src
    i_stamp = src.index('table_meta["visibility"] = _v1202hh')
    i_count = src.index("_z2_seen.append")
    assert 0 < i_count - i_stamp < 200, "the count must sit beside the stamp"


def test_the_ledger_names_the_gap_not_only_a_count():
    """★ #1202wc's lesson, one ledger over: a record that says a number and not WHICH ones
    cannot be acted on. `declared_but_unstamped` is the whole point — a declaration whose
    table was in this very batch and still did not get the verdict."""
    src = _finalize_src()
    assert '"declared_but_unstamped"' in src
    for key in ('"spec_map"', '"spec_names"', '"tables_seen"', '"stamped"', '"resume"'):
        assert key in src, key


def test_the_gap_is_computed_against_this_batch():
    """Not against the registry: a declaration whose table this kickoff never saw is a
    different fact (the entity never became a table) and must not be reported as a lost
    stamp.

    Asserted over the value NODE rather than a slice of text after the key. #943 caught the
    first draft doing `src[i:i + 400]` — and it was right to: the window is only correct
    until the record grows a field, at which point it starts reading the next entry's
    expression and the test means something else without changing.
    """
    tree = ast.parse(_finalize_src().lstrip())
    value = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "declared_but_unstamped":
                value = v
    assert value is not None, "the record no longer carries `declared_but_unstamped`"
    names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
    assert "_names1202z2" in names, sorted(names)
    assert "_z2_seen" in names, sorted(names)
    assert "_vis1202hh" in names, sorted(names)


def test_it_is_observation_only():
    """No branch OUTSIDE the instrument may read it back — the moment a decision depends on
    the ledger, a failed write becomes a behaviour change.

    Scoped to the outside on purpose: the instrument has one guard of its own (an empty run
    root must not write `logs/` into the process's cwd), and a scan that counted that as a
    decision would forbid the very care this asks for. My first draft did exactly that.
    """
    assert _SRC.count("spec_visibility_1202z2") <= 2, (
        "the ledger name appears more than at its write site and its warn key")
    tree = ast.parse(_SRC)
    own = [n for n in ast.walk(tree)
           if isinstance(n, ast.Try) and "_e1202z2" in ast.dump(n)]
    assert own, "the instrument's own try block is gone"
    inside = {id(x) for t in own for x in ast.walk(t)}
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.If) and "1202z2" in ast.dump(node.test):
            raise AssertionError(
                "a decision outside the instrument branches on it: %s"
                % ast.dump(node.test)[:120])


def test_a_write_failure_is_announced_not_swallowed():
    """★ The user's standing rule: a fallback that hides a failure is worse than none. An
    instrument that silently stops writing makes a run that lost every verdict look exactly
    like one that kept them — which is the very confusion it exists to end."""
    tree = ast.parse(_finalize_src().lstrip())
    handler = next((h for n in ast.walk(tree) if isinstance(n, ast.Try)
                    for h in n.handlers
                    if h.name == "_e1202z2"), None)
    assert handler is not None, "the instrument's except clause is gone"
    # the CALL, not merely the name: my first draft asserted `"warn_once_1201" in src`,
    # which survived deleting the import because the call below still spelled the word.
    calls = [c for c in ast.walk(handler) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "warn_once_1201"]
    assert calls, "the handler does not CALL warn_once_1201"
    assert any(isinstance(a, ast.Name) and a.id == "_e1202z2"
               for c in calls for a in c.args), "the exception itself is not passed on"
    imported = [n for n in ast.walk(handler) if isinstance(n, ast.ImportFrom)
                and any(a.name == "warn_once_1201" for a in n.names)]
    assert imported, "the call has no import to resolve — it would raise NameError"


def test_the_write_is_guarded_on_a_real_root():
    """`hubs.base_dir` has been wrong before: `_spec_visibility_1202hh`'s own docstring
    records a draft that derived `<project>/shared` and resolved to a path that never
    exists. An empty root must not write `logs/` into the process's cwd."""
    src = _finalize_src()
    assert 'str(_root1202z2) not in ("", ".")' in src


def test_the_ledger_line_is_valid_json_for_every_field_it_writes(tmp_path):
    """The record is built from names and flags; nothing in it may be a value json cannot
    serialise, or the whole line is lost at the moment it is needed."""
    rec = {"at": 1.0, "spec_map": 3, "spec_names": ["a", "b"], "tables_seen": 4,
           "stamped": ["a"], "declared_but_unstamped": ["b"], "resume": False}
    line = json.dumps(rec)
    assert json.loads(line) == rec


def test_the_loader_is_still_read_once_outside_the_loop():
    """The ledger reports `spec_map`, which is only meaningful while the map is read once
    for the whole batch — a per-table read would make the number a property of the last
    table rather than of the run."""
    src = _finalize_src()
    assert src.count("_spec_visibility_1202hh_lazy()") == 1, src.count(
        "_spec_visibility_1202hh_lazy()")
    i_load = src.index("_vis1202hh = _spec_visibility_1202hh_lazy()")
    i_loop = src.index("for tbl in tables:")
    assert i_load < i_loop
