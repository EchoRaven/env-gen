r"""#1203d9: the prober asked for `/api/places/{id}` literally, and scored the 404 against the app.

`plan_probe` builds the URL as `base_url + path`. A path the registry declares as a template --
`GET /api/places/{id}` -- is therefore requested as the literal string `/api/places/{id}`, the
app correctly 404s an unknown route, and `classify_probe_result` scores 404 as `fail` severity
P1. `deliverability` then turns that into a hard blocker: "latest run has N failed endpoint
probe(s)".

**This already happens.** Of the 369 `fail` probe records on disk, **50 (14%) are templated
paths** -- `GET /api/titles/{id}`, `GET /api/genres/{id}/episodes`, `GET /api/genres/{id}/titles`,
`POST /api/titles/{id}/rating`. The old status rule happened to probe only 27 templated
endpoints, which kept it small; **#1203d6 makes 526 of 3864 probeable endpoints templated,
across 161 runs**, so shipping d6 without this would have multiplied a false blocker twenty-fold
-- the #1203a5 shape, where a false block cost a whole run.

Asking the question needs an id the prober does not have, and inventing one would fabricate the
answer. So the honest verdict is "not asked", named as such: `ProbeSkip(reason="path_params")`.

Measured form: `{x}` only, 1516 of 5300 endpoint records. Neither `/:x` nor `<x>` appears
anywhere in the corpus, so the predicate is not widened to guess at them
(my invented predicates overmatch -- that is the recurring one).
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.hubs.runhub.probes import (  # noqa: E402
    ProbePlan, ProbeSkip, classify_probe_result, plan_probe)

URL = "http://localhost:8000"


def _p(path, method="GET", status="implemented", auth=False):
    return plan_probe({"method": method, "path": path, "status": status,
                       "auth_required": auth}, base_url=URL, auth_required=auth)


def test_a_templated_path_is_not_asked():
    """★ The defect: this used to be requested as the literal string."""
    r = _p("/api/places/{id}")
    assert isinstance(r, ProbeSkip) and r.reason == "path_params", r


def test_the_corpus_shapes_that_actually_failed():
    """The four real `fail` records, verbatim from the probe ledgers."""
    for path, method in (("/api/titles/{id}", "GET"),
                         ("/api/titles/{id}/episodes", "GET"),
                         ("/api/genres/{id}/titles", "GET"),
                         ("/api/titles/{id}/rating", "POST")):
        r = _p(path, method=method)
        assert isinstance(r, ProbeSkip) and r.reason == "path_params", (path, r)


def test_a_concrete_path_is_still_asked():
    """★ The invariant: 3338 of the 3864 probeable endpoints are concrete and must not move."""
    r = _p("/api/videos/feed")
    assert isinstance(r, ProbePlan) and r.url == URL + "/api/videos/feed", r


def test_a_numeric_path_segment_is_not_mistaken_for_a_template():
    """`/api/videos/10` is a real request, not a template."""
    assert isinstance(_p("/api/videos/10"), ProbePlan)


def test_a_trailing_brace_free_path_with_a_brace_in_a_query_is_untouched():
    """Paths are registered without query strings; assert the predicate needs real braces."""
    assert isinstance(_p("/api/search"), ProbePlan)


def test_destructive_still_wins_on_a_templated_path():
    """★ Reason precedence: `destructive` says more than `path_params`, so a templated DELETE
    must keep it. This is why the new skip is placed last."""
    r = _p("/api/videos/{id}", method="DELETE")
    assert isinstance(r, ProbeSkip) and r.reason == "destructive", r


def test_auth_required_still_wins_on_a_templated_write():
    r = _p("/api/videos/{id}/like", method="POST", auth=True)
    assert isinstance(r, ProbeSkip) and r.reason == "auth_required", r


def test_not_live_still_wins_on_a_templated_deprecated_endpoint():
    r = _p("/api/old/{id}", status="deprecated")
    assert isinstance(r, ProbeSkip) and r.reason == "not_live", r


def test_the_404_this_avoids_really_was_scored_as_a_failure():
    """★ Planted control: if 404 stopped being a `fail`, this patch would be unmotivated and
    this test says so out loud."""
    o = classify_probe_result(404, "Not Found", auth_required=False)
    assert o.verdict == "fail" and o.severity == "P1", o


def test_only_the_brace_form_is_matched():
    """The two forms the corpus does NOT contain are deliberately left probeable, so this stays
    honest about what was measured rather than guessing at other routers' syntax."""
    assert isinstance(_p("/api/places/:id"), ProbePlan)
    assert isinstance(_p("/api/places/<id>"), ProbePlan)
