r"""Guard: a provider that neither declares a `chat` parameter nor forwards `**kwargs` drops it.

Every provider's `chat` ends in `**kwargs`, so an argument it does not declare never raises —
it is absorbed. Whether that is harmless depends entirely on what the body then does with
`kwargs`:

    provider          declares tools   forwards **kwargs   effect of chat(..., tools=[...])
    AnthropicClient   yes              yes  (update)       handled
    OpenAIClient      yes              yes                 handled
    GoogleClient      yes              no                  handled (declared)
    MetagenClient     yes              no                  handled (declared)
    LocalLLMClient    NO               NO                  SILENTLY DROPPED

So the rule worth enforcing is not "every provider declares every parameter" — Anthropic does
not declare `tool_choice` and is perfectly fine, because `request_params.update(kwargs)` hands
it straight to the SDK. The rule is: **declare it, or forward kwargs; otherwise passing it is a
silent capability loss**, which is worse than a TypeError because the call returns a plausible
response with the capability missing and nothing in the run says so.

There is a live caller: `design_prep.py` sends `tools=_SCREEN_TOOL` plus
`tool_choice={"type": "tool", ...}` (the #480 forced-function rung). Against Anthropic both
reach the API. Against `LocalLLMClient` both vanish, and the forced-function rung degrades
without raising — so the `except Exception` ladder below it never fires either.

Found by writing this guard: my own single-line grep for `.chat(` call sites reported ZERO
callers passing `tools=`, because the real one spans lines. The guard's `-A4` window caught it
immediately. That is the reason it greps rather than trusting a one-off measurement.

To satisfy this: declare the parameter and handle it, forward `**kwargs`, or stop passing it.
"""
import inspect
import re
import subprocess
from pathlib import Path

import pytest

import utils.llm as L

_ROOT = Path(__file__).resolve().parent.parent
_PARAMS = ("tools", "functions", "tool_choice")

# frozen 2026-08-13 — providers that neither declare nor forward. Shrink freely; never grow.
_SILENT_DROPPERS = {"LocalLLMClient"}


def _providers():
    return {n: c for n, c in sorted(vars(L).items())
            if inspect.isclass(c) and issubclass(c, L.BaseLLMClient)
            and c is not L.BaseLLMClient and "chat" in c.__dict__}


def _forwards_kwargs(cls):
    src = inspect.getsource(cls.__dict__["chat"])
    return bool(re.search(r"update\(kwargs\)|\*\*kwargs\)", src))


def _declares(cls, param):
    return param in inspect.signature(cls.__dict__["chat"]).parameters


def _handles(cls, param):
    """Declared, or reachable through a kwargs passthrough, or read out of kwargs by hand."""
    if _declares(cls, param) or _forwards_kwargs(cls):
        return True
    return param in inspect.getsource(cls.__dict__["chat"])


def _chat_call_sites():
    out = subprocess.run(
        ["grep", "-rn", "-A4", "--include=*.py", r"\.chat(",
         str(_ROOT / "env_generator"), str(_ROOT / "utils")],
        capture_output=True, text=True).stdout
    return out.splitlines()


# --- the discovery must not pass vacuously ---------------------------------------------------

def test_there_are_providers_to_check():
    found = _providers()
    assert len(found) >= 4, found
    assert {"AnthropicClient", "OpenAIClient", "LocalLLMClient"} <= set(found)


def test_the_known_dropper_really_is_one():
    """Pins the premise this whole file rests on."""
    local = _providers()["LocalLLMClient"]
    assert not _declares(local, "tools")
    assert not _forwards_kwargs(local)


def test_kwargs_forwarding_is_what_saves_anthropic():
    """Anthropic does not declare `tool_choice`, and that is fine — it forwards."""
    anth = _providers()["AnthropicClient"]
    assert not _declares(anth, "tool_choice")
    assert _forwards_kwargs(anth)
    assert _handles(anth, "tool_choice")


# --- the rule -------------------------------------------------------------------------------

@pytest.mark.parametrize("param", _PARAMS)
def test_no_provider_becomes_a_new_silent_dropper(param):
    bad = {n for n, c in _providers().items() if not _handles(c, param)}
    assert bad <= _SILENT_DROPPERS, (
        f"provider(s) {sorted(bad - _SILENT_DROPPERS)} neither declare `{param}` nor forward "
        "**kwargs — passing it there is absorbed and the capability is lost without a word. "
        "Declare and handle it, forward **kwargs, or add the provider to _SILENT_DROPPERS "
        "with a reason.")


def test_the_frozen_list_is_still_accurate():
    stale = {n for n in _SILENT_DROPPERS
             if n in _providers() and all(_handles(_providers()[n], p) for p in _PARAMS)}
    assert not stale, f"no longer dropping — remove from _SILENT_DROPPERS: {sorted(stale)}"


# --- what the callers actually pass ------------------------------------------------------------

def test_the_live_caller_is_still_the_one_we_know_about():
    """A NEW `.chat(..., tools=)` caller means a new surface that LocalLLMClient will silence."""
    hits = [l for l in _chat_call_sites() if re.search(r"\b(tools|functions|tool_choice)=", l)]
    # grep -A emits "path:lineno:match" and "path-lineno-context"; the repo path itself
    # contains a dash, so split on the lineno separator, not on the first dash.
    files = {re.match(r"(.+?)[:-]\d+[:-]", l).group(1).rsplit("/", 1)[-1]
             for l in hits if re.match(r"(.+?)[:-]\d+[:-]", l)}
    assert files <= {"design_prep.py"}, (
        f"new .chat() call site(s) passing a droppable parameter: {sorted(files)} — check them "
        "against _SILENT_DROPPERS before shipping.")


def test_a_multiline_call_site_is_visible_to_this_grep():
    """The single-line grep that missed design_prep.py is exactly the mistake to not repeat."""
    hits = [l for l in _chat_call_sites() if "tools=" in l]
    assert hits, "the -A4 window must still catch the multi-line design_prep call"


# --- streaming ------------------------------------------------------------------------------

def test_chat_stream_is_uniform_and_should_stay_that_way():
    base = set(inspect.signature(L.BaseLLMClient.chat_stream).parameters)
    for name, cls in _providers().items():
        fn = cls.__dict__.get("chat_stream")
        if fn is None:
            continue
        missing = base - set(inspect.signature(fn).parameters)
        assert not missing, f"{name}.chat_stream dropped {sorted(missing)}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
