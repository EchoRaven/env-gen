r"""#764: a deterministic repair rewrote `/watch/${id}` to `/tenants` in a video app.

`repair_dead_nav_links` (#493) does not advise — it EDITS the source, repointing a dead nav
target at "the nearest existing route" by last-segment token overlap. Its own docstring says
"Classification mirrors ``dead_nav_link_remediation``", and that mirror was made by hand.

#690 taught the MESSAGE path that a target ending in `/` whose parameterised route IS declared
is not a routing defect at all — it is `/watch/${title.id}` with an undefined id. The repair
never learned it. r149:

    components/EpisodeList.jsx:    /watch/ -> /tenants
    components/HeroBillboard.jsx:  /watch/ -> /tenants
    components/HeroBillboard.jsx:  /title/ -> /tenants
    components/HoverPreviewCard.jsx: /watch/ -> /tenants

`/watch/:titleId` was declared and wired the whole time. Token overlap found nothing for `watch`,
so the positional fallback chose whatever came first. **A bad message costs a round; this costs
the links** — every play control in the app now navigates to an unrelated page.

The root cause is the duplicated classification, so the fix is one predicate with two callers:
`is_empty_param_prefix_690`, used by the message path and by the repair.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


# --- the predicate ------------------------------------------------------------------------------

@pytest.mark.parametrize("target,declared,expected", [
    ("/watch/", {"/watch/:titleId", "/browse"}, True),
    ("/title/", {"/title/:id"}, True),
    ("/browse/genre/", {"/browse/genre/:genreId"}, True),
    ("/watch/", {"/browse", "/tenants"}, False),      # no param route -> a real dead link
    ("/shop", {"/shop/:id"}, False),                  # no trailing slash -> not this shape
    ("/", {"/:x"}, False),                            # root is never this
    ("/watch/", set(), False),
    ("/watch/", None, False),
])
def test_the_predicate(target, declared, expected):
    assert fa.is_empty_param_prefix_690(target, declared) is expected


def test_a_deeper_param_does_not_count():
    """`/a/` must not match `/a/b/:id` — the param has to be the NEXT segment, or the target is
    a genuinely dead intermediate path."""
    assert fa.is_empty_param_prefix_690("/a/", {"/a/b/:id"}) is False


@pytest.mark.parametrize("junk", [None, "", 5, "notapath"])
def test_junk_never_raises(junk):
    assert fa.is_empty_param_prefix_690(junk, {"/x/:y"}) is False


# --- both callers use it ---------------------------------------------------------------------------

def test_the_message_path_uses_the_shared_predicate():
    src = inspect.getsource(fa.dead_nav_link_remediation)
    assert "is_empty_param_prefix_690(target, declared_pages)" in src


def test_the_repair_uses_the_shared_predicate_and_bails():
    src = inspect.getsource(fs.repair_dead_nav_links)
    assert "is_empty_param_prefix_690(target, declared)" in src
    i = src.index("is_empty_param_prefix_690")
    assert "return None" in src[i:src.index("tgt_toks", i)], "it must decline, not repoint"


def test_the_repair_looks_in_the_set_that_HAS_param_routes():
    """`static_routes` deliberately excludes every `:param` route, so passing it would make the
    guard vacuous — the #734 failure mode. It must read `declared`."""
    src = inspect.getsource(fs.repair_dead_nav_links)
    assert "is_empty_param_prefix_690(target, static_routes)" not in src
    assert src.index("declared = {") < src.index("is_empty_param_prefix_690")


def test_the_guard_runs_before_any_candidate_is_chosen():
    src = inspect.getsource(fs.repair_dead_nav_links)
    assert src.index("is_empty_param_prefix_690") < src.index("nearest existing route by last-segment")


# --- the message path is unchanged for everything else ------------------------------------------------

def test_a_genuinely_invented_link_still_gets_the_cheap_fix():
    msg = fa.dead_nav_link_remediation("/shop", "Nav.jsx", {"/browse"}, reference_routes=set())
    assert "CHEAPEST FIX FIRST" in msg


def test_a_declared_page_with_no_route_still_says_wire_it():
    msg = fa.dead_nav_link_remediation("/profile", "Nav.jsx", {"/profile"}, reference_routes=set())
    assert "Wire the missing route" in msg


def test_the_empty_param_message_still_names_the_real_fix():
    msg = fa.dead_nav_link_remediation("/watch/", "Hero.jsx", {"/watch/:titleId"})
    assert "EMPTY parameter" in msg
    assert "do NOT add a route or repoint the link" in msg


# --- provenance -------------------------------------------------------------------------------------------

def test_the_r149_damage_is_recorded():
    d = " ".join((fa.is_empty_param_prefix_690.__doc__ or "").split())
    assert "/watch/ -> /tenants" in d
    assert "MUTATING the source" in d


def test_the_root_cause_is_named_as_duplication():
    d = " ".join((fa.is_empty_param_prefix_690.__doc__ or "").split())
    assert "Classification mirrors" in d
    assert "One predicate, two callers" in d


def test_the_repair_records_why_this_is_worse_than_a_bad_message():
    src = " ".join(inspect.getsource(fs.repair_dead_nav_links).replace("#", " ").split())
    assert "A bad message costs a round; this costs the links" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
