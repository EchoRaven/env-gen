"""#1202wa: prove a list's rows are out of reach before reporting that they are.

#1202w0 walks an endpoint's own cursor and reports when the walk cannot reach the `total`
the endpoint itself states. MEASURED over the 19 `items`/`total` endpoints of four
delivered stacks: 17 (89%) carry no `next_cursor` key at all, so that walk ends on the
first page and any of them whose `total` exceeds a page would be reported on no evidence.

The two live cases that separate a missing cursor from missing rows:
  r126 `/api/creators/suggested` -- total=92, first page 20, no cursor. `limit=92` returns
    all 92: the rows are reachable, only the cursor is absent. Nothing to report.
  r135 `/api/feed/foryou` -- total=39, first page 8, HAS a cursor whose value is None.
    `limit=39` is refused 400 (the handler caps limit at 20), and two INNER JOINs drop the
    31 rows `total` counts. Genuinely unreachable, and still reported.

So the detector now spends one request asking for `total` rows outright. The asymmetry is
the point: only a 200 that actually carries them clears the finding, because the question
is "is reachability proven?", never "is the endpoint fine?".
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "env_generator", "llm_generator"))

from multi_agent.runtime import validation_runner as VR  # noqa: E402

BASE = "http://app.invalid"
PATH = "/api/things"


def _body(n_items, total, cursor=..., start=0):
    d = {"items": [{"id": start + i} for i in range(n_items)], "total": total}
    if cursor is not ...:
        d["next_cursor"] = cursor
    return json.dumps(d)


class _Fake:
    """Records every GET and answers `limit=` however the case under test demands."""

    def __init__(self, limit_status=200, limit_items=None):
        self.calls = []
        self.limit_status = limit_status
        self.limit_items = limit_items

    def __call__(self, method, url, *, token=None, **kw):
        self.calls.append(url)
        if "limit=" in url:
            if self.limit_status != 200:
                return {"status": self.limit_status, "body_text": '{"detail":"nope"}'}
            n = self.limit_items
            return {"status": 200, "body_text": _body(n, n if n is not None else 0, None)}
        return {"status": 404, "body_text": ""}


def _verdict(first_body, fake):
    old = VR._http
    VR._http = fake
    try:
        return VR._list_total_unreachable_1202w0(BASE, PATH, None, first_body)
    finally:
        VR._http = old


def test_a_cursorless_list_whose_limit_returns_everything_is_not_reported():
    fake = _Fake(limit_items=92)
    assert _verdict(_body(20, 92), fake) == "", (
        "limit=92 returned all 92 rows, so nothing is out of reach"
    )
    assert any("limit=92" in u for u in fake.calls), (
        "the claim must be corroborated by an actual request: %r" % fake.calls
    )


def test_a_refused_limit_keeps_the_finding():
    """r135's shape: the handler caps `limit`, so the rows really cannot be fetched."""
    fake = _Fake(limit_status=400)
    v = _verdict(_body(8, 39, cursor=None), fake)
    assert v == "%s total=39 reachable=8" % PATH, v


def test_a_limit_that_returns_a_short_page_keeps_the_finding():
    fake = _Fake(limit_items=8)
    v = _verdict(_body(8, 39, cursor=None), fake)
    assert v == "%s total=39 reachable=8" % PATH, v


def test_an_unparseable_limit_response_keeps_the_finding():
    class Junk(_Fake):
        def __call__(self, method, url, *, token=None, **kw):
            self.calls.append(url)
            return {"status": 200, "body_text": "<html>not json</html>"}

    v = _verdict(_body(8, 39, cursor=None), Junk())
    assert v == "%s total=39 reachable=8" % PATH, v


def test_an_absurd_total_is_never_requested():
    """A limit above the cap would be a denial of service against the app under test."""
    fake = _Fake(limit_items=10 ** 6)
    v = _verdict(_body(20, 10 ** 6, cursor=None), fake)
    assert v == "%s total=1000000 reachable=20" % PATH, v
    assert not any("limit=" in u for u in fake.calls), (
        "no request may be sent for a total above the cap: %r" % fake.calls
    )


def test_a_total_the_first_page_already_covers_costs_no_request():
    fake = _Fake(limit_items=5)
    assert _verdict(_body(5, 5), fake) == ""
    assert fake.calls == [], "a satisfied list must not be probed at all: %r" % fake.calls


def test_the_probe_appends_to_an_existing_query_string():
    fake = _Fake(limit_items=30)
    old = VR._http
    VR._http = fake
    try:
        VR._list_total_unreachable_1202w0(BASE, PATH + "?sort=new", None, _body(10, 30))
    finally:
        VR._http = old
    assert any(u.endswith("?sort=new&limit=30") for u in fake.calls), (
        "a second parameter must be joined with `&`, not a second `?`: %r" % fake.calls
    )
