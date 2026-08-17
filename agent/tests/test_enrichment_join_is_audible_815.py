r"""#815: the enrichment merge joins by `id` on both sides, and a miss was a silent `continue`.

#813 recorded its root cause as *"needs a live design-prep call, cannot be settled offline"*. That
is the same sentence item 112 used before #803 retired it — **a testing gap described as a
validation gap**. The call itself does need an LLM. The *join* does not.

    e_comps = {c.get("id"): c for c in es["components"]}
    for c in s["components"]:
        ec = e_comps.get(c.get("id"))
        if not ec:
            continue          # <- every enrichment for this component, gone

Both sides key on `id`. The skeleton has them (`top-nav-bar`, `page-title`). If the analyst answers
with its own (`nav_bar`, `title`) **every component misses**, the screen keeps a bare skeleton, and
nothing anywhere says so — while the frontend prompt still directs the lane to read
`build_notes`/`typography` on each one.

That is the second place the enrichment can evaporate, and it is consistent with the corpus:
`build_notes` lands 1 time in 4,006 components while `crop` — which reaches
`design_system.json` from the skeleton rather than through this merge — lands 92% of the time.

Which of the two is actually happening still needs a live run. What no longer needs one is
**knowing which**: #813 made the call audible, #815 makes the join audible, and the next run
distinguishes them in one line.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime import design_prep as dp


def _skel():
    return {"design_system": {}, "assets": [], "screens": [
        {"name": "login", "components": [{"id": "top-nav-bar"}, {"id": "page-title"}]}]}


def _enr(pairs):
    return {"screens": [{"name": "login", "components": [
        {"id": i, "build_notes": n} for i, n in pairs]}]}


def test_a_full_match_lands_the_data_and_says_nothing(caplog):
    """Non-vacuity both ways: the merge works, and a healthy screen produces no noise."""
    with caplog.at_level(logging.INFO):
        out = dp._merge_enrichment(_skel(), _enr([("top-nav-bar", "dark bar"),
                                                  ("page-title", "big h1")]))
    assert [c.get("build_notes") for c in out["screens"][0]["components"]] == \
        ["dark bar", "big h1"]
    assert not [r for r in caplog.records if "design-prep merge" in r.getMessage()]


def test_a_total_id_mismatch_warns(caplog):
    with caplog.at_level(logging.WARNING):
        dp._merge_enrichment(_skel(), _enr([("nav_bar", "x"), ("title", "y")]))
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "NONE of the 2 enriched component(s)" in msg


def test_the_warning_shows_BOTH_id_shapes():
    """★ The diagnosis is the comparison. 'the join missed' sends a reader looking;
    'nav_bar vs top-nav-bar' ends the investigation in the log line."""
    import inspect
    src = inspect.getsource(dp)
    i = src.index("#815")
    blk = src[i:src.index("return ds", i)]
    assert "sorted(e_comps)[:3]" in blk
    assert 'for c in (s.get("components") or [])][:3]' in blk


def test_it_names_the_downstream_consequence():
    import inspect
    assert "the frontend prompt still tells the lane to read them" in inspect.getsource(dp)


def test_a_partial_miss_is_info_not_warning(caplog):
    """A screen where the analyst dropped one component is not the same event as a total
    mismatch, and flagging both at WARNING is how a signal becomes noise (#793)."""
    with caplog.at_level(logging.INFO):
        dp._merge_enrichment(_skel(), _enr([("top-nav-bar", "x"), ("title", "y")]))
    recs = [r for r in caplog.records if "design-prep merge" in r.getMessage()]
    assert len(recs) == 1 and recs[0].levelno == logging.INFO
    assert "1 of 2 component(s)" in recs[0].getMessage()


def test_an_empty_enrichment_does_not_warn(caplog):
    """No enriched components at all is #813's territory (the call), not #815's (the join);
    reporting it here would double-count one failure as two."""
    with caplog.at_level(logging.INFO):
        dp._merge_enrichment(_skel(), {"screens": [{"name": "login", "components": []}]})
    assert not [r for r in caplog.records if "design-prep merge" in r.getMessage()]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
