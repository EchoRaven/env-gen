"""#1202vb — /auth/login must not issue a token to someone who did not prove who they are.

netflix-r30 live (2026-09-25): register 201, correct password 200, **wrong password 200
with a valid JWT**, never-registered email 200. Nine other live stacks across four
domains answered 401 to both, so the probe separates broken from correct apps rather
than flagging a style.
"""
import re
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.validation_runner import (
    wrong_password_verdict_1202vb as verdict,
)

_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/validation_runner.py")


def test_the_netflix_r30_reading_is_a_failure():
    """The live numbers that opened the ticket."""
    v, detail = verdict(201, 200, 200, 200)
    assert v == "fail", detail
    assert "WRONG password" in detail and "NEVER registered" in detail


def test_a_correct_app_passes():
    """Nine live stacks (tiktok r120/r122/r126/r132/r135, netflix-m1, rydr, paymo)."""
    assert verdict(201, 200, 401, 401) == ("pass", "")


@pytest.mark.parametrize("wrong, ghost", [(401, 401), (400, 400), (403, 422)])
def test_any_non_2xx_refusal_counts_as_checking(wrong, ghost):
    assert verdict(200, 200, wrong, ghost)[0] == "pass"


def test_only_the_wrong_password_leaks():
    v, detail = verdict(201, 200, 200, 401)
    assert v == "fail"
    assert "WRONG password" in detail
    assert "NEVER registered" not in detail


def test_only_the_ghost_account_leaks():
    """netflix-r24's shape: create-on-miss auto-provisions an unknown email, while a
    wrong password against an EXISTING user still 401s (create_user hits the unique
    email). Half a bypass is still a bypass."""
    v, detail = verdict(201, 200, 401, 200)
    assert v == "fail"
    assert "NEVER registered" in detail
    assert "WRONG password" not in detail


def test_register_that_did_not_take_is_skipped_not_failed():
    """igpreview live: register → 409, so every later login → 500. Without a credential
    the app itself issued, a refusal proves nothing about the password check."""
    v, detail = verdict(409, 500, 500, 500)
    assert v == "skip"
    assert "409" in detail


def test_an_app_that_refuses_its_own_correct_password_is_skipped_not_failed():
    """Refusing everything IS a defect — owned by the login/chain checks. Reporting it
    here too would send two lanes at one cause."""
    v, detail = verdict(201, 401, 401, 401)
    assert v == "skip"
    assert "correct password was refused" in detail


def test_a_skip_never_reaches_the_gate_and_a_fail_always_does():
    """The call site must add a check for pass/fail and stay silent for skip —
    a skip that emitted a passing check would launder 'not measured' into 'measured OK'."""
    src = _SRC.read_text()
    start = src.index("# 5.4b #1202vb")
    block = src[start:src.index("# 5.5 VERIFIER CHAIN TEST", start)]
    assert '_add("auth_password_is_checked"' in block
    add_line = next(l for l in block.splitlines() if '_add("auth_password_is_checked"' in l)
    # the _add must be guarded by the skip branch, not unconditional
    assert "else:" in block.split(add_line)[0]
    assert '_pw_verdict == "pass"' in add_line
    assert "#1202vb auth_password_is_checked skipped" in block


def test_the_probe_sends_a_password_that_differs_from_the_good_one():
    """A probe that reuses the correct password would pass on a broken app."""
    src = _SRC.read_text()
    start = src.index("# 5.4b #1202vb")
    block = src[start:src.index("# 5.5 VERIFIER CHAIN TEST", start)]
    wrong = re.search(r'"password": (_pw_good \+ "[^"]+")', block)
    assert wrong, "the wrong-password call must not send _pw_good unchanged"


def test_the_failing_check_can_be_routed_to_a_lane():
    """#1202tm's lesson: a check with no _CHECK_OWNER entry drops to the
    deliverability_other fallback and dispatches nobody — it blocks delivery forever."""
    from env_generator.llm_generator.multi_agent.runtime import remediation_dispatcher as rd
    src = pathlib.Path(rd.__file__).read_text()
    entry = src[src.index('"auth_password_is_checked": ('):]
    entry = entry[:entry.index('"business_writes_persist"')]
    assert '"backend"' in entry
    assert "custom_routes.py" in entry
    assert "verify_user_password" in entry


def test_the_prompt_forbids_rebinding_not_just_writing_the_file():
    """#1202vb prevention side. The ownership rule the lane obeyed is about FILES — it
    never wrote oauth_store.py, it rebound the class from custom_routes.py. A rule that
    only names files cannot reach that, so the AUTH hard-rules must name the behaviour.

    Anchored to the neighbouring rules, never a byte window (#943)."""
    j2 = (pathlib.Path(__file__).resolve().parents[1]
          / "env_generator/llm_generator/multi_agent/prompts/v4/backend_agent.j2").read_text()
    start = j2.index("**DO NOT write your own auth**")
    block = j2[start:j2.index("Standard CRUD is projected for you", start)]
    assert "REBIND" in block
    assert "OAuthStore.verify_user_password" in block
    # it must name the gate check, so the lane can connect the rule to the failure it sees
    assert "auth_password_is_checked" in block
    # and it must say what to do INSTEAD, or it just forbids the only escape the lane found
    assert "register step" in block
