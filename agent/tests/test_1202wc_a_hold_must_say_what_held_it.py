"""#1202wc: every delivery hold the ledger records must say WHY, not only that it happened.

#1202tk added `logs/delivery_hold.jsonl` to answer the one question a run directory could
not: the gate was green, so what stopped the release? It records the hold's name, kind and
milestone -- and `detail` was optional.

MEASURED over r135, r136 and r137: 130 hold records, and **103 of them (79%) carry an empty
detail** -- every `gate_failed_checks` (103) and every `browser_ui_unusable` (6), while all
21 squad records carry one. r137 wrote 36 identical lines reading "gate_failed_checks,
blocking, 1.0.0" and nothing else, although the failing check names sat in the variable on
the line above the call.

So the rule is now structural: a hold is recorded WITH its reason. This is checked by AST
over the real call sites rather than by grep, because the question is whether a third
argument is actually passed to that call -- a name appearing nearby proves nothing.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_ORCH = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                     "orchestrator.py")
_FV = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                   "framework_validation.py")

_FN = "_note_delivery_hold_1202tk"


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu: a scanner closes what it opens
        return fh.read()


def _calls():
    tree = ast.parse(_read(_ORCH))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == _FN):
            continue
        hold = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            hold = node.args[1].value
        else:
            for kw in node.keywords:
                if kw.arg == "hold" and isinstance(kw.value, ast.Constant):
                    hold = kw.value.value
        has_detail = len(node.args) >= 3 or any(kw.arg == "detail" for kw in node.keywords)
        out.append((node.lineno, hold, has_detail))
    return out


def test_the_ledger_has_call_sites_to_check():
    """A rule over zero call sites is vacuous -- #1202tk names fourteen conditions."""
    calls = _calls()
    assert len(calls) >= 14, (
        "expected the fourteen holds #1202tk describes, found %d" % len(calls)
    )


def test_every_hold_is_recorded_with_a_reason():
    missing = [(line, hold) for line, hold, has in _calls() if not has]
    assert not missing, (
        "a hold that names itself and says nothing cannot answer why the run did not "
        "ship -- 79%% of r135/r136/r137's records were like this. Sites without a "
        "detail: %r" % (missing,)
    )


def test_each_distinct_hold_name_is_covered():
    """Not one site per name: every NAME must be reachable only with a reason attached."""
    by_name = {}
    for _line, hold, has in _calls():
        if hold is None:
            continue
        by_name.setdefault(str(hold), []).append(has)
    assert by_name, "no hold names resolved from the call sites"
    silent = sorted(n for n, flags in by_name.items() if not all(flags))
    assert not silent, "these hold names can still be written without a reason: %r" % silent


def test_the_fresh_smoke_reason_is_set_where_it_is_known():
    """Its call site sees only a bool, so both False paths must stash their reason.

    Asserted on the assignment's position relative to the `return False` it explains, not on
    the attribute name appearing somewhere in the file: a name that is never assigned before
    the return it belongs to would leave the ledger with the fallback string.
    """
    tree = ast.parse(_read(_FV))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
               and n.name == "ensure_fresh_smoke_before_cut"), None)
    assert fn is not None, "ensure_fresh_smoke_before_cut not found"

    def _sets_reason(node):
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            for tgt in sub.targets:
                if (isinstance(tgt, ast.Attribute)
                        and tgt.attr == "_fresh_smoke_hold_reason_1202wc"):
                    return sub.lineno
        return None

    # Every `return False` that is a real hold decision (not the fault handler, which
    # returns True) must be preceded by the reason assignment inside the same function.
    false_returns = [n.lineno for n in ast.walk(fn)
                     if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                     and n.value.value is False]
    assert len(false_returns) >= 2, (
        "expected both hold paths (unchanged failing tree, fresh smoke failed); found %r"
        % false_returns
    )
    assigns = sorted(sub.lineno for sub in ast.walk(fn)
                     if isinstance(sub, ast.Assign)
                     for tgt in sub.targets
                     if isinstance(tgt, ast.Attribute)
                     and tgt.attr == "_fresh_smoke_hold_reason_1202wc")
    assert len(assigns) >= len(false_returns), (
        "each hold path needs its own reason; %d assignment(s) for %d hold(s)"
        % (len(assigns), len(false_returns))
    )
    for ret in false_returns:
        assert any(a < ret for a in assigns), (
            "the `return False` at line %d is reached with no reason assigned before it"
            % ret
        )
