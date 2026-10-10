"""#1203h1: "The failing run is recorded" named an artifact this path never writes.

`RunValidationTool._record_runhub_run` returns early on a failing report --
`if not report.get("passed"): return None` -- with a stated reason ("else the partial endpoint
list could understate failures"). So a FAILING validation deliberately records no RunHub run,
while the pre-cut smoke's hold message told its reader one was there.

Measured over every run log on disk: 46 of these holds across 31 runs, and in 15 of those runs
RunHub holds no failed run at all. A reader sent to look for one finds nothing about half the
time and cannot tell "never written" from "written and I missed it".

The evidence is durable, just elsewhere: `_fresh_smoke_hold_reason_1202wc` lands in
`logs/delivery_hold.jsonl` as a `fresh_smoke` record carrying the failing check and its detail
(r172's 04:03:27 entry names the chain and the 401 behind it). #1203fz's class — copy that
names something that does not exist — and #1202tk's rule: a run log is not kept.
"""
import ast
import inspect
from pathlib import Path

FWVAL = (Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent/runtime/framework_validation.py")
VTOOLS = (Path(__file__).resolve().parents[1]
          / "env_generator/llm_generator/tools/validation_tools.py")


def _hold_message() -> str:
    """The `RELEASE HELD ... FAILS a fresh api_smoke` format string, from the AST."""
    tree = ast.parse(FWVAL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        txt = ast.unparse(node)
        if "FAILS a fresh api_smoke" in txt and "RELEASE HELD" in txt:
            return txt
    raise AssertionError("the pre-cut smoke hold message was not found")


def test_the_message_no_longer_claims_a_runhub_run():
    msg = _hold_message()
    assert "The failing run is recorded" not in msg, msg


def test_the_message_names_where_the_evidence_actually_is():
    msg = _hold_message()
    assert "delivery_hold.jsonl" in msg, msg
    assert "fresh_smoke" in msg, msg


def test_the_message_says_no_runhub_run_is_written():
    """Not just silence about it: a reader who expects one has to be told it is absent."""
    msg = _hold_message()
    low = msg.lower()
    assert "runhub" in low, msg
    assert "records none" in low or "not as a runhub run" in low, msg


def test_the_claim_is_false_BY_CONSTRUCTION_in_the_recorder():
    """The premise, pinned where it lives, so this ticket cannot rot silently.

    If `_record_runhub_run` ever starts recording failing runs, the message should change back
    and this test is the place that says so.
    """
    src = VTOOLS.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_record_runhub_run")
    early = [n for n in ast.walk(fn)
             if isinstance(n, ast.If) and "passed" in ast.unparse(n.test)
             and "return None" in ast.unparse(n)]
    assert early, (
        "`_record_runhub_run` no longer refuses a failing report; if it now records failing "
        "runs, #1203h1's message should name the RunHub run again")


def test_the_hold_reason_is_still_set_so_the_ledger_entry_exists():
    """The replacement sentence has to be TRUE: the ledger record must still be written."""
    src = FWVAL.read_text(encoding="utf-8")
    i = src.index("FAILS a fresh api_smoke")
    tail = src[i:i + 4000]
    assert "_fresh_smoke_hold_reason_1202wc" in tail, (
        "the message points at the hold ledger, so the reason that lands there must be set "
        "on the same path")
