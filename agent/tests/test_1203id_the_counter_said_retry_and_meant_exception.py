"""#1203id: `retries` counted exceptions caught, not attempts re-sent.

`record_llm_retry_1202wr`'s own first sentence is "One failed attempt that WILL BE
RETRIED, and the seconds it burned". Its call site sat at the top of the `except` block,
above every guard that ends the call without retrying, so it counted every caught
exception. It always over-counted by the exhausted final attempt of each failing call;
#1203i8 made it total, because an unchanged-payload 400 now raises immediately.

tiktok-web-r184's first 20 minutes, with i8 live:

    retries: 61   retry_by_error: {"BadRequestError": 61}
    retry_sec_by_error: {"BadRequestError": 43.86}

against `Attempt N failed` 0, `All N attempts failed` 0, agent-level `Retry` 0 — not one
of those 61 was retried.

Not a harmless label: I read this field for r183 and reported "120 retries" when the
re-sends were 65. The seconds are still real, so a failure that ENDS the call now lands in
`failed_no_retry` rather than being dropped (#1202cr: a run that cannot say where its wall
clock went cannot be made cheaper).
"""
import asyncio
import logging

import pytest

from utils.config import LLMConfig, LLMProvider
from utils.llm import OpenAIClient, _LLM_USAGE


class _Err(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        if status is not None:
            self.status_code = status


IMAGE_400 = ("Error code: 400 - {'error': {'message': 'You uploaded an unsupported image. "
             "Please make sure your image is valid.', 'code': 'image_parse_error'}}")
QUOTA_401 = ("Error code: 401 - {'error': {'message': 'insufficient_quota', "
             "'type': 'insufficient_quota'}}")


def _client(attempts=3):
    c = OpenAIClient.__new__(OpenAIClient)
    c.config = LLMConfig(provider=LLMProvider.OPENAI, model_name="m", api_key="k",
                         retry_attempts=attempts, retry_delay=0.0)
    c._logger = logging.getLogger("LLM.openai")
    return c


@pytest.fixture(autouse=True)
def _reset():
    for k in ("retries", "retry_sec", "failed_no_retry", "failed_no_retry_sec"):
        _LLM_USAGE[k] = 0 if "sec" not in k else 0.0
    for k in ("retry_by_error", "retry_sec_by_error", "failed_no_retry_by_error"):
        _LLM_USAGE[k] = {}
    import utils.llm as _l
    _l._TERMINAL_LLM_ERROR["reason"] = None
    _l._QUOTA_FIRST_SEEN_1174["at"] = None
    yield


def _run(err, attempts=3):
    client = _client(attempts)
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


def test_an_unchanged_payload_400_counts_zero_retries():
    """r184's case. Before this fix it recorded 1 retry per occurrence while re-sending
    nothing — 61 phantom retries in 20 minutes."""
    assert _run(_Err(IMAGE_400, status=400)) == 1
    assert _LLM_USAGE["retries"] == 0, "a call that was never re-sent counted as a retry"
    assert _LLM_USAGE["retry_by_error"] == {}
    assert _LLM_USAGE["failed_no_retry"] == 1
    assert _LLM_USAGE["failed_no_retry_by_error"] == {"_Err": 1}


def test_a_terminal_error_counts_zero_retries():
    assert _run(_Err(QUOTA_401, status=401)) == 1
    assert _LLM_USAGE["retries"] == 0
    assert _LLM_USAGE["failed_no_retry"] == 1


def test_a_transient_error_counts_the_re_sends_not_the_attempts():
    """★ The number that must stay honest in the other direction: 3 attempts means 2
    retries (the first failure is re-sent, the second is re-sent, the third ends the
    call). The old code said 3 — one per exception."""
    assert _run(_Err("Connection error.")) == 3
    assert _LLM_USAGE["retries"] == 2, _LLM_USAGE["retries"]
    assert _LLM_USAGE["retry_by_error"] == {"_Err": 2}
    assert _LLM_USAGE["failed_no_retry"] == 1, "the exhausted final attempt is unaccounted"


def test_a_single_attempt_budget_records_no_retry():
    assert _run(_Err("Connection error."), attempts=1) == 1
    assert _LLM_USAGE["retries"] == 0
    assert _LLM_USAGE["failed_no_retry"] == 1


def test_the_seconds_are_not_lost_only_relabelled():
    """#1202cr's rule: the time is real either way. Whichever bucket a failure lands in,
    the run can still account for it."""
    _run(_Err(IMAGE_400, status=400))
    assert _LLM_USAGE["retry_sec"] == 0.0
    assert _LLM_USAGE["failed_no_retry_sec"] >= 0.0
    assert "failed_no_retry_sec" in _LLM_USAGE


def test_the_recorder_is_not_called_above_the_guards():
    """★ THE GUARD. The defect was purely positional: the recorder worked, its CALL SITE
    was above the returns. Pin that the retry counter is reached only inside the branch
    that is about to sleep and retry."""
    import ast
    import inspect
    import textwrap

    import utils.llm as _l
    src = textwrap.dedent(inspect.getsource(_l.BaseLLMClient._retry_with_backoff))
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "record_llm_retry_1202wr"):
            continue
        # every enclosing If of this call must test the attempt budget
        enclosing = [n for n in ast.walk(tree)
                     if isinstance(n, ast.If) and any(c is node for c in ast.walk(n))]
        tests = [ast.get_source_segment(src, n.test) or "" for n in enclosing]
        assert any("attempt < total_attempts" in t for t in tests), (
            "record_llm_retry_1202wr is reachable without a retry following it; "
            "enclosing conditions were %r" % (tests,))
        return
    raise AssertionError("record_llm_retry_1202wr is no longer called at all")


def test_the_counters_are_declared_not_created_on_first_write():
    """#1203ih: a MEASURED zero has to say zero.

    tiktok-web-r185 ran with #1203id live and its run_budget.json carried
    `retries: 92` beside no `failed_no_retry` key at all — created only on first write, so a
    run where nothing ended without a retry is indistinguishable from a build that has no
    such mechanism. That is #1202vp's hole ("the reader can only ever see None"), and it is
    the mirror of #947: do not print an UNMEASURED count as zero, but this one is measured on
    every call, so it must not hide.

    Asserted over the AST of the `_LLM_USAGE` literal, NOT over `llm_usage()`: this file's
    autouse `_reset` fixture writes these very keys before every test, so a runtime check
    passes even with the declaration deleted — I removed it as a mutation and all seven tests
    stayed green. A test my own fixture makes unfalsifiable proves nothing.
    """
    import ast
    import pathlib

    # the module's own file, via the import — `_AGENT` is a name from the OTHER test file
    # and does not exist here. Third time today I reached for a name without checking it
    # exists (the others: #1203i8's `locals().get("safe_messages")` and #1203ig's
    # `self._current_milestone_index`), so: resolve it from the imported module.
    import utils.llm as _l
    tree = ast.parse(pathlib.Path(_l.__file__).read_text(encoding="utf-8"))
    declared = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_LLM_USAGE" for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            declared = node.value
            break
    assert declared is not None, "the _LLM_USAGE initializer literal is gone"
    lit = {k.value: v for k, v in zip(declared.keys, declared.values)
           if isinstance(k, ast.Constant)}
    for k in ("failed_no_retry", "failed_no_retry_sec", "failed_no_retry_by_error",
              "retries", "retry_sec"):
        assert k in lit, "%s is created on first write, not declared" % k
    # declared with the right zero-value TYPE, so a reader can sum/merge without a guard
    assert isinstance(ast.literal_eval(lit["failed_no_retry"]), int)
    assert isinstance(ast.literal_eval(lit["failed_no_retry_sec"]), float)
    assert ast.literal_eval(lit["failed_no_retry_by_error"]) == {}


def test_the_ledger_is_named_as_the_consumer():
    """★ Self-audit: these keys have NO code reader, and that has to be stated.

    I spent this session finding evidence placed in keys nothing reads (#1203ii's whole
    reason), so the same standard applies to keys I add. `failed_no_retry*` rides
    `llm_usage()` into `run_budget.json` and its reader is whoever audits the ledger —
    #947's "a measurement that exists only in a log line is not a measurement". The
    docstring now says so AND cites the audit that used it (the #1203id before/after across
    r182-r187), so a future reader does not have to re-derive whether it is dead weight.
    """
    import inspect
    import utils.llm as _l
    doc = inspect.getdoc(_l.record_llm_failed_no_retry_1203id) or ""
    assert "WHO READS THESE" in doc, "the consumer of these keys is undocumented"
    assert "run_budget.json" in doc, "the docstring does not name where the keys land"
    assert "#947" in doc, "the rule that justifies persisting them is not cited"
    # and the evidence that it was actually used
    assert "r186" in doc and "r187" in doc, (
        "no evidence cited that these keys were actually read — that is what separates a "
        "ledger field from a dumb key")
