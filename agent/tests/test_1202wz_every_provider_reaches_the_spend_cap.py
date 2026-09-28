"""#1202wz: a provider that never records usage has no spend cap.

`ENVGEN_MAX_SPEND_USD` is enforced inside `_record_usage_1163` and NOWHERE ELSE -- one
enforcement point in the whole tree. Sweeping every `*Client` in `utils/llm.py`:

    OpenAIClient      records          GoogleClient    records
    AnthropicClient   DID NOT          LocalLLMClient  DID NOT   MetagenClient  DID NOT

On any of those three every call was invisible: `_LLM_USAGE` stayed at zero, `run_budget.json`
reported 0 calls and $0.00, and the cap never tripped. A run on one of them had no budget bound
at all and said so nowhere.

Reachable, not theoretical: `main.py` lists `--provider anthropic|local|metagen` among its
documented choices, and `scripts/tiktok_designinput.sh` exports `ANTHROPIC_API_KEY` for
`ENVGEN_PROVIDER=anthropic`, refusing only providers it does not recognise. One environment
variable selects an uncapped run.

It has cost nothing yet: production has been on the OpenAI-compatible path throughout --
268,187 calls across 72 runs, every one reporting a cache figure, which only that path's
`prompt_tokens_details` extraction produces (`cache_unreported` is 0 in all 72). A live
footgun, not a past loss.

The second half of the fix is `_anthropic_usage_1202wz`: the normaliser dropped
`cache_read_input_tokens` and `cache_creation_input_tokens`, so the ONE provider whose
`cache_control` breakpoint this module goes out of its way to set was also the one that could
not report whether the breakpoint worked.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

from utils.llm import (  # noqa: E402
    _LLM_USAGE,
    _anthropic_usage_1202wz,
    llm_usage,
    record_response_usage_1202wz,
)

_LLM = os.path.join(_AGENT, "utils", "llm.py")


def _read():
    with open(_LLM, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _client_classes():
    return [n for n in ast.walk(ast.parse(_read()))
            if isinstance(n, ast.ClassDef) and n.name.endswith("Client")
            and n.name != "BaseLLMClient"]


class _Usage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# --- the ratchet -------------------------------------------------------------------------

def test_the_sweep_sees_the_providers():
    names = {c.name for c in _client_classes()}
    assert len(names) >= 5, names


def test_every_provider_client_reaches_the_cap():
    """★ The defect. A client that records nothing is a run with no budget bound."""
    missing = []
    for cls in _client_classes():
        body = ast.unparse(cls)
        if ("_record_usage_1163" not in body
                and "record_response_usage_1202wz" not in body):
            missing.append(cls.name)
    assert missing == [], (
        "these providers never record a call, so ENVGEN_MAX_SPEND_USD -- enforced only inside "
        "_record_usage_1163 -- cannot trip on them and the run has no budget bound: %r"
        % missing)


def test_the_cap_still_has_exactly_one_enforcement_point():
    """If the cap moves, the ratchet above is measuring the wrong thing."""
    tree = ast.parse(_read())
    holders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if "ENVGEN_MAX_SPEND_USD" not in ast.unparse(node):
            continue
        # ENFORCING means ASSIGNING the terminal latch, not merely reading it --
        # `terminal_stop_is_own_budget_1202hv` names the same env var to CLASSIFY a stop
        # that already happened, and counting it here made this test fail on its own
        # looseness before it ever guarded anything.
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign):
                continue
            for tgt in inner.targets:
                if (isinstance(tgt, ast.Subscript)
                        and getattr(tgt.value, "id", "") == "_TERMINAL_LLM_ERROR"):
                    holders.append(node.name)
    holders = sorted(set(holders))
    assert holders == ["_record_usage_1163"], (
        "the spend cap is no longer enforced in the single place this test assumes: %r"
        % holders)


# --- the recorder ------------------------------------------------------------------------

def test_a_usage_dict_is_counted():
    before = llm_usage()["calls"]
    record_response_usage_1202wz(
        {"prompt_tokens": 100, "completion_tokens": 10, "cached_tokens": 80})
    got = llm_usage()
    assert got["calls"] == before + 1
    assert got["uncached"] >= 20


def test_a_missing_cache_field_records_the_omission_not_a_zero():
    """#1026b: absent is not zero -- a 0 reads as 'the prefix is never cached'."""
    before = int(_LLM_USAGE.get("cache_unreported") or 0)
    record_response_usage_1202wz({"prompt_tokens": 50, "completion_tokens": 5})
    assert int(_LLM_USAGE["cache_unreported"]) == before + 1


def test_a_junk_usage_never_breaks_a_call():
    for bad in (None, "nope", 7, []):
        record_response_usage_1202wz(bad)      # must not raise


# --- the anthropic mapping ---------------------------------------------------------------

def test_anthropic_prompt_tokens_include_the_cached_halves():
    """Anthropic's `input_tokens` EXCLUDES cache reads; this ledger's `prompt` is the whole
    prompt, with `cached` a subset of it (`uncached = prompt - cached`)."""
    got = _anthropic_usage_1202wz(_Usage(
        input_tokens=1000, output_tokens=50,
        cache_read_input_tokens=8000, cache_creation_input_tokens=200))
    assert got["prompt_tokens"] == 9200, got
    assert got["cached_tokens"] == 8000, got
    assert got["prompt_tokens"] - got["cached_tokens"] == 1200, (
        "uncached must be input + creation, the two billed at full rate")


def test_anthropic_reports_a_cache_write_separately():
    got = _anthropic_usage_1202wz(_Usage(
        input_tokens=1, output_tokens=1,
        cache_read_input_tokens=0, cache_creation_input_tokens=34303))
    assert got["cache_creation_tokens_1202wz"] == 34303, (
        "a cache WRITE is what distinguishes a cold prefix from a changed one; the "
        "normaliser dropped it")


def test_anthropic_without_the_field_says_unreported():
    got = _anthropic_usage_1202wz(_Usage(input_tokens=10, output_tokens=2))
    assert got["cached_tokens"] == "n/a", got
    assert got["prompt_tokens"] == 10


def test_the_normaliser_hands_that_dict_to_the_response():
    """A mapper nothing calls is #1202wm's dead mechanism."""
    fn = next((n for n in ast.walk(ast.parse(_read()))
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "_parse_response"), None)
    assert fn is not None
    body = ast.unparse(fn)
    assert "_anthropic_usage_1202wz" in body, "the response no longer carries the mapping"
    assert "record_response_usage_1202wz" in body, "the response no longer reaches the cap"
