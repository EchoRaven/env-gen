r"""#612: the harness reported a GUESS at the cause as if it were an observation.

The browser test user's login note said, unconditionally:

    "login did nothing: token=False url=… — the form is not wired to the API"

Checked against the verification chains of every run whose UI login flow failed, that claim is
**false in all 12**: `POST /auth/login` answered **200** in each one — r142 alone logged 54
successful logins, r125 15, r137 7. The observable facts (no token, no navigation) are real; the
causal clause was an inference the harness had no basis for.

It is load-bearing. `login` is the ONLY failing UI flow in the whole corpus (12 of 66 runs), the
note lands in the failure ledger, and it sends the frontend lane to re-wire a form that is
already wired.

`test_user_validation` already discriminates correctly from the /auth response statuses (#566o —
"The old note ALWAYS said 'form is not wired to the API', which misdiagnoses a wired form →
agents chase a non-bug"). This SECOND code path never got that fix. Same shape as #604: the fix
exists, another path bypasses it.

Four signals now, in order of strength:
    no /auth request at all      -> genuinely not wired
    /auth all >= 400             -> credentials / backend, explicitly NOT a wiring bug
    /auth 2xx but no token       -> response shape or post-login handling
    + the direct-API login (#504) the same function already runs, as corroboration
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_runner as r


@pytest.fixture(scope="module")
def src():
    return inspect.getsource(r)


def _after(text: str, i: int, until: str = "\ndef ") -> str:
    """From an anchor to the next semantic landmark (end of text if absent).

    A window sized in BYTES breaks whenever a comment above it grows — the ratchet
    in test_source_windows_do_not_grow_943 exists because that had already happened
    more than once. Anchor + landmark keeps checking the same code however the
    module moves.
    """
    j = text.find(until, i)
    return text[i:j if j != -1 else len(text)]



# --- the claim is no longer unconditional ------------------------------------------------

def test_the_unconditional_not_wired_claim_is_gone(src):
    i = src.index("#612")
    window = _after(src, i)
    assert 'else f"login did nothing' not in window
    # it survives ONLY inside the branch that has evidence for it
    j = window.index("submit sent NO /auth request")
    assert "not wired to the API" in window[j:]


def test_the_no_request_branch_is_the_only_one_that_says_not_wired(src):
    i = src.index("#612")
    window = _after(src, i)
    assert window.count("not wired to the API") == 2      # the branch + the comment's quote


def test_a_4xx_is_reported_as_credentials_not_wiring(src):
    i = src.index("the form IS wired but /auth returned")
    assert "NOT a wiring bug" in _after(src, i, "\n\n")


def test_a_2xx_without_a_token_is_reported_as_shape(src):
    i = src.index("response shape or post-login handling")
    assert "/auth returned" in src[i - 260:i]


def test_the_statuses_are_captured_from_the_page(src):
    i = src.index("def _on_auth_resp")
    window = src[i - 200:i + 500]
    assert 'page.on("response", _on_auth_resp)' in window
    assert '"/auth/" in _r.url' in window


def test_the_listener_is_removed_after_the_drive(src):
    """It must not keep collecting through the rest of the walk."""
    i = src.index("_drive_auth_form(page, creds)")
    assert 'remove_listener("response", _on_auth_resp)' in _after(src, i, "\n\n")


def test_a_listener_failure_cannot_break_the_walk(src):
    i = src.index("def _on_auth_resp")
    assert "except Exception:" in _after(src, i, "\n\n")


# --- the #504 corroboration --------------------------------------------------------------------

def test_the_direct_api_login_is_folded_in_as_a_fourth_signal(src):
    i = src.index('report["api_login_ok"] = bool(token) or (')
    window = _after(src, i)
    assert "#612" in window
    assert "neither a backend" in window and "nor a credential fault" in window


def test_the_corroboration_only_fires_when_the_form_drive_FAILED(src):
    i = src.index("nor a credential fault")
    window = src[i - 700:i + 100]
    assert "not ok_auth" in window and 'report.get("api_login_ok")' in window


def test_the_corroboration_cannot_raise(src):
    i = src.index("nor a credential fault")
    assert "except Exception:" in _after(src, i, "\n\n")


# --- the evidence is recorded --------------------------------------------------------------------

def test_the_measurement_that_justifies_it_is_recorded(src):
    flat = " ".join(src.replace("#", " ").split())
    assert "FALSE IN ALL 12" in flat and "54 successful logins" in flat


def test_the_module_still_parses_and_imports():
    import ast
    ast.parse(inspect.getsource(r))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
