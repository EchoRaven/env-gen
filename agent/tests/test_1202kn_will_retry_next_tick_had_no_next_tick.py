"""#1202kn: "attempt refunded, will retry next tick" — there was no next tick.

The visual gate refunds a capture that found the app unreachable or mid-rebuild (#655b, #75a)
and its own log line promises the retry:

    "Visual fidelity: %s — attempt refunded, will retry next tick (unreachable %s/%s)."

Nothing retried. `_maybe_run_visual_fidelity` has exactly three call sites and all three sit
downstream of a CLEAR delivery gate: two in `_maybe_framework_deliver`'s release-decision
branch, and one in `framework_validation` that fires only on an api_smoke PASS. While any
unrelated check is red, none of them runs, so the refunded attempt is never retaken.

tiktok-r115, live, is the worked case. api_smoke passed ONCE at 16:09 and drove the gate; the
capture landed in a rebuild window and was correctly refunded — `unreachable_refunds: 1`.
Twenty-two minutes and thirteen coordination ticks later the state file still read

    "total_judgments": 0, "last_judged_sig": null, "attempts": 0

while `deliverability_ui_flow_failed` held the gate red. The run had never judged a single
screen. r114, for comparison, had its first verdict at ~22 minutes.

`_maybe_framework_deliver` IS the tick — it runs every cycle — so the promise is honoured
there, in the branch that previously just logged the red checks and returned.

WHAT IS VERIFIED: the retry fires only when a refund is outstanding AND nothing has been judged
this milestone; it does not fire on a clear gate (the existing drivers own that path), nor once
a judgment exists, nor with no gate instance; and it can never break the delivery loop.

WHAT IS NOT: that it adds judging budget. `maybe_run` still self-guards on the pass latch, the
`attempts >= 3` cap and an unchanged signature, and `_TRANSIENT_REFUND_CAP` bounds how often a
capture may be excused at all. This re-takes an attempt the framework had already decided not
to charge for — it does not grant a new one.

This is the same shape as #102 ("drive ONE final fresh capture before releasing" — measured not
to happen in 56% of releases) and #1202ju ("cannot drift from the endpoints" — it had drifted):
a comment stating a guarantee that no code delivers. See the standing rule that an absolute
claim in a comment is a testable hypothesis.
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


def _deliver_src():
    from multi_agent import orchestrator as O
    return textwrap.dedent(inspect.getsource(O.Orchestrator._maybe_framework_deliver))


def _retry_guard():
    """The `if` that guards the #1202kn retry, read from the parse tree (#923: never a source
    span ending on a bare delimiter)."""
    tree = ast.parse(_deliver_src())
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "_vf1202kn" not in names:
            continue          # the pre-existing `_vf_decision == 'defer'` driver, not this one
        for stmt in node.body:
            call = getattr(stmt, "value", None)
            if (isinstance(call, ast.Await)
                    and isinstance(call.value, ast.Call)
                    and isinstance(call.value.func, ast.Attribute)
                    and call.value.func.attr == "_maybe_run_visual_fidelity"):
                return ast.unparse(node.test)
    raise AssertionError("no #1202kn retry guarding _maybe_run_visual_fidelity")


def test_the_refund_promises_a_retry():
    """★ The premise, quoted from the shipped code — if this line ever goes, the defect this
    fixes goes with it and the test should be reconsidered, not silently kept."""
    from multi_agent.runtime import visual_fidelity as VF
    src = inspect.getsource(VF)
    assert "attempt refunded, will retry next tick" in src


def test_the_retry_exists_in_the_blocked_branch():
    """★ The fix. It must live where the gate is RED — the clear path already has drivers."""
    src = _deliver_src()
    i = src.index('if gate.get("failed_checks"):')
    j = src.index("_maybe_run_visual_fidelity", i)
    assert "#1202kn" in src[i:j], "the retry must sit inside the failed-checks branch"


def test_it_fires_only_when_nothing_has_been_judged():
    """★ Scope: a gate that HAS judged is converging normally and must not be re-driven here."""
    g = _retry_guard()
    assert "total_judgments" in g and "== 0" in g.replace("'", ""), g


def test_it_fires_only_when_a_refund_is_outstanding():
    """★ Scope: without a refund there is no promise to honour, and driving the gate on every
    red tick would change the cost model."""
    g = _retry_guard()
    assert "unreachable_refunds" in g and "transient_refunds" in g, g


def _retry_try_node():
    """The `try` wrapping the #1202kn retry, from the parse tree.

    Deliberately NOT a source span: the comment above the retry quotes
    `_maybe_run_visual_fidelity` in prose, so `src.index(...)` lands inside the comment and a
    span test 'passes' or 'fails' on the wrong region entirely — the same #923 shape that bit
    test_1202kk and test_1202hh today."""
    tree = ast.parse(_deliver_src())
    cands = [n for n in ast.walk(tree) if isinstance(n, ast.Try)
             and "_vf1202kn" in {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}]
    assert cands, "the #1202kn retry is not wrapped in a try"
    # INNERMOST: the whole method is itself wrapped in a try, which also "contains" the retry.
    # Shortest source wins.
    return min(cands, key=lambda n: len(ast.unparse(n)))


def test_it_requires_an_existing_gate_instance():
    """`_vf_gate` is a lazy property — touching it here would CONSTRUCT the gate on a run that
    never had one, which is a side effect this branch must not have."""
    node = _retry_try_node()
    body = ast.unparse(node)
    assert "_vf_gate_instance" in body, "must read the already-built instance"
    assert "self._vf_gate\n" not in body and "self._vf_gate " not in body, (
        "must not touch the lazy property, which would construct a gate")
    assert "_vf1202kn is not None" in _retry_guard()


def test_the_retry_cannot_break_the_delivery_loop():
    """Same contract every best-effort repair in this file keeps: a retry must never be the
    reason delivery stops being attempted."""
    node = _retry_try_node()
    assert node.handlers, "the retry must have an except clause"
    h = node.handlers[0]
    assert isinstance(h.type, ast.Name) and h.type.id == "Exception"
    assert "#1202kn retry skipped" in ast.unparse(h), ast.unparse(h)[:200]


def test_the_gate_still_self_guards():
    """★ The cost argument, checked rather than asserted: `maybe_run` returns early on the pass
    latch, the attempt cap and an unchanged signature, so re-driving it cannot buy extra
    judgments."""
    from multi_agent.runtime import visual_fidelity as VF
    src = inspect.getsource(VF.VisualFidelityGate.maybe_run)
    assert "if self.passed:" in src
    assert "if self.attempts >= 3:" in src
    assert "sig == self.last_judged_sig" in src


def test_r115s_recorded_state_would_have_triggered_it():
    """★ The live case, replayed from the state r115 actually persisted."""
    class _G:
        total_judgments = 0
        unreachable_refunds = 1
        transient_refunds = 0
    g = _retry_guard()
    ok = eval(g, {"getattr": getattr}, {"_vf1202kn": _G()})   # noqa: S307 — the shipped guard
    assert bool(ok) is True

    class _Judged(_G):
        total_judgments = 4
    assert bool(eval(g, {"getattr": getattr}, {"_vf1202kn": _Judged()})) is False   # noqa: S307

    class _NoRefund(_G):
        unreachable_refunds = 0
    assert bool(eval(g, {"getattr": getattr}, {"_vf1202kn": _NoRefund()})) is False  # noqa: S307

    assert bool(eval(g, {"getattr": getattr}, {"_vf1202kn": None})) is False        # noqa: S307
