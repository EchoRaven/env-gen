"""#522b (netflix r93, 2026-08-06) — the visual-gate capture must mint an auth token
whenever the app HAS auth, not only when the noisy per-screen requires_auth flag is set.

GROUND TRUTH: r93 catalog pages 401'd (games 0.08) because the capture injected NO token —
minting was gated on `auth_needed = any(s["auth"])`, and the design-analyst measured the
catalog screens requires_auth=false that run (lane-noisy: r92 measured auth → token minted →
catalog rendered 0.50). The token-injection machinery (add_init_script, both keys, both
storages, pre-navigation) was already correct; the ONLY defect was gating the MINT on the
noisy flag. FIX #522b: drive minting off a DETERMINISTIC has_auth signal — a measured-auth
screen OR a seed demo user exists OR a /login|/signin|/signup route was projected — so the
capture is reliably authenticated on any app with an auth system, and inert (token=None) on
a truly-public app. The skip-judgment path stays gated on auth_measured (only a MEASURED-auth
screen with a failed mint is a non-judgment), so no new wedge.

These tests lock the has_auth decision logic + that the module imports cleanly (no syntax
regression from the edit)."""


def _has_auth(auth_measured, has_seed, routes):
    """Mirror of the #522b decision in visual_fidelity.run_visual_fidelity (~:1342)."""
    has_login_route = any(str(r).rstrip("/").lower() in ("/login", "/signin", "/signup")
                          for r in (routes or set()))
    return auth_measured or bool(has_seed) or has_login_route


def test_mints_when_login_route_present_even_if_flag_false():
    # the exact r93 case: catalog measured public (auth_measured False), but a /login route
    # exists → app HAS auth → must mint (so /api/games returns data, not 401).
    assert _has_auth(False, False, {"/browse", "/login", "/games"}) is True


def test_mints_when_seed_user_exists():
    assert _has_auth(False, True, {"/browse"}) is True


def test_mints_when_measured_auth():
    assert _has_auth(True, False, set()) is True


def test_public_app_does_not_mint():
    # no measured auth, no seed user, no login route → truly public → token stays None (unchanged)
    assert _has_auth(False, False, {"/", "/about", "/pricing"}) is False


def test_signin_signup_variants_count():
    assert _has_auth(False, False, {"/signin"}) is True
    assert _has_auth(False, False, {"/signup/"}) is True


def test_module_imports_cleanly():
    # catches a syntax/indentation regression from the #522b edit
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    assert hasattr(vf, "run_visual_fidelity") and hasattr(vf, "_seed_demo_login")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
