"""#1202dc — name the host-level cause instead of whatever docker printed last.

`_compose_up` reported `(stderr or stdout)[-400:]`. netflix-r43 spent its whole $400 with
the visual gate reporting

    visual gate could not boot app: yml: the attribute `version` is obsolete, it will be
    ignored, please remove it to avoid potential confusion

— a DEPRECATION WARNING — while the real failure, `Bind for 0.0.0.0:8006 failed: port is
already allocated`, sat in the same stderr and fell outside the slice. The gate failed to
boot 7 times, `_best_by_screen` stayed empty, plateau climbed to 7 and no screen was ever
scored, while every lane churned on docker_up. That is where the $400 went.

Nobody can act on "the attribute version is obsolete"; anyone can free a port.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _compose_failure_reason_1202dc as reason,
    _COMPOSE_FATAL_1202DC,
)

R43_STDERR = (
    " Container netflix-local-r43-database-1  Recreated\n"
    "Error response from daemon: driver failed programming external connectivity on "
    "endpoint netflix-local-r43-database-1: Bind for 0.0.0.0:8006 failed: port is "
    "already allocated\n"
    "yml: the attribute `version` is obsolete, it will be ignored, please remove it to "
    "avoid potential confusion\n"
)


def test_the_r43_case_leads_with_the_port():
    """The exact bytes that cost the run, and the sentence that should have led."""
    out = reason(R43_STDERR, "")
    assert out.startswith("port is already allocated")
    assert "free it" in out


def test_the_raw_text_survives_behind_the_lead():
    """A diagnosis that discards the evidence cannot be checked by the next reader."""
    out = reason(R43_STDERR, "")
    assert "Raw:" in out


def test_a_deprecation_warning_alone_earns_no_diagnosis():
    """The failure mode this fixes must not be replaced by a confident wrong answer:
    a stderr matching no signature is reported as-is."""
    warn = "yml: the attribute `version` is obsolete, it will be ignored"
    out = reason(warn, "")
    assert out.strip() == warn.strip()
    assert "HOST PORT" not in out


@pytest.mark.parametrize("token", [t for t, _ in _COMPOSE_FATAL_1202DC])
def test_every_signature_produces_an_actionable_sentence(token):
    """A host-level cause is only useful if it names what to DO — r37 lost 372 dollars to an
    address-pool exhaustion nobody could read off the log."""
    out = reason("Error response from daemon: %s" % token, "")
    assert out.startswith(token)
    assert " — " in out and len(out.split(" — ", 1)[1]) > 20


def test_empty_output_still_says_something():
    assert reason("", "") == "compose up failed"
    assert reason(None, None) == "compose up failed"


def test_stdout_is_searched_when_stderr_is_silent():
    """compose has printed the fatal line to stdout in some versions; keying only on
    stderr would restore the original blindness."""
    out = reason("", "Bind for 0.0.0.0:8006 failed: port is already allocated")
    assert out.startswith("port is already allocated")
