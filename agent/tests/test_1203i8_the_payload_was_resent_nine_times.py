"""#1203i8: a 400 that says the image is unparseable was retried as if transient.

`image_parse_error` is 1184 of the 1190 HTTP 400s in the whole corpus, and every one
of them was re-sent. In tiktok-web-r183 the backend agent's conversation acquired one
at 22:21:24 and failed 40 consecutive LLM-layer attempt-triples until 22:25:54 --
3 LLM attempts under the agent loop's own tries = 9 identical re-sends per call, 120
retries, 122.8s of sleep, a 100% failure rate and no successes. When the budget ran
out the agent had lost its kickoff contribution, and the substance gate reported that
as the agent having "no substantive endpoint + data-model/table decisions".

That it is the PAYLOAD and not the image is established and not assumed: all 11
reference PNGs were written at 22:16:21, never rewritten, decode cleanly, declare a
media type matching their magic bytes, fit under the per-image cap after the
framework's own `_fit_image_b64`, and the same 8.5MB of base64 was accepted by the
same endpoint on replay. The frontend agent viewed the same files in the same minutes
and its calls succeeded.

The error strings below are copied verbatim from the run logs. They are the PROVIDER's
wording, not the framework's, so a literal is the right anchor here -- the framework
cannot rename them, and a test that imported the framework's own marker tuple to build
its positive case would be asserting the constant against itself.
"""
import asyncio

import pytest

from utils.llm import _is_unchanged_payload_400_1203i8 as is_unchanged


class _Err(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        if status is not None:
            self.status_code = status


# verbatim from gm_tiktok_r183.log:489 (and 1024 more in gm_tiktok_r117.log)
R183_IMAGE = (
    "Error code: 400 - {'error': {'message': 'You uploaded an unsupported image. "
    "Please make sure your image is valid.', 'type': 'invalid_request_error', "
    "'param': None, 'code': 'image_parse_error'}}")

# the only other two 400s in the entire corpus -- both must stay retryable, because
# neither names a condition this rule has measured as unchanged-on-re-send.
OTHER_400S = [
    "Error code: 400 - {'error': {'message': 'something went wrong reading your request'}}",
    ("Error code: 400 - {'error': {'message': 'Invalid prompt: your prompt was flagged "
     "as potentially violating our usage policy.'}}"),
]


def test_the_corpus_image_400_is_recognised():
    assert is_unchanged(_Err(R183_IMAGE, status=400)) is True
    # status is not what identifies it: a wrapper that drops "Error code: 400" must not
    # make the condition invisible.
    assert is_unchanged(_Err(R183_IMAGE)) is True


@pytest.mark.parametrize("msg", OTHER_400S)
def test_the_other_corpus_400s_stay_retryable(msg):
    """A rule that answered True for every 400 would pass the test above and still be
    wrong. These are the real alternatives it has to leave alone."""
    assert is_unchanged(_Err(msg, status=400)) is False


@pytest.mark.parametrize("msg", [
    "Error code: 429 - {'error': {'message': 'Rate limit reached', 'type': 'rate_limit'}}",
    "Request timed out.",
    "Connection error.",
    "",
])
def test_transient_errors_stay_retryable(msg):
    assert is_unchanged(_Err(msg)) is False


def _client(attempts=3):
    """A real `OpenAIClient` with construction bypassed. The retry loop under test is
    the thing being measured, so it is NOT stubbed; only the provider SDK handshake in
    `__init__` is skipped, and the two attributes the loop reads are set explicitly.
    `retry_delay=0` keeps the backoff from sleeping the suite."""
    import logging

    from utils.config import LLMConfig, LLMProvider
    from utils.llm import OpenAIClient

    c = OpenAIClient.__new__(OpenAIClient)
    c.config = LLMConfig(provider=LLMProvider.OPENAI, model_name="m", api_key="k",
                         retry_attempts=attempts, retry_delay=0.0)
    c._logger = logging.getLogger("LLM.openai")
    return c


def _count_attempts(err):
    client = _client()
    calls = {"n": 0}

    async def _boom(*a, **k):
        calls["n"] += 1
        raise err

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(type(err)):
            loop.run_until_complete(client._retry_with_backoff(_boom))
    finally:
        loop.close()
    return calls["n"]


def test_the_llm_retry_loop_sends_it_once():
    """The whole point: one attempt, not three. Before the patch this made 3 calls."""
    n = _count_attempts(_Err(R183_IMAGE, status=400))
    assert n == 1, "an unchanged-payload 400 was re-sent %d times" % n


def test_the_llm_retry_loop_still_retries_a_transient_error():
    """The counter-control. If the no-retry path were reached for everything, the test
    above would pass against a loop that had simply stopped retrying anything."""
    n = _count_attempts(_Err("Connection error."))
    assert n == 3, "a transient error stopped being retried (%d attempt(s))" % n


def test_the_agent_retry_loop_does_not_resend_the_same_conversation():
    """The other half of the 9x multiplier: `call_with_retry` called `func` again with
    the identical history after the LLM layer had already given up on it."""
    import logging

    from utils.base_agent import AgentMetrics, BaseAgent

    class _Agent(BaseAgent):
        async def process_task(self, task):   # the one abstract method
            raise AssertionError("not exercised by this test")

    agent = _Agent.__new__(_Agent)
    agent._logger = logging.getLogger("test.agent")
    agent._metrics = AgentMetrics()
    agent._retry_config = {"max_retries": 3, "min_wait": 0.0, "max_wait": 0.0,
                           "multiplier": 1.0}

    calls = {"n": 0}

    async def _boom():
        calls["n"] += 1
        raise _Err(R183_IMAGE, status=400)

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(_Err):
            loop.run_until_complete(agent.call_with_retry(_boom))
    finally:
        loop.close()
    assert calls["n"] == 1, (
        "the agent loop re-sent the same conversation %d times" % calls["n"])

    # counter-control, same loop: a transient error must still get its three tries,
    # otherwise the assertion above is satisfied by a loop that retries nothing.
    calls["n"] = 0

    async def _flaky():
        calls["n"] += 1
        raise _Err("Connection error.")

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(_Err):
            loop.run_until_complete(agent.call_with_retry(_flaky))
    finally:
        loop.close()
    assert calls["n"] == 3, "a transient error stopped being retried (%d)" % calls["n"]


def test_each_marker_carries_its_own_weight():
    """The corpus string contains BOTH the provider's error code and its sentence, so a
    rule keyed on either one alone passes every test above. The redundancy is deliberate
    -- the provider can reword the sentence without changing the code, and has shipped
    the code `None` on other errors -- so each marker is exercised on its own here.
    Without this, dropping one marker is a mutation no test can see."""
    code_only = ("Error code: 400 - {'error': {'message': 'Bad image.', "
                 "'code': 'image_parse_error'}}")
    sentence_only = ("Error code: 400 - {'error': {'message': 'You uploaded an "
                     "unsupported image.', 'code': 'invalid_value'}}")
    assert is_unchanged(_Err(code_only, status=400)) is True
    assert is_unchanged(_Err(sentence_only, status=400)) is True


def test_a_terminal_error_still_latches_its_reason():
    """#1203i8 sits after #326/#1159 in the retry loop and must not shadow them: a
    terminal provider error has to keep reaching `_TERMINAL_LLM_ERROR` so the run loop
    can poll it and abort. If the new check were moved above the terminal test, an error
    that matched both would stop latching -- this pins that the terminal path is still
    the one that runs for a terminal error."""
    import utils.llm as _llm

    quota = ("Error code: 429 - {'error': {'message': 'You have no credits remaining.', "
             "'type': 'insufficient_quota', 'code': 'credit_balance_too_low'}}")
    assert is_unchanged(_Err(quota, status=429)) is False
    _llm._TERMINAL_LLM_ERROR["reason"] = None
    _llm._QUOTA_FIRST_SEEN_1174["at"] = None
    assert _llm._is_terminal_llm_error(_Err(quota, status=429)) is False  # grace
    assert _llm._is_terminal_llm_error(_Err(quota, status=401)) is True


def test_terminal_wins_when_an_error_matches_both():
    """Precedence, pinned with a hostile fixture.

    The #1203i8 check sits below #326's terminal test, and the comment there says a
    terminal error must still latch its reason. Nothing in the corpus matches both
    predicates, so moving the new check above the terminal one was a mutation that
    survived every other test in this file -- an ordering asserted in a comment and
    nowhere else. The invariant is real regardless of today's corpus: #326 exists so the
    run loop can poll `terminal_llm_error()` and abort instead of letting every lane
    spin rejected calls, and an error that merely happens to mention an image must not
    cost the run that signal.

    So construct the case the corpus does not supply: one error that satisfies both.
    Terminal has to win, which means the reason latches."""
    import utils.llm as _llm

    both = ("Error code: 400 - {'error': {'message': 'You uploaded an unsupported "
            "image.', 'type': 'insufficient_quota'}}")
    assert is_unchanged(_Err(both, status=400)) is True        # i8 matches
    assert _llm._is_terminal_llm_error(_Err(both, status=400)) is True   # and so does #326

    _llm._TERMINAL_LLM_ERROR["reason"] = None
    client = _client()
    calls = {"n": 0}

    async def _boom(*a, **k):
        calls["n"] += 1
        raise _Err(both, status=400)

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(_Err):
            loop.run_until_complete(client._retry_with_backoff(_boom))
    finally:
        loop.close()
    assert calls["n"] == 1, "either path should stop after one attempt"
    assert _llm._TERMINAL_LLM_ERROR["reason"], (
        "#1203i8 shadowed #326: the terminal reason never latched, so the run loop has "
        "nothing to poll and will spin rejected calls instead of aborting")
    _llm._TERMINAL_LLM_ERROR["reason"] = None
