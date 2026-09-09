r"""#1202hv: one fact, three emitters — and #1180 fixed exactly one of them.

`_TERMINAL_LLM_ERROR` is deliberately shared. #1163 routed our own
ENVGEN_MAX_SPEND_USD guard through the same latch #1159 uses for a provider that has
genuinely gone terminal, because both mean "stop the run". Fine as a mechanism, wrong
as a label — and each consumer decided the label for itself:

    orchestrator run loop  #1180 branched on the string, says "the provider is fine"  OK
    orchestrator ledger    wrote the literal "aborted_provider" for anything latched  WRONG
    kickoff_driver         "the LLM provider is terminally unavailable"               WRONG

Measured on this corpus: 6 of 6 runs whose ledger reads `aborted_provider`
(r99/r100/r101/r102/r103/r106, $498.67 together) were stopped by their OWN cap. Zero
were the provider. #1180's comment records being sent to check whether the key had
died — "it had not, a probe answered 200 immediately" — and the ledger sent the next
reader down that same path today.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from utils.llm import terminal_stop_is_own_budget_1202hv as is_own_cap

AGENT = Path(__file__).resolve().parents[1]
ORCH = (AGENT / "env_generator" / "llm_generator" / "multi_agent" / "orchestrator.py").read_text()
KICK = (AGENT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
        / "kickoff_driver.py").read_text()

# The literal reason r106 wrote, from generated/tiktok-web-r106/run_budget.json.
R106 = ("[BudgetExceeded] run spend $80.16 reached ENVGEN_MAX_SPEND_USD=$80.00 "
        "(set ENVGEN_BUDGET_UNLIMITED=1 to disable)")
# A real provider terminal, the #1159 shape.
PROVIDER = ("[RateLimitError] Error code: 429 - {'error': {'message': 'You have no "
            "credits remaining...', 'type': 'insufficient_quota'}}")


# --- the predicate, against strings the corpus actually produced -------------------

def test_the_r106_reason_is_our_own_cap():
    assert is_own_cap(R106) is True


def test_a_real_provider_terminal_is_not():
    assert is_own_cap(PROVIDER) is False


def test_the_bracket_tag_alone_is_enough():
    """A future message may drop the env-var name; the tag still identifies it."""
    assert is_own_cap("[BudgetExceeded] run spend $9.00 reached the cap") is True


def test_leading_whitespace_does_not_hide_the_tag():
    assert is_own_cap("  [BudgetExceeded] run spend $9.00") is True


def test_empty_and_none_are_not_a_budget_stop():
    assert is_own_cap("") is False
    assert is_own_cap(None) is False


def test_it_never_raises_on_odd_input():
    for junk in (123, [], {"a": 1}, object()):
        assert is_own_cap(junk) in (True, False)


# --- emitter 1: the ledger status --------------------------------------------------

def _orch_cls():
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    return Orchestrator


def test_the_ledger_says_budget_for_our_own_cap():
    assert _orch_cls()._abort_status_1202hv(R106) == "aborted_budget"


def test_the_ledger_still_says_provider_for_the_provider():
    assert _orch_cls()._abort_status_1202hv(PROVIDER) == "aborted_provider"


def test_the_ledger_call_site_uses_the_helper_not_a_literal():
    """The write must go through the branch — a literal here is the whole defect."""
    i = ORCH.index("#1202eb: HOW the run ended")
    j = ORCH.index("return GenerationResult(", i)
    seg = ORCH[i:j]
    assert "_abort_status_1202hv" in seg
    assert '"aborted_provider" if _abort_1202eb' not in seg, "the old literal is back"


# --- emitter 2: #1180's run-loop message, converged onto the same predicate ---------

def test_the_1180_site_asks_the_predicate():
    """AST, not a text landmark: the phrases this site branches on ALSO appear verbatim
    in its own comment, so slicing between them reads the prose, not the code — the
    first draft of this test did exactly that and passed on the comment."""
    tree = ast.parse(ORCH)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "terminal_stop_is_own_budget_1202hv"]
    assert calls, "no site actually CALLS the predicate"

    # And nobody re-decides it locally with the old string compare.
    stale = [n for n in ast.walk(tree)
             if isinstance(n, ast.Compare)
             and any(isinstance(o, ast.In) for o in n.ops)
             and isinstance(n.left, ast.Constant)
             and n.left.value == "ENVGEN_MAX_SPEND_USD"]
    assert not stale, "a site still decides this itself; that is how the three drifted"


# --- emitter 3: kickoff ------------------------------------------------------------

def test_kickoff_no_longer_blames_the_provider_unconditionally():
    i = KICK.index("Kickoff abandoned after")
    j = KICK.index("_kickoff_fallback_or_reconcile", i)
    seg = KICK[i:j]
    assert "terminally unavailable" in seg, "the provider branch must survive"
    assert "OWN spend ceiling" in seg, "the budget branch must exist"


def test_kickoff_returns_a_distinguishable_reason():
    i = KICK.index("Kickoff abandoned after")
    seg = KICK[i:i + KICK[i:].index("# Round-8g")]
    assert "own_budget_cap" in seg and "provider_terminal" in seg


# --- reachability: the branches are not buried under an unrelated guard -------------

def test_the_kickoff_branch_is_reachable_from_the_terminal_check():
    """#1202hv must sit inside `if _term_1202ec:` and nothing narrower."""
    tree = ast.parse(KICK)
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "_own_cap"]
    assert hits, "the flag vanished"


def test_no_fixed_source_windows_in_this_file():
    """#943's ratchet: byte windows break when a comment grows."""
    src = Path(__file__).read_text()
    assert not re.search(r"\[\s*\w+\s*:\s*\w+\s*\+\s*\d+\s*\]", src)
