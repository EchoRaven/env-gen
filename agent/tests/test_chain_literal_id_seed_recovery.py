"""FIX #144 — literal-id 404 recovery: add a SEED-DATA rung to the ladder.

run-66 M2 live (4th occurrence of the literal-id class): verifier chain step
`POST /api/posts/9/like` 404'd (seed has posts 1-6). #136's ladder failed all
three rungs: no same-resource captured id (the chain never creates a post —
no POST /api/posts by contract), live list recovery 404'd (posts are listed
via /api/feed, NOT /api/posts — the known collection-name-mismatch blind
spot), and the global last_id was a wrong-resource id. The verifier then
livelocked yielding "blocked: missing POST /api/posts" until the 75-min
no-convergence wall.

The framework KNOWS which ids exist after every clean boot: the authored
app/backend/seed_data.json (#130/#135 guarantee those rows are present).
New rung between live-list and global-last_id: seed_ids[resource] — the
first row with an explicit non-None id. Deterministic, no network, immune
to collection-name mismatches.
"""
import json
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce


def test_load_seed_ids(tmp_path):
    seed = {"users": [{"id": 1}, {"id": 2}],
            "posts": [{"id": 5, "caption": "x"}],
            "follows": [{"follower_id": 1, "followee_id": 2}],  # no explicit id
            "not_a_table": "str"}
    p = tmp_path / "app" / "backend"
    p.mkdir(parents=True)
    (p / "seed_data.json").write_text(json.dumps(seed))
    ids = ce.load_seed_ids(tmp_path)
    assert ids == {"users": 1, "posts": 5}


def test_load_seed_ids_missing_file(tmp_path):
    assert ce.load_seed_ids(tmp_path) == {}


def _mk_http(responses):
    calls = []

    def fake_http(method, url, token=None, body=None, **kw):
        calls.append((method, url))
        for frag, resp in responses:
            if frag in url:
                return resp
        return {"status": 404, "body_text": '{"detail":"Not found"}'}
    return fake_http, calls


def test_literal_id_404_recovers_via_seed(monkeypatch):
    # POST /api/posts/9/like → 404; list /api/posts also 404 (feed mismatch);
    # seed says posts→1 → retry /api/posts/1/like → 201 → step passes.
    fake_http, calls = _mk_http([
        ("/api/posts/1/like", {"status": 201, "body_text": "{}"}),
    ])
    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "like-chain", "steps": [
        {"method": "POST", "path": "/api/posts/9/like", "expect": [200, 201]},
    ]}
    r = ce.execute_chain("http://x", chain, seed_ids={"posts": 1})
    assert any("/api/posts/1/like" in u for _, u in calls), calls
    assert r["steps"][0]["ok"] is True, r["steps"]


def test_seed_rung_does_not_mask_truly_broken_endpoint(monkeypatch):
    # even with the seed id, the endpoint 500s → step honestly broken
    fake_http, _ = _mk_http([
        ("/api/posts/1/like", {"status": 500, "body_text": "boom"}),
    ])
    monkeypatch.setattr(ce, "_http", fake_http)
    chain = {"name": "like-chain", "steps": [
        {"method": "POST", "path": "/api/posts/9/like", "expect": [200, 201]},
    ]}
    r = ce.execute_chain("http://x", chain, seed_ids={"posts": 1})
    assert r["steps"][0]["ok"] is False, "genuinely broken endpoint must still fail"


def test_run_chains_threads_seed_ids(tmp_path, monkeypatch):
    # run_chains loads seed ids from the project dir and execute_chain uses them
    p = tmp_path / "app" / "backend"
    p.mkdir(parents=True)
    (p / "seed_data.json").write_text(json.dumps({"posts": [{"id": 3}]}))
    chains_rel = Path(ce.CHAINS_STORE_RELPATH)
    cp = tmp_path / chains_rel
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps({"like": {
        "name": "like", "status": "registered",
        "steps": [{"method": "POST", "path": "/api/posts/9/like",
                   "expect": [200, 201]}]}}))
    fake_http, calls = _mk_http([
        # normalize_steps prepends POST /auth/register to every chain (the token
        # source). Unstubbed it 404s, and every later step is then "skipped —
        # depends on token from a failed earlier step", so the like step this
        # test is about never runs at all.
        ("/auth/register", {"status": 201,
                            "body_text": '{"access_token": "t"}'}),
        ("/api/posts/3/like", {"status": 201, "body_text": "{}"}),
    ])
    monkeypatch.setattr(ce, "_http", fake_http)
    r = ce.run_chains("http://x", tmp_path, [])
    assert any("/api/posts/3/like" in u for _, u in calls), calls
    # normalize_steps prepends an /auth/register step — assert on the LIKE step
    _like = [s for s in r["chains"][0]["steps"] if "like" in str(s.get("action"))][0]
    assert _like["ok"] is True, r["chains"]
