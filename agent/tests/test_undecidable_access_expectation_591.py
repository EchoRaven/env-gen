r"""#591: the MIRROR of #586 — an expectation nothing can FALSIFY.

#586 rejects a chain asking one request to answer two ways. #591 rejects the opposite: a
BUSINESS step whose `expect` accepts both a 2xx and 401/403 passes whether the app SERVED the
data or REFUSED the caller. It proves nothing about access control, and still counts toward the
green chain total the delivery gate reads.

Measured over 1682 chains / 5861 business steps carrying an explicit expectation: 56 such steps
in 16 runs, on exactly the resources every owner-scoping leak in this arc lived on —
`/api/my-list` x26, `/api/titles/{id}/rating` x8, `/api/continue-watching` x6, `/api/profiles`
x2. r133 (the #568 live cross-user leak) has 12; r142, one of the three *** MULTI-MILESTONE
VALIDATED *** runs, has 13.

Scope is narrow on purpose. Control-plane paths are exempt — there a chain legitimately means
"this surface exists and answers sanely" and cannot know if its user is an admin (654 of the 710
arc-wide wide-expectation steps are exactly that). 409 and 404 are not denial codes, so
`POST /auth/register [200,201,409]` — the most common wide expectation in the whole arc — is
untouched.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    undecidable_access_expectations as blind,
)


def _s(method, path, expect=None, **kw):
    st = {"method": method, "path": path, **kw}
    if expect is not None:
        st["expect"] = expect
    return st


# --- the real shapes found in the arc ---------------------------------------------------------

def test_the_r142_my_list_shape_is_rejected():
    got = blind([_s("POST", "/api/my-list", [200, 201, 401, 403])])
    assert len(got) == 1
    i, p, codes = got[0]
    assert (i, p) == (0, "POST /api/my-list")
    assert codes == [200, 201, 401, 403]


def test_every_arc_shape_on_a_business_resource_is_caught():
    steps = [_s("GET", "/api/my-list", [200, 401, 403]),
             _s("DELETE", "/api/my-list/1", [200, 204, 401, 403, 404]),
             _s("POST", "/api/titles/1/rating", [200, 201, 401, 403]),
             _s("GET", "/api/continue-watching", [200, 401]),
             _s("GET", "/api/profiles", [200, 403])]
    assert [i for i, _, _ in blind(steps)] == [0, 1, 2, 3, 4]


def test_a_query_string_does_not_hide_the_step():
    got = blind([_s("GET", "/api/my-list?profile_id=3", [200, 403])])
    assert got and got[0][1] == "GET /api/my-list"


# --- what must NOT be rejected -----------------------------------------------------------------

def test_the_most_common_wide_expectation_in_the_arc_is_untouched():
    """`POST /auth/register [200,201,409]` — idempotent setup, and control-plane besides."""
    assert blind([_s("POST", "/auth/register", [200, 201, 409])]) == []


def test_409_and_404_are_not_denial_codes():
    assert blind([_s("POST", "/api/my-list", [200, 201, 409])]) == []
    assert blind([_s("DELETE", "/api/my-list/1", [200, 204, 404])]) == []


def test_control_plane_tolerance_stays_legal():
    """654 of the arc's 710 wide-expectation steps are these — a chain cannot know whether
    its user is an admin, and 'the surface answers sanely' is the actual intent."""
    for path in ("/api/v1/tenants", "/api/v1/reset", "/api/v1/admin/init-tenant",
                 "/oauth/authorize", "/oauth/token", "/auth/login",
                 "/health", "/.well-known/jwks.json"):
        assert blind([_s("POST", path, [200, 302, 400, 401, 403, 422])]) == [], path


def test_a_pure_denial_probe_is_the_encouraged_shape():
    assert blind([_s("GET", "/api/my-list", [403], auth="intruder")]) == []
    assert blind([_s("GET", "/api/my-list", [401, 403])]) == []


def test_a_plain_success_expectation_is_decidable():
    assert blind([_s("GET", "/api/my-list", [200])]) == []
    assert blind([_s("GET", "/api/my-list", 200)]) == []


def test_no_expectation_means_must_succeed_and_is_left_alone():
    """An absent `expect` is decidable (2xx required) — never report it."""
    assert blind([_s("GET", "/api/my-list")]) == []


def test_junk_is_inert():
    assert blind([]) == []
    assert blind([None, "nope", {}]) == []
    assert blind([_s("GET", "/api/my-list", ["oops", "403"])]) == []   # no 2xx parsed


# --- registration wiring ------------------------------------------------------------------------

def _register(hub, steps, name="c1"):
    return hub.register_verification_chain(
        name=name, steps=steps, agent="verifier")


@pytest.fixture()
def hub(tmp_path):
    from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub
    return RegistryHub(str(tmp_path))


def test_the_chain_is_refused_at_registration(hub):
    res = _register(hub, [_s("POST", "/auth/register", [200, 201, 409], save={"token": "access_token"}),
                          _s("GET", "/api/my-list", [200, 403], auth="token")])
    assert isinstance(res, dict) and res.get("error")
    assert "undecidable access expectation" in res["error"]


def test_the_refusal_says_how_to_express_what_was_meant(hub):
    res = _register(hub, [_s("GET", "/api/my-list", [200, 403], auth="token")])
    msg = res.get("error", "")
    assert "SEPARATE step" in msg and "different actor" in msg and "foreign id" in msg
    assert "409 and 404 are not denial codes" in msg
    assert "/oauth" in msg          # names the exemption so the verifier isn't confused


def test_a_clean_chain_still_registers(hub):
    res = _register(hub, [_s("POST", "/auth/register", [200, 201, 409], save={"token": "access_token"}),
                          _s("GET", "/api/my-list", [200], auth="token")])
    assert not (isinstance(res, dict) and res.get("error")), res


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
