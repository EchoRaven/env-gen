r"""#572 (netflix r137, live): the delivery-deferral log hand-listed a SUBSET of the signals
`browser_report_unusable` actually keys on. The predicate had grown `fallback_dom_pages` (#224)
and `primary_dataless` (#231d); the message was never taught to print them. r137 deferred
delivery four times over 23 minutes while logging

    DELIVERY DEFERRED: browser test-user found the app UNUSABLE
    (auth_ok=True blank=[] login_wall=[] hollow=False no_real_data=False fake_map=[])

— every field it printed was clean, so the hold read as evidence-free and the P0 dispatched to
the frontend named nothing to fix.

Fix: `browser_unusable_signals` returns the signals that FIRED, and the message is derived from
it, so the predicate and its explanation cannot drift apart again. Diagnostic only — the gate
verdict is untouched (asserted below on every case).
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.test_user_runner import (
    browser_report_unusable,
    browser_unusable_signals,
)

_R137 = {"ran": True, "auth_ok": True, "api_login_ok": True, "blank_pages": [],
         "auth_redirect_pages": [], "hollow_frontend": False, "no_real_data": False,
         "fake_map_pages": [], "fallback_dom_pages": ["/browse"], "primary_dataless": False}

_CASES = [
    _R137,
    {"ran": True, "auth_ok": True, "primary_dataless": True},
    {"ran": True, "auth_ok": False},
    {"ran": True, "auth_ok": False, "api_login_ok": True},          # #504 cancels login signals
    {"ran": True, "auth_ok": True, "blank_pages": ["/my-list"]},
    {"ran": True, "auth_ok": True, "hollow_frontend": True},
    {"ran": True, "auth_ok": True, "no_real_data": True},
    {"ran": True, "auth_ok": True, "fake_map_pages": ["/map"]},
    {"ran": False},
    {"ran": True, "auth_ok": True},                                  # nothing fired
    None,
]


def test_r137_the_signal_the_old_message_hid_is_now_named():
    got = browser_unusable_signals(_R137)
    assert got == {"fallback_dom_pages": ["/browse"]}, got
    assert browser_report_unusable(_R137) is True


def test_signals_and_verdict_never_disagree():
    """The whole point: a non-empty signal set iff the gate says unusable."""
    for c in _CASES:
        assert bool(browser_unusable_signals(c)) == bool(browser_report_unusable(c)), c


def test_api_login_ok_suppresses_the_login_signals_in_both(_case=None):
    """#504: a working direct-API login makes form-drive auth failures false negatives."""
    rep = {"ran": True, "auth_ok": False, "hollow_frontend": True,
           "auth_redirect_pages": ["/browse"], "api_login_ok": True}
    assert browser_unusable_signals(rep) == {}
    assert browser_report_unusable(rep) is False
    # ...but a NON-login signal alongside them still holds, and is named
    rep2 = dict(rep, blank_pages=["/my-list"])
    assert browser_unusable_signals(rep2) == {"blank_pages": ["/my-list"]}
    assert browser_report_unusable(rep2) is True


def test_a_walk_that_did_not_run_names_nothing():
    for c in (None, {}, {"ran": False, "auth_ok": False}):
        assert browser_unusable_signals(c) == {}
        assert browser_report_unusable(c) is False


def test_multiple_signals_are_all_named():
    rep = {"ran": True, "auth_ok": True, "blank_pages": ["/a"], "primary_dataless": True,
           "fallback_dom_pages": ["/b"]}
    got = browser_unusable_signals(rep)
    assert set(got) == {"blank_pages", "primary_dataless", "fallback_dom_pages"}, got


def test_the_orchestrator_message_is_derived_not_hand_listed():
    """Guard against the drift returning: the deferral log must not re-hardcode the field
    list it used to print."""
    import inspect
    from env_generator.llm_generator.multi_agent import orchestrator
    src = inspect.getsource(orchestrator)
    assert "browser_unusable_signals(_bg_report)" in src
    assert "auth_ok=%s blank=%s login_wall=%s" not in src, "the hand-listed subset is back"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
