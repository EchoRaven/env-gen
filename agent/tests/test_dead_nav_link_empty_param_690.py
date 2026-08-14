r"""#690: the route existed — the link had lost its parameter — and all three branches misread it.

Found by a key I had not used: grouping runs by OUTCOME (delivered vs aborted) instead of by
failure class. That comparison first produced a negative that reframes the whole session:

    delivered      27 runs   median 24,969 log lines, 101 steps,  9.3 failures per 1000 lines
    not delivered 133 runs   median 11,184 log lines,  69 steps,  9.7 failures per 1000 lines

The failure RATE is the same. Aborted runs are not failing more — they simply stop at about half
the length. So tool-call failures do not decide delivery; what decides it is whether the gate
ever goes green. Reading the final `Failed checks:` line of the 14 aborted runs that record one:

    verification_checklist_not_ready   6
    deliverability_dead_nav_link       5
    business_chain_failing             4

`dead_nav_link` FIRES more in the live era than ever — 212 in r100+ against 37 before — though
era-controlling the terminal blocker shows it is not what runs finally die on (13 of those 14
aborted runs are pre-r100; the one r100+ run died on business_chain_failing). What it costs is
rounds spent on a mis-stated cause. What it flags is always the same shape:

    components/HeroBillboard.jsx:  /watch/        -> /profiles   x34
    components/HoverPreview.jsx:   /watch/        -> /profiles   x20
    components/GenresDropdown.jsx: /browse/genre/ -> /profiles   x16

A parameterised prefix with NOTHING after it: the template rendered `/watch/${id}` with an empty
id. `/watch/:titleId` is declared and wired, so the route is fine — but #278's three branches
would send the lane to wire a route that exists, author a page that exists, or repoint a link
that already points at the right page. None is the fix, and each costs a round.

The new branch runs FIRST and is detected from data already passed in: the target ends in "/" and
a declared route begins with it followed by a `:param` segment.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_audit import (
    dead_nav_link_remediation as remediate,
)

_DECLARED = {"/watch/:titleId", "/browse/genre/:genreId", "/profiles", "/browse"}


# --- the empty-parameter case ---------------------------------------------------------------

def test_it_recognises_the_empty_parameter():
    out = remediate("/watch/", "HeroBillboard.jsx", _DECLARED)
    assert "EMPTY parameter" in out


def test_it_names_the_route_that_does_exist():
    out = remediate("/watch/", "HeroBillboard.jsx", _DECLARED)
    assert "`/watch/:titleId` IS declared and wired" in out


def test_it_rules_out_the_three_wrong_repairs():
    """Each of #278's branches is a wasted round here."""
    out = remediate("/watch/", "HeroBillboard.jsx", _DECLARED)
    assert "do NOT add a route or repoint the link" in out


def test_it_says_to_fix_the_value():
    out = remediate("/watch/", "HeroBillboard.jsx", _DECLARED)
    assert "Fix the VALUE" in out
    assert "do not render the link at all while the id is missing" in out


def test_a_nested_parameterised_prefix_works():
    out = remediate("/browse/genre/", "GenresDropdown.jsx", _DECLARED)
    assert "EMPTY parameter" in out
    assert "/browse/genre/:genreId" in out


def test_the_component_is_named():
    assert "HoverPreview.jsx" in remediate("/watch/", "HoverPreview.jsx", _DECLARED)


# --- it must not steal the other branches ------------------------------------------------------

def test_a_declared_page_still_gets_the_wire_the_route_message():
    out = remediate("/profiles", "Nav.jsx", _DECLARED)
    assert "Wire the missing route" in out
    assert "EMPTY parameter" not in out


def test_an_undeclared_target_still_gets_the_cheap_fix():
    out = remediate("/nope", "Nav.jsx", _DECLARED)
    assert "EMPTY parameter" not in out


def test_a_reference_screen_still_gets_the_author_message():
    out = remediate("/games", "Nav.jsx", _DECLARED, {"/games"})
    assert "IS a screen in the REFERENCE design" in out
    assert "EMPTY parameter" not in out


def test_the_bare_root_is_not_treated_as_an_empty_parameter():
    """`/` ends in a slash but is not a parameterised prefix."""
    assert "EMPTY parameter" not in remediate("/", "Nav.jsx", _DECLARED)


def test_a_trailing_slash_with_no_parameterised_route_is_not_claimed():
    """Only claim the route exists when one actually does."""
    assert "EMPTY parameter" not in remediate("/settings/", "Nav.jsx", _DECLARED)


def test_a_static_route_sharing_the_prefix_does_not_count():
    """`/browse/all` is not a parameter segment."""
    assert "EMPTY parameter" not in remediate("/browse/", "Nav.jsx", {"/browse/all"})


# --- degenerate inputs ---------------------------------------------------------------------

@pytest.mark.parametrize("target", ["", None, "/watch/?x=1", "/watch/#frag"])
def test_it_never_raises(target):
    remediate(target, "Nav.jsx", _DECLARED)


def test_a_query_string_does_not_hide_the_empty_parameter():
    assert "EMPTY parameter" in remediate("/watch/?x=1", "Nav.jsx", _DECLARED)


def test_no_declared_routes_at_all_is_safe():
    remediate("/watch/", "Nav.jsx", set())


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    flat = " ".join(inspect.getsource(fa.dead_nav_link_remediation).replace("#", " ").split())
    assert "212 occurrences in r100+ against 37 before" in flat
    assert "the claim is withdrawn" in flat, "the over-claim must stay recorded"


def test_why_it_must_run_first_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
    flat = " ".join(inspect.getsource(fa.dead_nav_link_remediation).replace("#", " ").split())
    assert "the other three branches all mis-diagnose it" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
