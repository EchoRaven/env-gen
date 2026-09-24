"""#1202ga -- the schema is the contract; metadata is a mirror of it.

`resolve_endpoint_auth` read the top-level key and the registration-time metadata mirror,
never `schema.auth_required` — which is what `register_endpoint(schema=...)` writes. So a
lane that updated its own contract had no effect at all.

tiktok-r97 end to end, and it is why that run never delivered:

  * the verifier relayed six "unauthenticated API returns 401" bugs to backend (the relay
    the dispatcher's own text asks for: "a 4xx/5xx from the API is BACKEND");
  * backend applied #320's public-read declaration -- schema.auth_required = False on
    /api/videos/{id}, its comments, and /api/live -- and truthfully marked them completed;
  * every one still carried metadata.auth_required = True from its first registration, so
    this resolver returned True, the routes kept projecting Depends(get_current_user), and
    the logged-out flow failed on the same 401 for the rest of the run.

The lane did the right thing six times and the framework ignored it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime.route_projector import resolve_endpoint_auth  # noqa: E402


def _ep(schema_auth=..., meta_auth=..., top_auth=...):
    ep = {"method": "GET", "path": "/api/videos/{id}", "schema": {}}
    if schema_auth is not ...:
        ep["schema"]["auth_required"] = schema_auth
    if top_auth is not ...:
        ep["auth_required"] = top_auth
    meta = {}
    if meta_auth is not ...:
        meta["auth_required"] = meta_auth
    return ep, meta


def test_a_public_declaration_in_the_schema_takes_effect():
    """r97's exact shape: the lane declared it public, the stale mirror said otherwise."""
    ep, meta = _ep(schema_auth=False, meta_auth=True)
    assert resolve_endpoint_auth("GET", ep["path"], ep, meta) is False, (
        "the lane's contract update was ignored in favour of the registration mirror")


def test_an_auth_declaration_in_the_schema_also_takes_effect():
    ep, meta = _ep(schema_auth=True, meta_auth=False)
    assert resolve_endpoint_auth("GET", ep["path"], ep, meta) is True


def test_the_top_level_still_outranks_the_schema():
    """#1097 treats the top-level key as the most explicit statement; unchanged."""
    ep, meta = _ep(schema_auth=True, meta_auth=True, top_auth=False)
    assert resolve_endpoint_auth("GET", ep["path"], ep, meta) is False


def test_metadata_still_answers_when_the_schema_is_silent():
    """Records that only ever set the mirror must not start reading differently."""
    ep, meta = _ep(meta_auth=True)
    assert resolve_endpoint_auth("GET", ep["path"], ep, meta) is True
    ep, meta = _ep(meta_auth=False)
    assert resolve_endpoint_auth("GET", ep["path"], ep, meta) is False


def test_an_unstated_endpoint_keeps_its_shape_default():
    """#r58's rule is untouched: unstated means 'decide from the shape'."""
    ep, meta = _ep()
    assert resolve_endpoint_auth("POST", "/api/videos", ep, meta) is True   # a write
    assert resolve_endpoint_auth("GET", "/api/videos", ep, meta) is False   # a public read
    assert resolve_endpoint_auth("GET", "/api/me", ep, meta) is True        # self read


def test_a_none_in_the_schema_is_unstated_not_false():
    """The #r58 trap: a PRESENT-but-None key must not read as 'public'."""
    ep, meta = _ep(schema_auth=None)
    assert resolve_endpoint_auth("POST", "/api/videos", ep, meta) is True


_EMITTER_TABLES = {
    "users": {"name": "users", "schema": {"columns": [
        {"name": "id", "type": "integer", "primary_key": True},
        {"name": "email", "type": "text"}]}},
    "videos": {"name": "videos", "metadata": {"owner_scoped_reads": True},
               "schema": {"columns": [
                   {"name": "id", "type": "integer", "primary_key": True},
                   {"name": "author_id", "type": "integer", "references": "users.id"},
                   {"name": "caption", "type": "text"}]}},
}


def _emitted_feed(schema_auth, meta_auth):
    from multi_agent.runtime.backend_skeleton import render_skeleton_main
    ep = {"method": "GET", "path": "/api/videos",
          "schema": {"auth_required": schema_auth},
          "metadata": {"auth_required": meta_auth}}
    src = render_skeleton_main([ep], _EMITTER_TABLES)
    keep, body = False, []
    for line in src.split("\n"):
        if "def _projected_get_api_videos" in line:
            keep = True
        elif keep and line.startswith("@app."):
            break
        if keep:
            body.append(line)
    return "\n".join(body)


def test_the_emitter_agrees_with_the_resolver():
    """#1097's premise is ONE RULE, ONE PRODUCER — backend_skeleton must see the schema
    declaration too, or the two emitters drift again.

    Asserted on the EMITTED handler in both directions rather than on the name of a local
    in the emitter's source. #1202hi replaced that local's hand-rolled three-copy test with
    the shared reader, so the identifier this used to grep for is gone while the property it
    stood for got stronger — a behavioural check cannot go stale that way, and it also
    catches an emitter that reads the right copy and then ignores it.
    """
    ep_pub = {"schema": {"auth_required": False}, "metadata": {"auth_required": True}}
    assert resolve_endpoint_auth("GET", "/api/videos", ep_pub, ep_pub["metadata"]) is False
    pub = _emitted_feed(False, True)
    assert pub, "the feed handler was not projected at all"
    assert "get_current_user" not in pub, (
        "the skeleton still ignores the schema declaration:\n" + pub)

    ep_auth = {"schema": {"auth_required": True}, "metadata": {"auth_required": False}}
    assert resolve_endpoint_auth("GET", "/api/videos", ep_auth, ep_auth["metadata"]) is True
    gated = _emitted_feed(True, False)
    assert "get_current_user" in gated, (
        "a stale mirror must not open a read the contract protects:\n" + gated)


def test_r97s_contract_resolves_the_way_the_lane_declared():
    """The four shapes r97 actually held, in one assertion."""
    cases = [
        ({"auth_required": False}, {"auth_required": True}, False),   # lane made it public
        ({"auth_required": True}, {"auth_required": True}, True),     # untouched, authed
        ({}, {}, None),                                               # unstated
    ]
    for schema, meta, expected in cases:
        ep = {"method": "GET", "path": "/api/videos/{id}", "schema": schema}
        got = resolve_endpoint_auth("GET", ep["path"], ep, meta)
        if expected is not None:
            assert got is expected, f"{schema}/{meta} -> {got}"
