"""#1124: "Connection refused" without an address is half a diagnosis.

`HealthcheckProbe` holds the url it polls for the whole of `wait()`, and dropped it at
the moment of capture — `HealthcheckResult` carried healthy / status_code / attempts /
elapsed_s / last_error and no address. The same file makes this exact argument four
lines below, in #1000, about the `Allow:` header on a 405.

Found live on the gpt-5.5 run: 8 runs, 5 aborted, every one recorded as
`healthy=False, attempts=31, "[Errno 111] Connection refused"` with no address — while
THREE candidate ports were in play at once (the run's own API=3000, the test-user
squad's api=3011, and the container-internal 8081). The record therefore could not
distinguish "the app never came up" from "we probed the wrong port": opposite defects
with opposite fixes.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.hubs.runhub.compose import (
    HealthcheckProbe,
    HealthcheckResult,
)

URL = "http://localhost:3011/health"


class _Resp:
    def __init__(self, code):
        self.status_code = code


def _probe(getter, **kw):
    kw.setdefault("poll_interval_s", 0)
    kw.setdefault("timeout_s", 0.05)
    return HealthcheckProbe(url=URL, getter=getter,
                            clock=_clock(), sleep=lambda _s: None, **kw)


def _clock():
    """Monotonic-ish fake so timeout_s is reached deterministically."""
    t = {"n": 0.0}

    def c():
        t["n"] += 0.03
        return t["n"]
    return c


def test_a_refusal_records_the_address_it_was_refused_at():
    def _refuse(url, timeout):
        raise OSError("[Errno 111] Connection refused")

    r = _probe(_refuse).wait()
    assert r.healthy is False
    assert "Connection refused" in r.last_error
    assert r.url == URL, (
        "the failure still does not say WHERE it was refused: %r" % (r.url,)
    )


def test_a_success_records_it_too():
    """Both paths, so a passing record can be cross-checked against the port map."""
    r = _probe(lambda url, timeout: _Resp(200)).wait()
    assert r.healthy is True and r.url == URL


def test_the_recorded_address_is_the_one_actually_polled():
    """Guard against reporting a constant rather than the probe's own target."""
    seen = []

    def _capture(url, timeout):
        seen.append(url)
        raise OSError("[Errno 111] Connection refused")

    r = _probe(_capture).wait()
    assert seen, "the probe never issued a request"
    assert r.url == seen[0]


def test_the_other_fields_are_untouched():
    def _refuse(url, timeout):
        raise OSError("[Errno 111] Connection refused")

    r = _probe(_refuse).wait()
    assert r.attempts >= 1
    assert r.elapsed_s > 0
    assert r.status_code is None


def test_url_defaults_to_empty_for_a_hand_built_result():
    """The field is additive: existing constructions keep working."""
    r = HealthcheckResult(healthy=True)
    assert r.url == ""
    assert r.healthy is True and r.attempts == 0


def test_the_persisted_record_carries_the_url():
    """service.py writes the field into the run record, not just onto the object."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import service

    src = inspect.getsource(service)
    # Landmark-anchored, not a fixed-width window: #943's ratchet forbids the latter
    # precisely because the offset goes stale the moment the block is edited.
    i = src.index('"last_error": hc_result.last_error')
    window = src[i:src.index("})", i)]
    assert '"url"' in window, (
        "the healthcheck dict written to the run record has no url key — the field "
        "exists on the result but never reaches anyone reading the store"
    )
