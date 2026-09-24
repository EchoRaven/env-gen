r"""#1202m: the party who can end the chain-rejection loop is told it is being asked.

The rejection message is excellent and reaches the VERIFIER; it ends by telling it to "ask the
backend lane to implement + register the endpoint FIRST". Nothing tells the BACKEND. So the
only party who can end the loop — by implementing and registering the endpoint, or by deciding
it should not exist — never hears that it is being asked for.

Measured: r26's counter for `PUT /api/profiles/{}` climbs monotonically to 49 and never
plateaus; r24 33, r25 26, r22 22 — every run in the corpus is in this loop. The module's own
comment puts it at 514 rejections across 50 of 50 runs, median 18 per run for a median of 2
distinct causes, ~9 re-submissions per cause. In r26 it is 36% of every chain registration the
verifier attempts.

Twice the answer was better wording for the verifier (#636 led with the instruction, #710
refined it) and twice the loop continued. A third round of wording aimed at the same reader is
not an answer.

★ What this deliberately is NOT: auto-dropping the offending steps and registering the rest.
That was written, tested, and reverted. It registers a chain that proves LESS — a weakened
judge — and three tests (#664's counter-survives-the-process, #71's dedup-across-chain-names)
correctly defend that contract. The rejection stands, the chain covers exactly what it covered,
and no task is filed. All that changes is that the request appears where someone can answer it.
"""

import logging
import sys
import tempfile
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime import registryhub as rh  # noqa: E402


def _hub():
    h = rh.RegistryHub(Path(tempfile.mkdtemp()))
    # The framework prepends an auth round-trip to every chain, so those endpoints have to
    # exist or the fixture rejects for a reason that has nothing to do with this test.
    for m, p_ in (("POST", "/auth/register"), ("POST", "/auth/login"),
                  ("GET", "/api/profiles")):
        h.register_endpoint(m, p_, schema={}, provider="backend", agent="backend")
    return h


def _chain(h, name):
    return h.register_verification_chain(
        name=name,
        description="probe",
        steps=[{"method": "PUT", "path": "/api/profiles/{id}", "expect_status": [200]}],
        agent="verifier")


def test_the_backend_is_named_once_the_request_repeats(caplog):
    h = _hub()
    with caplog.at_level(logging.WARNING, logger=rh.__name__):
        for i in range(3):
            _chain(h, "c%d" % i)
    assert "#1202m BACKEND" in caplog.text
    assert "/api/profiles" in caplog.text


def test_the_rejection_itself_is_unchanged():
    """The chain is still rejected and still covers nothing it did not cover before."""
    h = _hub()
    for i in range(3):
        out = _chain(h, "c%d" % i)
        assert isinstance(out, dict) and out.get("error")
        assert "NOT registered" in out["error"]
    assert "c0" not in (h.get_verification_chains() or {})


def test_a_clean_chain_is_untouched():
    h = _hub()
    out = h.register_verification_chain(
        name="clean", description="ok",
        steps=[{"method": "GET", "path": "/api/profiles", "expect_status": [200]}],
        agent="verifier")
    assert not (isinstance(out, dict) and out.get("error")), out
    assert "clean" in (h.get_verification_chains() or {})


def test_the_first_rejection_does_not_page_the_backend(caplog):
    """One rejection is the verifier making a mistake; it is the REPEAT that is a signal."""
    h = _hub()
    with caplog.at_level(logging.WARNING, logger=rh.__name__):
        _chain(h, "first")
    assert "#1202m BACKEND" not in caplog.text
