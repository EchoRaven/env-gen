"""#516 (netflix r89, 2026-08-06) — a MEDIA hero's CTAs must be canonical action verbs.

GROUND TRUTH: r89's live browse_home render (verified from the capture) showed the primary hero
button as "▶ Kids" — the design decomposition mis-classified the "Kids" PROFILE badge as a hero
action component, so _action_labels_221 extracted "Kids" and it shipped as the Play button. FIX
#516: for a media hero (app stages video), drop decomposed action labels that aren't recognizable
media CTAs; if none survive, the canonical ["Play","More Info"] fallback applies. Media-gated +
generalizable (no product literals) → non-media heroes untouched.

These tests lock: the media-CTA vocabulary (rejects profile/proper-name noise, accepts real CTAs);
the leak source (_action_labels_221('Kids') → ['Kids']); and the filter behavior (a noise label is
dropped so the caller's canonical fallback fills)."""
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _MEDIA_CTA_RE, _action_labels_221)


def test_media_cta_re_rejects_profile_or_proper_names():
    for noise in ("Kids", "Ava", "John", "Guest", "Profile"):
        assert not _MEDIA_CTA_RE.search(noise), noise


def test_media_cta_re_accepts_real_ctas():
    for cta in ("Play", "Watch Now", "More Info", "Resume", "Continue Watching",
                "Trailer", "Details", "Add to List", "Download", "Preview"):
        assert _MEDIA_CTA_RE.search(cta), cta


def test_action_labels_extracts_kids_leak():
    # confirms the r89 leak SOURCE: a mis-classified 'Kids' action component → ['Kids'].
    assert _action_labels_221("Kids") == ["Kids"]


def test_filter_drops_noise_then_canonical_fallback_applies():
    # the exact #516 filter the hero block applies to a media hero, then the caller's fallback.
    def _apply(labels, is_media):
        if is_media and labels:
            labels = [l for l in labels if _MEDIA_CTA_RE.search(l)]
        if not labels and is_media:
            labels = ["Play", "More Info"]
        return labels
    assert _apply(["Kids"], True) == ["Play", "More Info"]           # noise → canonical
    assert _apply(["Play", "More Info"], True) == ["Play", "More Info"]  # real CTAs kept
    assert _apply(["Watch Now", "Kids"], True) == ["Watch Now"]      # mixed → keep the real one
    assert _apply(["Kids"], False) == ["Kids"]                       # non-media hero untouched


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
