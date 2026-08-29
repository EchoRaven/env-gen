"""#1154: a connection-level UI failure is not evidence about the product.

netflix-local-r12, to the minute: the stack was down 20:50-22:04 (~70
net::ERR_CONNECTION_REFUSED), `ui_flow:login_page` recorded "POST
http://localhost:8081/auth/register request_failed / ERR_CONNECTION_REFUSED",
`docker_up` succeeded at 22:04:20, and that flow never re-ran.  #757 retires a
failure only when a later pass supersedes it BY NAME, so with no re-run the
stale record stayed the newest word on its flow and blocked alone until the
no-convergence abort at 22:13 -- while the checklist read docker_build=success,
npm_install=success, backend_start=success and 8 UI records passed.

Replayed against that run's real store (9 records), failed_records goes 1 -> 0
and the sole blocker disappears; with no passing record it still blocks.
"""
from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _ui_evidence_breadth_739 as breadth, _UNREACHABLE_1154)


def _rec(flow, status, summary=""):
    return {"name": "validation:ui_flow:%s" % flow, "status": status,
            "evidence": {"summary": summary, "metadata": {"check": "ui_flow",
                                                          "flow": flow}}}


R12_SUMMARY = ("login_page signup/auth journey failed: POST "
               "http://localhost:8081/auth/register request_failed / "
               "ERR_CONNECTION_REFUSED")


def test_r12s_actual_record_stops_blocking():
    recs = [_rec("login_page", "failure", R12_SUMMARY)] + [
        _rec(n, "passed") for n in
        ("landing_page", "browse_home_page", "games_page", "tenants_page",
         "signup_page", "init-tenant_page", "genre_category_page",
         "browse_by_languages_page")]
    out = breadth(recs)
    assert out["failed_records"] == 0, out
    assert out["unreachable_records"] == 1
    assert out["pages_unreachable"] == ["login_page"]
    assert out["passed_records"] == 8


def test_with_nothing_passing_it_still_blocks():
    """No positive evidence the origin is up -> the app may really be dead."""
    out = breadth([_rec("login_page", "failure", R12_SUMMARY)])
    assert out["failed_records"] == 1, out
    assert out["unreachable_records"] == 0
    assert out["pages_failed"] == ["login_page"]


def test_a_real_product_failure_is_untouched():
    """A 4xx/5xx is the app being wrong, and must keep blocking even beside passes."""
    recs = [_rec("login_page", "failure",
                 "POST /auth/register request_failed / 500 Internal Server Error"),
            _rec("landing_page", "passed")]
    out = breadth(recs)
    assert out["failed_records"] == 1, out
    assert out["unreachable_records"] == 0


def test_bare_request_failed_is_not_enough():
    """`request_failed` also appears on 4xx/5xx, which ARE product evidence."""
    assert not any(m.lower() == "request_failed" for m in _UNREACHABLE_1154)
    out = breadth([_rec("x", "failure", "POST /auth/login request_failed"),
                   _rec("y", "passed")])
    assert out["failed_records"] == 1, out


def test_the_marker_list_covers_the_browser_spellings():
    for m in ("ERR_CONNECTION_REFUSED", "ECONNREFUSED"):
        assert m in _UNREACHABLE_1154


def test_the_discount_is_reported_not_silent():
    """Discounting silently would be the #691/#790 mistake."""
    out = breadth([_rec("login_page", "failure", R12_SUMMARY),
                   _rec("landing_page", "passed")])
    assert "unreachable_records" in out and "pages_unreachable" in out
