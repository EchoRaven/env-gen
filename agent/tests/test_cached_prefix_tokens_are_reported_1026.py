r"""#1026: the run's largest cost axis was unmeasurable on the path every run takes.

Two `[LLM Response]` log sites exist. The Responses-API one reports `cached_tokens`. The
chat-completions one — the path every netflix run actually takes — never read
`usage.prompt_tokens_details`, so no run has ever recorded whether its prompt prefix was
served from cache.

Why that matters, measured on r172 (pairing each request with its response, n=4155):

    prompt tokens      210,779,817        completion tokens  1,030,351
    per-call prompt    flat at ~41,000 from 9 messages onward (median 41,089 at 9-16 msgs,
                       41,246 at 65-128, 62,385 at 712) — a 30x growth in message count
                       costs 1.55x more tokens, so it is NOT history
    the fixed block    frontend_agent.j2 is 104,817 chars ≈ 26k tokens; the shared
                       agent_definition_v3.j2 is another 28,779; tools add ~2k

So roughly 33k tokens of STATIC system prompt is re-sent on every one of ~4,155 calls —
about 137M tokens, ~65% of the run — and the structure is cache-friendly (the system message
is first, and `_compose_system_prompt` appends its dynamic directive block at the END, so the
static part is a stable prefix). Whether that prefix is actually cached is the difference
between "free" and "the biggest wall-clock lever in the system", and r172 died on a 7200s
wall-clock cap.

★ This changes nothing about what is sent. It is a measurement fix, on the same principle as
#1023b/#1023d/#1024: an unmeasured axis must not be invisible. A run reporting
`cached_tokens=0` across the board would make prompt-size work the highest-value optimisation
available; a run reporting high hit rates retires the question.
"""
import inspect
import re

import pytest

from utils import llm as L


def _chat_completions_src():
    """The chat-completions logging site — located by the usage read that only it performs,
    not by a line number."""
    src = inspect.getsource(L)
    i = src.index("prompt_tokens = response.usage.prompt_tokens if response.usage else 0")
    return src[i:src.index("raw_response=response", i)]


def test_the_chat_path_logs_cached_tokens():
    assert "cached_tokens={cached_tokens}" in _chat_completions_src()


def test_it_reads_prompt_tokens_details():
    assert "prompt_tokens_details" in _chat_completions_src()


def test_cached_tokens_travels_in_the_usage_dict():
    """A log line is greppable; the usage dict is what any aggregator can sum."""
    b = _chat_completions_src()
    assert '"cached_tokens": cached_tokens' in b


def test_a_provider_without_the_field_cannot_break_a_call():
    """This is in the hot path of every LLM call. A provider that omits
    `prompt_tokens_details` — or returns None — must degrade, not raise."""
    b = _chat_completions_src()
    assert "except Exception:" in b
    assert 'cached_tokens = "n/a"' in b


def test_absent_is_reported_as_absent_not_as_zero_1026b():
    """★ The correction. The first cut defaulted to 0, and r173 logged `cached_tokens=0` on
    every call — which reads as "the prefix is never cached". The truth was that the metagen
    sidecar built a three-key usage dict and dropped `prompt_tokens_details` at the transport.
    A measure that cannot say "I was not told" manufactures a finding out of its own blind
    spot — the same trap as an empty index reading as "all tables dead" (#1023b)."""
    b = _chat_completions_src()
    assert '"n/a"' in b, "unreported must be distinguishable from a measured zero"
    assert "ABSENT IS NOT ZERO" in b


def test_both_response_sites_now_report_it():
    """The two paths must not drift again — that drift is the whole defect."""
    src = inspect.getsource(L)
    sites = re.findall(r'\[LLM Response\] latency=[^"\']*', src)
    assert len(sites) >= 2, sites
    for s in sites:
        assert "cached_tokens=" in s, f"a response log site without cached_tokens: {s[:90]}"


# --- the extraction, exercised rather than asserted about ------------------------------------

class _Details:
    def __init__(self, c): self.cached_tokens = c


class _Usage:
    def __init__(self, p, c, t, details=None):
        self.prompt_tokens, self.completion_tokens, self.total_tokens = p, c, t
        if details is not None:
            self.prompt_tokens_details = details


def _extract(usage):
    """Mirror of the production expression, so the degradation cases are executed.
    Returns "n/a" when the provider did not report — never a fabricated 0."""
    try:
        d = getattr(usage, "prompt_tokens_details", None) if usage else None
        if d is None and isinstance(usage, dict):
            d = usage.get("prompt_tokens_details")
        c = getattr(d, "cached_tokens", None) if d is not None else None
        if c is None and isinstance(d, dict):
            c = d.get("cached_tokens")
        return int(c) if c is not None else "n/a"
    except Exception:
        return "n/a"


@pytest.mark.parametrize("usage,expected", [
    (_Usage(100, 10, 110, _Details(64)), 64),
    (_Usage(100, 10, 110, _Details(0)), 0),          # a MEASURED zero stays 0
    (_Usage(100, 10, 110, _Details(None)), "n/a"),   # field present but null -> unreported
    (_Usage(100, 10, 110), "n/a"),                   # provider omits the field entirely
    (None, "n/a"),                                   # no usage at all
    ({"prompt_tokens_details": {"cached_tokens": 12}}, 12),   # dict-shaped (sidecar JSON)
])
def test_extraction_distinguishes_absent_from_zero(usage, expected):
    assert _extract(usage) == expected


def test_the_measurement_that_motivates_it_is_recorded():
    d = " ".join((__doc__ or "").split())
    assert "210,779,817" in d and "104,817" in d
    assert "1.55x" in d, "the reason this is NOT a history problem must travel with it"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
