"""#1202cc — a capture that raced the compose stack is not a judgment.

`capture_unavailable` required ZERO photographs, so a round that captured some screens and
had the rest refused was scored as a REAL verdict with the refused ones at 0.00.

r35 live, 10:59:45: the verifier's run_validation ran `docker compose down -v
--remove-orphans` (a 37s down/build/up cycle) while the capture was walking the routes. 13
screens photographed and scored 0.34-0.82, 12 raised ERR_CONNECTION_REFUSED in the same
second, the round reported 0.0592 against a 0.6000 bar, delivery deferred, one of three
per-source attempts burnt -- on an app whose next round scored 0.4538.

LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import _CONNECTION_ERR_1202CC  # noqa: E402

REFUSALS = (
    "Error: Page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:8056/my-list",
    "net::ERR_CONNECTION_RESET",
    "net::ERR_EMPTY_RESPONSE",
    "net::ERR_NAME_NOT_RESOLVED",
    "connect ECONNREFUSED 127.0.0.1:8056",
)

# Failures that say something about the PAGE, not the transport. #768r is explicit that
# these must keep counting against the app.
NOT_TRANSPORT = (
    "Timeout 30000ms exceeded waiting for selector",
    "TypeError: (void 0) is not a function",
    "the SPA never hydrated — route rendered BLANK",
    "Error: Page.goto: net::ERR_ABORTED",
    "playwright binary is missing and cannot be installed",
)


def test_the_r35_refusal_is_recognised():
    """The exact string r35 logged 12 times in one second."""
    assert _CONNECTION_ERR_1202CC.search(REFUSALS[0])


def test_every_transport_failure_is_recognised():
    for e in REFUSALS:
        assert _CONNECTION_ERR_1202CC.search(e), e


def test_page_level_failures_are_not_treated_as_transport():
    """THE control. Widening this pattern to catch a render failure would reopen #542's
    hole: a canonical page that fails to load would stop counting and the gate would pass a
    partial exam."""
    for e in NOT_TRANSPORT:
        assert not _CONNECTION_ERR_1202CC.search(e), e


def test_the_branch_requires_both_photographs_and_refusals():
    """The whole justification: a server cannot be serving and refusing at once, so the
    combination is what proves the stack moved. Either alone must not trigger it -- zero
    photographs is the pre-existing branch, and refusals with no successes is that branch
    too. #943: landmark anchors."""
    src = (LLM / "multi_agent" / "runtime" / "visual_fidelity.py").read_text(encoding="utf-8")
    i = src.index("_refused_1202cc = sorted(")
    guard = src[i:src.index("return {", i)]
    assert "if shots and _refused_1202cc:" in guard


def test_the_pre_existing_zero_capture_branch_still_comes_first():
    """A round that photographed nothing keeps its own #949 message, which names the actual
    exception; #1202cc must not swallow that case.

    #1203pg RE-AIMED this, structurally. The old form compared `src.index` of the message
    literal against `src.index("_refused_1202cc = sorted(")`, and that literal moved into
    `_capture_unavailable_summary_1203pg` when #949's sentence was given an owner. Switching
    the landmark to the helper's NAME would have been worse than useless: the helper is DEFINED
    above `run_visual_fidelity`, so the index would find the `def` and the assertion would hold
    no matter where the branch sat. Compare the statements themselves.
    """
    import ast
    import inspect
    from multi_agent.runtime import visual_fidelity as _vf
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(_vf)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "run_visual_fidelity")
    # BOTH branches return `capture_unavailable: True` — #1202cc's own does too, which is how
    # the caller bounds its refund. So the key alone does not identify the zero-capture one;
    # the first version of this re-aim asserted there was exactly one and was simply wrong.
    # The zero-capture branch is the one that builds #949's sentence.
    zero = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
            and isinstance(n.value, ast.Dict)
            and "capture_unavailable" in {k.value for k in n.value.keys
                                          if isinstance(k, ast.Constant)}
            and any(getattr(c.func, "id", "") == "_capture_unavailable_summary_1203pg"
                    for c in ast.walk(n) if isinstance(c, ast.Call))]
    refused = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_refused_1202cc" for t in n.targets)]
    assert len(zero) == 1, (
        "expected exactly one return built from #949's summary, found %d" % len(zero))
    assert len(refused) == 1, "the #1202cc guard moved or multiplied: %d" % len(refused)
    assert zero[0].lineno < refused[0].lineno, (
        "#1202cc now runs before the zero-capture branch and would swallow it")


def test_the_refund_stays_bounded():
    """An app that is genuinely down satisfies this every round; without the cap the gate
    would never count an attempt and the run would spin to wall-clock (the #655b lesson).
    The branch returns capture_unavailable, which the caller already bounds."""
    src = (LLM / "multi_agent" / "runtime" / "visual_fidelity.py").read_text(encoding="utf-8")
    i = src.index("_refused_1202cc = sorted(")
    body = src[i:src.index('"min_similarity": min_similarity}', i) + 40]
    assert '"capture_unavailable": True' in body
    assert "_TRANSIENT_REFUND_CAP" in src
