r"""#1203d2: a `/me` endpoint cannot be public, so "the probe is probably mis-authored" is wrong.

When a denial probe gets a 2xx, `_contract_public_note_1202ib` attaches, verbatim:

    CONTRACT SAYS PUBLIC: this endpoint states auth_required=False (last written by …), so the
    projected handler carries no guard and a 2xx is what it is BUILT to answer — THIS PROBE IS
    PROBABLY MIS-AUTHORED. If the endpoint really must deny, change the CONTRACT first.

For a path whose last segment is `me` that is backwards: an endpoint returning the CALLER'S OWN
record is auth-required by definition, so the contract is the defect and the probe is right.

MEASURED, resolving auth through `_stated_auth_1202hi` (all three places a record can state it —
my first pass read only the top level and wrongly concluded the field is never set): of the 58
corpus endpoints whose last segment is `me`, **49 resolve auth-required, 3 to nothing, 6 to
PUBLIC** — r58, r121, r123, r135, r144 and r148 (live). Three of the six carry
`schema=False, metadata=True`, the self-disagreeing shape #1202hi measured 220 of.

r148 live: `GET /api/me` resolves public, its denial probe got 200 where 401 was expected,
`business_chain_failing` blocks the run, and the note told the lane its own probe was wrong.

★ THE PRECEDENT IS TEN LINES UP in the same function: #1202vc carves out the authorization
server for exactly this reason, and its comment states the rule — "A true finding arriving with
a framework-authored dismissal attached is worse than no note."
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.chain_executor as CE  # noqa: E402


def _eps(path, auth, who="backend", method="GET"):
    """★ A LIST of endpoint mappings, not a dict keyed by "METHOD /path".
    `_match_endpoint_template_1202id` does `for ep in endpoints or []` and skips anything that
    is not a Mapping — handed a dict it iterates the KEYS (strings) and matches nothing. My
    first fixture was the dict shape and the note came back empty for every case, including the
    one that must pass unpatched."""
    return [{"method": method, "path": path,
             "schema": {"auth_required": auth},
             "_updated_by": who}]


def _note(path, auth=False, method="GET"):
    return CE._contract_public_note_1202ib(method, path, _eps(path, auth, method=method))


def _pred():
    fn = getattr(CE, "_is_own_identity_path_1203d2", None)
    assert fn is not None, "_is_own_identity_path_1203d2 is not defined"
    return fn


# ── the predicate ─────────────────────────────────────────────────────────────────────

def test_the_six_live_shapes_match():
    """Every path the corpus actually has in this state, verbatim."""
    f = _pred()
    for p in ("/api/me", "/api/users/me", "/auth/me", "/me"):
        assert f(p) is True, p


def test_it_is_a_segment_test_not_a_substring():
    """★ Matched the way #1202vc matches: a SEGMENT, so ordinary business paths are untouched."""
    f = _pred()
    for p in ("/api/theme", "/api/members", "/api/me/settings", "/api/home", "/api/media"):
        assert f(p) is False, p


def test_it_folds_case_and_strips_the_api_prefix_and_query():
    f = _pred()
    assert f("/API/ME") is True
    assert f("/api/me/") is True
    assert f("/api/me?expand=1") is True


def test_nothing_is_invented_beyond_the_measured_signal():
    """`current_user` / `whoami` appear nowhere in the corpus; a predicate I invent overmatches."""
    f = _pred()
    assert f("/api/current_user") is False
    assert f("/api/whoami") is False


# ── the note ──────────────────────────────────────────────────────────────────────────

def test_a_public_me_is_told_the_contract_is_wrong():
    """★ r148's live case."""
    n = _note("/api/me", auth=False)
    assert "OWN-IDENTITY ENDPOINT" in n, n
    assert "the probe is right" in n, n
    assert "auth_required=True" in n, n


def test_it_does_not_tell_the_lane_to_weaken_the_probe():
    """The exact harm: a true finding arriving with a framework-authored dismissal."""
    n = _note("/api/me", auth=False)
    assert "mis-authored" not in n, n
    assert "Do NOT weaken the probe" in n, n


def test_it_still_names_who_wrote_the_contract():
    n = _note("/api/me", auth=False)
    assert "backend" in n, n


def test_an_ordinary_public_endpoint_keeps_the_old_note():
    """★ The 52 `/me` endpoints that are NOT public never reach here, and a genuinely public
    business read must still get #1202ib's original advice unchanged."""
    n = _note("/api/videos", auth=False)
    assert "CONTRACT SAYS PUBLIC" in n, n
    assert "probably mis-authored" in n, n
    assert "OWN-IDENTITY" not in n, n


def test_a_me_endpoint_that_requires_auth_produces_no_note_at_all():
    """The note only ever renders when the contract resolved to PUBLIC — the 49 healthy ones
    are untouched, which is what keeps the blast radius at six."""
    assert _note("/api/me", auth=True) == ""


def test_the_carve_out_is_checked_before_the_general_note():
    """★ Structural: order matters. Below the general return it would be dead code."""
    import ast
    import inspect

    src = inspect.getsource(CE._contract_public_note_1202ib)
    i_own = src.find("_is_own_identity_path_1203d2")
    i_gen = src.find("CONTRACT SAYS PUBLIC")
    assert i_own != -1, "the carve-out is gone"
    assert i_own < i_gen, "the /me carve-out sits AFTER the general note — it can never run"
