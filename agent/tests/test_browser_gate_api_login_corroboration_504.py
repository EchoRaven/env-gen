"""#504 (netflix r81, 2026-08-05) — the pre-release BROWSER test-user gate FALSE-BLOCKED a
functionally-deliverable app. r81's app login works end-to-end (proven by live playwright
form-drive with the seeded creds: token stored, /browse no bounce), but the gate's harness
form-drive login failed (cred mismatch / transient mid-remediation build) → auth_ok False →
hollow_frontend → FIX #152 HARD-held the release forever → no delivery (business_chain green,
build clean, all else passing). FIX: corroborate the login-broken HARD signal with a DIRECT-API
login (report['api_login_ok']). When the app authenticates the seeded creds via the API, a
form-drive auth failure is a harness/transient false-negative, NOT an unusable app → do NOT
flag unusable / hard-defer on the login signals. A genuinely dead auth (API login ALSO fails →
api_login_ok False) still blocks. Non-login signals (blank/no_real_data/fake_map/fallback/
primary_dataless) always hold. These tests lock both pure predicates."""
from env_generator.llm_generator.multi_agent.runtime.test_user_runner import (
    browser_report_unusable, browser_gate_decision)


def _rep(**kw):
    base = {"ran": True, "auth_ok": True, "blank_pages": [], "auth_redirect_pages": [],
            "hollow_frontend": False, "no_real_data": False, "fake_map_pages": [],
            "fallback_dom_pages": [], "primary_dataless": False}
    base.update(kw)
    return base


# ---- the r81 case: form-drive login failed but the app's API login WORKS ----
def test_form_login_failed_but_api_login_ok_is_NOT_unusable():
    r = _rep(auth_ok=False, hollow_frontend=True, auth_redirect_pages=["browse", "games"],
             api_login_ok=True)
    assert browser_report_unusable(r) is False  # provably loginable → not unusable
    assert browser_gate_decision(r, "defer") == "defer"  # squad_decision honored (bounded escape)
    assert browser_gate_decision(r, "release") == "release"  # NOT hard-held → can release


def test_genuinely_broken_auth_still_blocks():
    # API login ALSO fails (api_login_ok False) → real dead auth → unusable + HARD-defer.
    r = _rep(auth_ok=False, hollow_frontend=True, api_login_ok=False)
    assert browser_report_unusable(r) is True
    assert browser_gate_decision(r, "release") == "defer"  # hard-held (never escape a dead app)


def test_api_login_ok_absent_is_byte_identical_prior_behavior():
    # no api_login_ok key (older callers) → login-broken still blocks exactly as before.
    r = _rep(auth_ok=False, hollow_frontend=True)
    assert browser_report_unusable(r) is True
    assert browser_gate_decision(r, "release") == "defer"


def test_non_login_signals_still_block_even_when_api_login_ok():
    # api login works, but a page is blank / renders no real data → STILL unusable (not login-caused).
    assert browser_report_unusable(_rep(api_login_ok=True, blank_pages=["browse"])) is True
    assert browser_report_unusable(_rep(api_login_ok=True, no_real_data=True)) is True
    # fallback_dom / primary_dataless still HARD-defer even with api_login_ok.
    assert browser_gate_decision(_rep(api_login_ok=True, primary_dataless=True), "release") == "defer"
    assert browser_gate_decision(_rep(api_login_ok=True, fallback_dom_pages=["x"]), "release") == "defer"


def test_fully_healthy_app_releases():
    r = _rep(api_login_ok=True)  # auth ok, no bad signals
    assert browser_report_unusable(r) is False
    assert browser_gate_decision(r, "release") == "release"


def test_did_not_run_never_unusable():
    assert browser_report_unusable({"ran": False}) is False
    assert browser_report_unusable(None) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
