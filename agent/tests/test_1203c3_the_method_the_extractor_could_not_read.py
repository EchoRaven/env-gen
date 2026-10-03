r"""#1203c3: one nested brace in the options object and the call's method becomes GET.

`extract_frontend_calls` read the method with `re.match(r"[`'\"]\s*,\s*\{([^{}]*)\}", tail)`.
`[^{}]*` cannot cross a nested brace, so an options object holding `body:{...}` or
`headers:{...}` never matched and the method fell back to GET.

MEASURED on the corpus `api.js` files: 791 of 1543 extracted calls (51%) carry a nested brace in
their options, across 153 runs — half the frontend's calls reported with the wrong method.

THE HARM IS REAL. The alignment check is deliberately METHOD-TOLERANT (its own comment: a static
scan cannot tell a fetch's method from a route path), but its ERROR TEXT prints the method and
lanes act on the text: "Frontend calls unregistered endpoint(s) … GET /auth/logout, GET
/auth/signup" appears 320 times across 17 runs, and FIVE endpoints were then registered with the
invented method — `GET /auth/logout` (r135, r146), `GET /auth/signup` (r146),
`GET /api/auth/logout` (r133), `GET /auth/login` (r138). r146 carries two of them while its own
source says POST.

Verified end to end against r146's real frontend: before, all four auth calls read GET; after,
all four read POST, and one genuine `POST /api/v1/tenants` is recognised that was previously
mis-read.

★ MY FIRST DRAFT WAS WRONG AND THE DIFF CAUGHT IT. It returned "unknown" both for an options
object it could not close AND for a call with no options object at all, so r146's plain
`request('/api/search?…')` GETs became `? /api/search`. The three states are distinct: no options
object → the wrapper's default GET; options read → whatever `method:` says, else GET; options
started and never closed → unknown.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.delivery.contract_extract as CE  # noqa: E402

extract_frontend_calls = CE.extract_frontend_calls


def _opts(tail):
    """Looked up per call, not at import. ★ A module-level `from ... import` of a symbol the
    patch adds turns a missing function into a COLLECTION error — one broken file instead of the
    specific assertions that fail — and this is the SECOND time in this session I wrote that
    (the #1203c2 tests did it too)."""
    fn = getattr(CE, "_options_object_1203c3", None)
    assert fn is not None, "_options_object_1203c3 is not defined"
    return fn(tail)


def _unk():
    v = getattr(CE, "_UNKNOWN_METHOD_1203C3", None)
    assert v is not None, "_UNKNOWN_METHOD_1203C3 is not defined"
    return v


def _calls(tmp_path, src):
    fe = tmp_path / "src" / "services"
    fe.mkdir(parents=True)
    (fe / "api.js").write_text(src, encoding="utf-8")
    return set(extract_frontend_calls(tmp_path))


# ── the reader itself ─────────────────────────────────────────────────────────────────

def test_a_nested_body_no_longer_hides_the_method():
    """★ r146's own source, character for character."""
    assert _opts("',{method:'POST',body:{}})") == "method:'POST',body:{}"


def test_a_nested_headers_object_no_longer_hides_the_method():
    tail = "', {method: 'PUT', headers: {'Content-Type': 'application/json'}})"
    assert "method: 'PUT'" in (_opts(tail) or "")


def test_a_flat_options_object_still_reads():
    assert _opts("', { method: 'DELETE' })") == " method: 'DELETE' "


def test_no_options_object_is_an_empty_reading_not_an_unknown():
    """★ The distinction my first draft lost: `request('/x')` has no options and is a GET by the
    wrapper's default — returning None here turned four of r146's real GETs into `?`."""
    assert _opts("')") == ""
    assert _opts("');") == ""


def test_an_unterminated_options_object_is_unknown():
    """Started and never closed inside the window — the one case where the method is genuinely
    not knowable, and the only case the sentinel is for."""
    assert _opts("',{method:'POST',body:{") is None


def test_deep_nesting_is_followed():
    tail = "',{method:'PATCH',body:{a:{b:{c:1}}},headers:{x:{y:2}}})"
    assert "method:'PATCH'" in (_opts(tail) or "")


def test_the_window_is_bounded():
    """A runaway literal must not scan the whole file; past the window it is unknown."""
    assert _opts("',{method:'POST'," + "x" * 5000) is None


# ── the extractor's behaviour ─────────────────────────────────────────────────────────

def test_r146s_auth_calls_read_as_post(tmp_path):
    """★ The exact four calls that were registered with an invented GET."""
    src = (
        "export async function signup(b){return request('/auth/signup',"
        "{method:'POST',body:{u:1}})}\n"
        "export async function logout(){return request('/auth/logout',{method:'POST',body:{}})}\n"
        "export async function login(b){return request('/auth/login',"
        "{method:'POST',body:{u:1}})}\n")
    got = _calls(tmp_path, src)
    assert got == {"POST /auth/signup", "POST /auth/logout", "POST /auth/login"}, got
    assert not [c for c in got if c.startswith("GET")], got


def test_a_plain_get_call_is_still_get(tmp_path):
    """★ The regression my first draft introduced: no options object must stay GET, not `?`.

    The fixture is r146's own shape — `request('/api/videos/feed' + qs({...}))`, where the query
    is built by a helper and never appears in the literal. My first fixture wrote the query
    INLINE (`'/api/search?q='+q`) and expected `GET /api/search`; the extractor keeps the
    literal's query (`GET /api/search?q=`) and always has, before this patch and after. That was
    my expectation being wrong about an unrelated behaviour, not a regression — pinned here with
    the realistic shape so the test measures what it names.
    """
    got = _calls(tmp_path, (
        "export async function getFeed({cursor,limit=5}={}){"
        "const data=await request(`/api/videos/feed${qs({cursor,limit})}`);return data}\n"))
    assert got == {"GET /api/videos/feed"}, got
    assert _unk() not in "".join(got)


def test_an_options_object_without_a_method_is_get(tmp_path):
    src = "export const f = () => fetch('/api/feed', {headers:{'X-A':'b'}})\n"
    got = _calls(tmp_path, src)
    assert got == {"GET /api/feed"}, got


def test_the_sentinel_is_not_a_verb(tmp_path):
    """★ `?` must not be mistakable for an HTTP method by a reader or a downstream matcher: the
    alignment check compares PATHS, and the message is what lanes act on."""
    u = _unk()
    assert u not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
    assert len(u) <= 3 and not u.isalpha()


def test_the_path_reading_is_untouched(tmp_path):
    """#1202ge's depth-tracked PATH reading is a separate scanner and must behave as before —
    a template with a call inside it still yields the computed-path spelling."""
    src = ("export async function getVideo(id){return request("
           "`/api/videos/${encodeURIComponent(id)}`)}\n")
    got = _calls(tmp_path, src)
    assert len(got) == 1, got
    assert next(iter(got)).startswith("GET /api/videos/"), got


def test_the_wrong_method_erased_a_real_call(tmp_path):
    r"""★ The sharpest harm, found by running the PATCHED code over r146's own `api.js`:
    the invented GET does not merely mislabel, it makes two distinct calls COLLIDE.

    `extract_frontend_calls` returns a SET of "METHOD /path". r146 has two calls on one path:

        export async function listTenants(){return (await request('/api/v1/tenants')).items||[]}
        export async function createTenant(id,name){return request('/api/v1/tenants',{method:'POST',body:{id,name:name||id}})}

    The second has a nested `body:{...}`, so it read as `GET /api/v1/tenants` — the same string
    the first produces — and the POST vanished from the set entirely. Same for
    `createVideoComment` against `getComments` on `/api/videos/{id}/comments`.

    So `contract_alignment`'s `frontend_call_unregistered: 0` on r146 was computed from a set
    missing BOTH writes. A mislabelled entry is visible; an erased one is not.
    """
    calls = _calls(tmp_path, (
        "export async function listTenants(){return (await request('/api/v1/tenants')).items||[]}\n"
        "export async function createTenant(id,name){return request('/api/v1/tenants',"
        "{method:'POST',body:{id,name:name||id}})}\n"
    ))
    assert "GET /api/v1/tenants" in calls, calls
    assert "POST /api/v1/tenants" in calls, calls
    assert len([c for c in calls if c.endswith("/api/v1/tenants")]) == 2, calls


def test_the_erasure_is_what_the_old_reading_did():
    """The counter-proof, stated as the old regex rather than as a patched/unpatched run: the
    `[^{}]*` class cannot cross the nested brace, which is the whole mechanism."""
    import re
    tail = "',{method:'POST',body:{id,name:name||id}})"
    assert re.match(r"[`'\"]\s*,\s*\{([^{}]*)\}", tail) is None, "the old regex should fail here"
    inner = _opts(tail)
    assert inner and "POST" in inner, inner
