"""#1202wi: a check that can stop a release must record WHAT it failed on.

`blocker_prose` (#983) is fed exclusively from `compute_deliverability`'s blockers, so by
construction the `deliverability_*` family names its instances and the validation / chain /
task family never does. MEASURED over the recent gate ledgers, comparing each entry's
`failed_checks` against its `blocker_prose`: 11 check kinds carry no prose at all, 2123
occurrences -- validation_ui_evidence_failed 1001, business_chain_failing 368,
incomplete_required_tasks 245, verification_checklist_not_ready 166,
contract_alignment_failed 116, unresolved_failed_tasks 98.

Every one of the five wired here already had its instances in scope inside
`validate_delivery_gate`:
  * business_chain_failing     -- its producer returns {"reason", "detail"} and the detail,
                                  already formatted as "N chain(s) have NOT passed: <names>",
                                  was discarded; only `reason` was ever read.
  * incomplete_required_tasks  -- `_by1009` (reason -> task names), sent to logger and nowhere
  * verification_checklist_not_ready -- `#585`'s `_seen`/`_when`, same
  * contract_alignment_failed  -- `contract_report["errors"]`, one line above the append
  * unresolved_failed_tasks    -- `_bugs743["failed"]`

Two of the five fire before the deliverability block runs, which is why the collector is
declared at the top of the function and merged at the end rather than written into
`deliverability_blocker_prose` directly.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.delivery_gate import _merged_prose_1202wi  # noqa: E402

_GATE = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                     "delivery_gate.py")

# The checks measured as carrying no prose whose instances are in scope at the append site.
_WIRED = ("business_chain_failing", "incomplete_required_tasks",
          "verification_checklist_not_ready", "contract_alignment_failed",
          "unresolved_failed_tasks",
          # #1202ws: the sixth. #1202wi's survey ran over a SUBSET of the gate ledgers
          # (r13*/r3*) and undercounted the whole class ~5x -- 2123 across 11 kinds became
          # 10,816 across 24 once all 83 were read -- which is how this one was missed. Its
          # instances go to `logger` eight at a time and nowhere else; 311 occurrences
          # across 8 runs, most recent r121.
          "business_response_key_noncanonical")


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _gate_fn():
    tree = ast.parse(_read(_GATE))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "validate_delivery_gate"), None)
    assert fn is not None, "validate_delivery_gate not found"
    return fn


def _noted_checks():
    """Every check name handed to the collector, read structurally from the call sites."""
    out = set()
    for node in ast.walk(_gate_fn()):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_note1202wi" and node.args):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.add(arg.value)
        elif isinstance(arg, ast.Subscript):
            # `business_chain_block["reason"]` -- the name is chosen at runtime from the
            # same dict the failed_check is appended from, so it is that check by
            # construction. Record it under the token this repo uses for it.
            out.add("business_chain_failing")
    return out


def test_each_measured_check_now_records_an_instance():
    noted = _noted_checks()
    missing = sorted(c for c in _WIRED if c not in noted)
    assert not missing, (
        "these checks can still stop a release while recording only that they failed: %r"
        % missing)


def test_the_collector_reaches_the_verdict():
    """A collector nothing merges is a measurement that never left, which is #947's rule."""
    src = _read(_GATE)
    tree = ast.parse(src)
    merged = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, val in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "blocker_prose"):
                continue
            assert isinstance(val, ast.Call), (
                "blocker_prose must be the MERGED map, not the deliverability half: %s"
                % ast.unparse(val))
            assert getattr(val.func, "id", "") == "_merged_prose_1202wi", ast.unparse(val)
            merged = True
    assert merged, "the verdict does not carry a blocker_prose key at all"


def test_the_business_chain_detail_is_read_off_the_result():
    """★ Its producer formatted the instance and the call site dropped it on the floor."""
    src = ast.unparse(_gate_fn())
    assert "business_chain_block.get('detail')" in src or \
           'business_chain_block.get("detail")' in src, (
        "the reason was read and the detail beside it was not")


def test_merge_keeps_both_sides():
    got = _merged_prose_1202wi({"a": ["from deliverability"]},
                               {"a": ["from the gate"], "b": ["only here"]})
    assert got == {"a": ["from deliverability", "from the gate"], "b": ["only here"]}, got


def test_merge_does_not_mutate_its_input():
    left = {"a": ["x"]}
    _merged_prose_1202wi(left, {"a": ["y"]})
    assert left == {"a": ["x"]}, "the caller's map must not grow under it: %r" % left


def test_merge_tolerates_empty_sides():
    assert _merged_prose_1202wi(None, None) == {}
    assert _merged_prose_1202wi({}, {"a": ["x"]}) == {"a": ["x"]}
    assert _merged_prose_1202wi({"a": ["x"]}, {}) == {"a": ["x"]}
