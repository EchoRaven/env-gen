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

# --- #1202xb: the same hole through the other door ----------------------------------------
#
# `chat_stream` records nothing on FIVE of the six clients (MetagenClient's delegates to
# `chat`). Wiring them would be work on dead code: nothing outside `utils/llm.py` and this
# test suite references `chat_stream` or `LLM.stream` — the engine builds an `LLM` in
# `orchestrator.py` and `llm_overrides.py` and only ever calls `chat`. AnthropicClient.chat
# DOES stream internally for large outputs (`_should_stream`), but all four of its request
# branches converge on `_parse_response`, which #1202wz wired, so that path is covered.
#
# So this is a tripwire, not a fix: the day a caller appears, it fails and says to add the
# recording first. It is a reachability check by name, which cannot see an indirect call —
# a floor, not a proof, exactly as #1202ts says of a claim-checker.
import glob  # noqa: E402

_SKIP_1202XB = ("utils/llm.py",)


def _stream_callers_1202xb():
    """Files outside llm.py whose AST calls `chat_stream` or `.stream` on an llm-ish object."""
    out = []
    roots = (os.path.join(_AGENT, "env_generator"), os.path.join(_AGENT, "utils"),
             os.path.join(_AGENT, "tools"))
    for root in roots:
        for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, _AGENT).replace(os.sep, "/")
            if rel in _SKIP_1202XB or "/tests/" in "/" + rel:
                continue
            try:
                with open(path, encoding="utf-8") as fh:      # #1202eu
                    tree = ast.parse(fh.read())
            except Exception:
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)):
                    continue
                if node.func.attr == "chat_stream":
                    out.append("%s:%d" % (rel, node.lineno))
                elif node.func.attr == "stream":
                    owner = ast.unparse(node.func.value).lower()
                    if "llm" in owner:
                        out.append("%s:%d" % (rel, node.lineno))
    return sorted(set(out))


def _stream_methods_that_record_1202xb():
    """{class: bool} for every `chat_stream`, counting a delegation to `chat` as recording."""
    got = {}
    for cls in _client_classes():
        for fn in cls.body:
            if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and fn.name == "chat_stream"):
                continue
            body = ast.unparse(fn)
            got[cls.name] = ("_record_usage_1163" in body
                             or "record_response_usage_1202wz" in body
                             or "self.chat(" in body)
    return got


def test_the_stream_scan_sees_the_methods():
    got = _stream_methods_that_record_1202xb()
    assert len(got) >= 5, "the chat_stream scan found almost nothing: %r" % got


def test_streaming_is_either_unused_or_capped():
    """★ The tripwire. Today the left side holds; the day it stops, the right must."""
    callers = _stream_callers_1202xb()
    if not callers:
        return
    silent = sorted(k for k, ok in _stream_methods_that_record_1202xb().items() if not ok)
    assert not silent, (
        "something now streams (%r) and these clients record nothing on that path, so "
        "ENVGEN_MAX_SPEND_USD cannot trip on it -- wire them the way #1202wz wired `chat`: %r"
        % (callers, silent))


def test_the_anthropic_stream_branch_inside_chat_is_covered():
    """`_should_stream` makes `chat` itself stream for large outputs. All four of its request
    branches must converge on the one recorded exit."""
    cls = next(c for c in _client_classes() if c.name == "AnthropicClient")
    fn = next(f for f in cls.body
              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == "chat")
    # Only `chat`'s OWN returns. `ast.walk` descends into the nested `_call()` closures,
    # whose returns hand the response back to `chat` and are not exits from it -- counting
    # them made this test fail on its own scope before it guarded anything.
    parent = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def _owner(node):
        while node in parent:
            node = parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    returns = [n for n in ast.walk(fn)
               if isinstance(n, ast.Return) and n.value is not None and _owner(n) is fn]
    assert returns, "chat no longer returns anything this test can check"
    bypass = [ast.unparse(n) for n in returns if "_parse_response" not in ast.unparse(n)]
    assert not bypass, (
        "chat has a return that bypasses the recorded exit, so those calls never reach the "
        "spend cap: %r" % bypass)
