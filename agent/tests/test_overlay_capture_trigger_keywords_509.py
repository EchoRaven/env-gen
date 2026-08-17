"""#509 (netflix r84, 2026-08-05) — MODAL/OVERLAY interaction capture. Overlay screens
(rate_dialog, account_menu, card_hover_preview) scored a floor (~0.12/0.40) because route-
capture screenshots the PARENT page, never opening the overlay → judged against the modal
reference. #128 correctly marks them ADVISORY; #509 makes them SCORABLE: after navigating to
the parent route (reference_spec route_hint), drive the trigger (click/hover) so the shot
captures the real overlay. Best-effort + fallback (never regresses).

The playwright interaction (_drive_overlay_open) validates by render on the next run; these
tests lock the PURE trigger-derivation helpers + that the module imports (JS constants /
async helper parse)."""
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    _overlay_trigger_keywords, _overlay_is_hover)


# ---- keyword derivation strips the interaction token, keeps the intent ----
def test_rate_dialog_keywords():
    kws = _overlay_trigger_keywords("rate_dialog")
    assert "rate" in kws
    assert "dialog" not in kws  # the interaction token is stripped


def test_account_menu_keywords_include_menu_synonyms():
    kws = _overlay_trigger_keywords("account_menu")
    assert "account" in kws
    # menu-type → generic synonyms appended so a bare avatar trigger is still found
    for syn in ("profile", "avatar", "menu"):
        assert syn in kws


def test_card_hover_preview_keywords():
    kws = _overlay_trigger_keywords("card_hover_preview")
    assert "card" in kws
    assert "hover" not in kws and "preview" not in kws


def test_search_flyout_keywords():
    kws = _overlay_trigger_keywords("search_flyout")
    assert "search" in kws
    assert "flyout" not in kws


def test_dropdown_gets_menu_synonyms():
    kws = _overlay_trigger_keywords("shows_genres_dropdown")
    assert "shows" in kws or "genres" in kws
    assert "menu" in kws  # dropdown → menu synonyms


def test_keywords_dedup_and_min_length():
    # short tokens (<=2 chars) and stopwords dropped; result de-duplicated.
    kws = _overlay_trigger_keywords("the_user_modal")
    assert "the" not in kws and "user" not in kws  # stopwords
    assert len(kws) == len(set(kws))               # de-duplicated


# ---- hover detection ----
def test_hover_detection():
    assert _overlay_is_hover("card_hover_preview") is True
    assert _overlay_is_hover("card_preview") is True
    assert _overlay_is_hover("rate_dialog") is False
    assert _overlay_is_hover("account_menu") is False


# ---- module imports cleanly (JS constants + async _drive_overlay_open parse) ----
def test_module_imports_and_driver_present():
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    assert callable(vf._drive_overlay_open)
    assert "role=dialog" in vf._OVERLAY_DETECT_JS
    assert "scrollIntoView" in vf._OVERLAY_OPEN_JS


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
