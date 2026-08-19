"""#992: a button that says "Continue" is not fabricated data.

r161 logged this 72 times:

    Fabricated member-field fallbacks rewritten to honest empty states (#175 gate sites):
      ["AuthForm.jsx:3 `initialEmail || 'haibot2@illinois.edu'` → `(initialEmail ?? '—')`",
       "AuthForm.jsx:5 `? 'Continue' : mode`                    → `? '—' : mode`"]

The first rewrite is right and valuable — the lane had hardcoded the OPERATOR'S OWN EMAIL as
a fallback. The second puts a dash on a button.

The rule that misfires:

    if t[:1].isupper() and len(t) >= 4 and t.isalpha():   # proper-noun default (Hotel, Place)
        return True

`Continue` is uppercase, alphabetic and 8 characters, so it reads as an invented proper noun.
So do `Submit`, `Cancel`, `Search`, `Login` — essentially every button label in existence. A
browser walk hunting for "Continue" cannot find "—", which means the heal built to keep the UI
honest was failing the flows it was meant to protect.

The distinction is what the literal DENOTES: `Hotel` standing in for a missing name is
invented content; `Continue` on a control is the control's own text, present whether or not
any record exists behind it.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    _is_fabricated_fallback_literal as _fab)


@pytest.mark.parametrize("label", [
    "Continue", "Submit", "Cancel", "Save", "Delete", "Search", "Login", "Sign in",
    "Register", "Download", "Refresh", "Settings", "Profile",
])
def test_ui_action_labels_survive(label):
    assert _fab(label) is False, f"{label!r} is a control's own text, not invented content"


@pytest.mark.parametrize("fake", [
    "Hotel", "Placeville", "John Smith", "4.5 stars", "$19.99", "Springfield",
])
def test_fabricated_data_is_still_caught(fake):
    assert _fab(fake) is True, f"{fake!r} invents content that should be an empty state"


def test_the_operator_email_case_still_fires():
    """The rewrite that made #175 worth having — a lane hardcoding a real personal address."""
    assert _fab("haibot2@illinois.edu") is True


def test_the_honest_empty_states_are_untouched():
    for honest in ("—", "N/A", "Unknown", "Loading…", "No results"):
        assert _fab(honest) is False


def test_case_does_not_matter():
    assert _fab("CONTINUE") is False and _fab("continue") is False


def test_the_control_rewrites_the_button():
    """Planted control: the PRE-FIX rule — uppercase + alphabetic + >=4 — classifies a plain
    button label as fabricated, which is how a dash reached the UI."""
    t = "Continue"
    assert t[:1].isupper() and len(t) >= 4 and t.isalpha(), (
        "the control was supposed to match the old proper-noun rule; if it does not, this "
        "fix is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
