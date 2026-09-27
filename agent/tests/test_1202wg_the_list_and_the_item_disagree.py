"""#1202wg: the ids a list serves must be fetchable from that list's own item endpoint.

MEASURED over the corpus's verification chains: 324 fail across 43 runs, and the dominant
family is `GET /<resource>/{id} -> 404` -- users 26, videos 21, sounds 15 and more, 90
occurrences across 15 runs, the most recent being r137. r137's three failing chains are one
shape: step 1 takes `items.0.id` from the feed, step 2 asks for that id and receives 404
while the framework's own marker reports the table holds 39 live rows and the route ran.

Its cause there was an owner-scoped projected item read over a column the dataset never
filled (`_OWNER_COL['videos'] == 'user_id'`, 0 of 35 rows), so `None != caller` denied every
row to every caller while the unscoped list served them. That cause is fixed (#1202w9,
#1202wb); the invariant is worth holding directly, because it is domain-agnostic, the chains
only stumble into it by accident, and it names the resource rather than one id.

It pairs a list ONLY with its own item endpoint. r137's feed serves video ids under
`/api/feed/for-you`, and pairing that with `/api/videos/{id}` would be a guess -- a wrong
pairing reports a defect that does not exist.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import validation_runner as VR  # noqa: E402

BASE = "http://app.invalid"
EPS = [{"method": "GET", "path": "/api/videos"},
       {"method": "GET", "path": "/api/videos/{id}"},
       {"method": "GET", "path": "/api/feed/for-you"}]


def _list(*ids):
    return json.dumps({"items": [{"id": i} for i in ids], "total": len(ids)})


class _Fake:
    """Answers item GETs from a set of ids that exist; records every url asked."""

    def __init__(self, exists):
        self.exists = {str(x) for x in exists}
        self.calls = []

    def __call__(self, method, url, *, token=None, **kw):
        self.calls.append(url)
        rid = url.rsplit("/", 1)[-1]
        if rid in self.exists:
            return {"status": 200, "body_text": json.dumps({"item": {"id": rid}})}
        return {"status": 404, "body_text": '{"detail":"not found"}'}


def _verdict(path, body, fake, endpoints=EPS):
    old = VR._http
    VR._http = fake
    try:
        return VR._list_ids_the_item_denies_1202wg(BASE, path, None, body, endpoints)
    finally:
        VR._http = old


def test_an_id_the_item_endpoint_denies_is_named():
    fake = _Fake(exists=["1"])
    v = _verdict("/api/videos", _list(1, 2, 3), fake)
    assert v == "/api/videos/{id} denied 2 of 3 id(s) that /api/videos served: 2, 3", v


def test_a_consistent_pair_says_nothing():
    fake = _Fake(exists=["1", "2", "3"])
    assert _verdict("/api/videos", _list(1, 2, 3), fake) == ""


def test_a_list_with_no_item_endpoint_is_not_paired():
    """★ r137's feed serves VIDEO ids; guessing that pairing invents findings."""
    fake = _Fake(exists=[])
    v = _verdict("/api/feed/for-you", _list(1, 2), fake)
    assert v == "", (
        "there is no /api/feed/for-you/{id} in the contract, so nothing contradicts it: %r" % v)
    assert fake.calls == [], "no request may be sent for a pairing we did not find"


def test_a_nested_item_path_is_not_mistaken_for_the_pair():
    """`/api/videos/{id}/comments` is two segments deeper and is not this list's item."""
    eps = [{"method": "GET", "path": "/api/videos"},
           {"method": "GET", "path": "/api/videos/{id}/comments"}]
    fake = _Fake(exists=[])
    assert _verdict("/api/videos", _list(1), fake, endpoints=eps) == ""
    assert fake.calls == []


def test_a_post_item_route_is_not_a_read():
    eps = [{"method": "GET", "path": "/api/videos"},
           {"method": "POST", "path": "/api/videos/{id}"}]
    fake = _Fake(exists=[])
    assert _verdict("/api/videos", _list(1), fake, endpoints=eps) == ""


def test_at_most_five_ids_are_probed():
    fake = _Fake(exists=[])
    v = _verdict("/api/videos", _list(*range(1, 21)), fake)
    assert "denied 5 of 5" in v, v
    assert len(fake.calls) == 5, (
        "a list of 20 must not become 20 requests against the app under test: %r" % fake.calls)


def test_a_body_without_ids_is_not_a_finding():
    fake = _Fake(exists=[])
    body = json.dumps({"items": [{"caption": "a"}, {"caption": "b"}], "total": 2})
    assert _verdict("/api/videos", body, fake) == ""
    assert fake.calls == []


def test_a_bare_list_body_is_read_too():
    fake = _Fake(exists=["1"])
    v = _verdict("/api/videos", json.dumps([{"id": 1}, {"id": 2}]), fake)
    assert "denied 1 of 2" in v, v


def test_a_non_404_is_not_a_denial():
    """A 500 is a different defect and #157 already carries it; do not relabel it."""
    class Boom(_Fake):
        def __call__(self, method, url, *, token=None, **kw):
            self.calls.append(url)
            return {"status": 500, "body_text": "boom"}

    assert _verdict("/api/videos", _list(1, 2), Boom(exists=[])) == ""


def test_the_recorder_writes_a_readable_row(tmp_path):
    ok = VR.record_list_ids_the_item_denies_1202wg(tmp_path, ["/api/videos/{id} denied 1 of 1"])
    assert ok
    p = tmp_path / "logs" / "list_ids_the_item_denies_1202wg.jsonl"
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["count"] == 1 and row["endpoints"] == ["/api/videos/{id} denied 1 of 1"]


def test_the_recorder_writes_nothing_for_no_findings(tmp_path):
    assert VR.record_list_ids_the_item_denies_1202wg(tmp_path, []) is False
    assert not (tmp_path / "logs").exists()
