"""#1174: quota exhaustion is not always permanent.

#1159 was right that a 429 saying "no credits" must not be retried like a
throttle -- r15 spent 2h50m doing exactly that. It was wrong that the condition
never recovers. Measured across three runs on the same account:

    r16   01:12:10 -> 01:13:07     57 SECONDS, then the balance was back
    r15   08:42:50 -> 11:44:19     3h01m, never recovered in-run
    r14   02:34:32 -> 08:19:52     5h45m of intermittent outages -- and r14
                                   still DELIVERED, so it recovered repeatedly

r16 was killed by the 57-second one. It was at ONE failing gate check with $262
already spent, and the key answered HTTP 200 again minutes later.

So the outage gets a grace window: hold the first quota error, let the retry
path work, and latch terminal only once it has PERSISTED. r15 still aborts ~5
minutes in rather than 2h50m; r16 survives.
"""
import os
import time

import pytest

import utils.llm as L


class _Err(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        if status is not None:
            self.status_code = status


# verbatim shape from netflix-r16b.log
QUOTA = ("Error code: 429 - {'error': {'message': 'You have no credits remaining. "
         "Add credits to continue using the API at ...', "
         "'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'}}")


@pytest.fixture(autouse=True)
def clean():
    os.environ["ENVGEN_QUOTA_GRACE_S"] = "2"
    L._QUOTA_FIRST_SEEN_1174["at"] = None
    yield
    os.environ.pop("ENVGEN_QUOTA_GRACE_S", None)
    L._QUOTA_FIRST_SEEN_1174["at"] = None


def test_the_first_outage_is_not_terminal():
    """r16's 57-second blip must not kill a run at one failing check."""
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is False
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is False


def test_a_persistent_outage_still_aborts():
    """r15's protection: 2h50m of spinning is the thing this must never allow."""
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is False
    time.sleep(2.1)
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is True


def test_a_success_resets_the_clock():
    """Otherwise an early blip spends a much later outage's grace window and the
    second one latches instantly -- r14 had 5h45m of INTERMITTENT outages and
    still delivered."""
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is False
    time.sleep(2.1)
    L._record_usage_1163(10, 0, 1)
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is False


def test_hard_auth_never_waits():
    """401/403 does not recover by waiting, so it must not get a grace window."""
    assert L._is_terminal_llm_error(_Err("Error code: 401 - invalid api key", 401)) is True


def test_a_real_throttle_is_still_retryable():
    assert L._is_terminal_llm_error(
        _Err("Error code: 429 - Rate limit reached for gpt-5.5", 429)) is False


def test_zero_grace_restores_1159_exactly():
    """The escape hatch: an account known to be dead can abort on the first error."""
    os.environ["ENVGEN_QUOTA_GRACE_S"] = "0"
    L._QUOTA_FIRST_SEEN_1174["at"] = None
    assert L._is_terminal_llm_error(_Err(QUOTA, 429)) is True


def test_a_bad_grace_value_falls_back_to_the_default():
    os.environ["ENVGEN_QUOTA_GRACE_S"] = "not-a-number"
    assert L._quota_grace_1174() == 300.0
