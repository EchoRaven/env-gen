"""#1159: a 429 that says "no credits" is not a rate limit.

`_is_terminal_llm_error` returned False for ANY 429 before it looked at the
message, and OpenAI returns quota exhaustion AS a 429:

  Error code: 429 - {'error': {'message': 'You have no credits remaining...',
                     'type': 'insufficient_quota', 'code': 'credit_balance_too_low'}}

So the phrase list — which has carried "insufficient_quota" all along — was
never reached for the one provider whose billing errors arrive with that
status, `terminal_llm_error()` stayed None, and the orchestrator's abort path
(#326, "abort within one tick instead of letting every lane spin thousands of
rejected calls") never fired.

Measured: netflix-local-r15 hit its first quota error at 08:54:28 and kept
retrying until 11:44:19 — 2h50m against an account that could not recover,
322 x 429, zero milestones. r14 logged 837 of them across 6.8 hours.
"""
from pathlib import Path

import pytest

from utils.llm import _is_terminal_llm_error as is_terminal
from utils.llm import _TERMINAL_ERROR_PHRASES


class _Err(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        if status is not None:
            self.status_code = status


# verbatim from netflix-r15.log
R15 = ("Error code: 429 - {'error': {'message': 'You have no credits remaining. "
       "Add credits to continue using the API at "
       "https://platform.openai.com/settings/organization/billing/.', "
       "'type': 'insufficient_quota', 'param': None, "
       "'code': 'credit_balance_too_low'}}")


def test_the_error_that_burned_two_hours_fifty_is_terminal():
    """#1174 refined this: the message is still recognised, but a quota outage now
    gets a grace window before it counts as terminal, because r16 was killed by a
    57-SECOND one while sitting at a single failing gate check with $262 spent.
    r15's protection is unchanged -- it aborts once the outage PERSISTS, which is
    the case this test was written for (its outage ran 3h01m)."""
    import os
    import utils.llm as _L
    os.environ["ENVGEN_QUOTA_GRACE_S"] = "0"      # the pre-#1174 contract, verbatim
    _L._QUOTA_FIRST_SEEN_1174["at"] = None
    try:
        assert is_terminal(_Err(R15, 429)) is True
    finally:
        os.environ.pop("ENVGEN_QUOTA_GRACE_S", None)
        _L._QUOTA_FIRST_SEEN_1174["at"] = None


def test_a_persistent_outage_is_terminal_under_the_default_grace():
    """The r15 case as it now behaves: not on the first error, but once it lasts."""
    import time
    import os
    import utils.llm as _L
    os.environ["ENVGEN_QUOTA_GRACE_S"] = "1"
    _L._QUOTA_FIRST_SEEN_1174["at"] = None
    try:
        assert is_terminal(_Err(R15, 429)) is False
        time.sleep(1.1)
        assert is_terminal(_Err(R15, 429)) is True
    finally:
        os.environ.pop("ENVGEN_QUOTA_GRACE_S", None)
        _L._QUOTA_FIRST_SEEN_1174["at"] = None


def test_it_does_not_depend_on_the_status_attribute():
    """Provider wrappers do not always expose status_code."""
    assert is_terminal(_Err(R15)) is True


def test_a_real_rate_limit_stays_retryable():
    """Aborting a run on a transient throttle would be the worse defect."""
    assert is_terminal(_Err("Error code: 429 - Rate limit reached for gpt-5.5",
                            429)) is False


def test_geminis_resource_exhausted_stays_retryable():
    """The phrase list is deliberately NOT the generic "quota"/"exceeded",
    which appear in transient 429s."""
    assert is_terminal(
        _Err("429 ResourceExhausted: Quota exceeded for requests", 429)) is False
    assert "quota exceeded" not in [p.lower() for p in _TERMINAL_ERROR_PHRASES]


def test_hard_auth_is_still_terminal():
    assert is_terminal(_Err("Error code: 401 - invalid api key", 401)) is True


def test_a_timeout_is_not_terminal():
    assert is_terminal(_Err("LLM call exceeded 240s")) is False


def test_the_phrase_check_now_precedes_the_429_shortcut():
    """Anchored on the def, cut at the next def (#943) — the ORDER is the fix."""
    src = Path(__import__("utils.llm", fromlist=["x"]).__file__).read_text(
        encoding="utf-8")
    i = src.index("def _is_terminal_llm_error(")
    body = src[i:src.index("\ndef ", i + 1)]
    assert body.index("_TERMINAL_ERROR_PHRASES") < body.index("status == 429")
    assert "#1159" in body


def test_the_orchestrator_still_polls_it():
    """The abort path is what makes the classification worth anything."""
    from env_generator.llm_generator.multi_agent import orchestrator as orch
    src = Path(orch.__file__).read_text(encoding="utf-8")
    i = src.index("_term = _terminal_llm_error()")
    seg = src[i:src.index("break", i)]
    assert "budget_exceeded" in seg
