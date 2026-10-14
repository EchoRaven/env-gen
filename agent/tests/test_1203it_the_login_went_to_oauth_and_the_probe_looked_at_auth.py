r"""#1203it: the probe watched `/auth/` only, and told an app that logs in via /oauth/ that
its form issued no auth request at all.

`_ui_auth_flow` attaches three listeners — response, request, requestfailed — and all three
tested `"/auth/" in url`. That is the literal #1203g1 removed from `test_user_runner`,
because it matches neither `/oauth/token` (the framework's own OAuth2 token endpoint) nor
`/api/oauth/*`. `lifecycle` says of this exact constant that "six modules re-listed this
surface and all six omitted the same three"; `test_user_validation` was a seventh, and
re-listed it THREE times.

#1203g1 could call its own fix drift-closing, because it measured 0 frontends calling
/oauth/. THAT IS NO LONGER TRUE, and this ticket has the run:

    generated/instagram-core-r176/app/frontend/src/pages/LoginPage.jsx
        window.location.assign(`/oauth/authorize?client_id=instagram-web&redirect_uri=...`)

    its login flow, recorded:
        "the login form issued NO auth request, and the token in storage was left by an
         earlier flow"

The form issued one. These listeners could not see where it went. The app was fine — the
same sentence #670 and #1203ip each had to write about this probe.

The surface itself is owned by `lifecycle.FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl` and derived
once in `test_user_runner`; this module imports that tuple rather than re-filtering it, so the
"drop well-known" rule has no second copy either (#1032).
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur
from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

SRC = inspect.getsource(tuv)
SURFACE = tur._AUTH_OBSERVED_PREFIXES_1203G1


def _flow():
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_ui_auth_flow":
            return node
    raise AssertionError("_ui_auth_flow is gone")


LISTENERS = ("_on_resp", "_on_req_1203a6", "_on_reqfail_1203a6")


def _listener(name):
    for node in ast.walk(_flow()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("%s is gone" % name)


# --- the surface, which is what the predicate resolves to --------------------------------------

def test_the_login_url_from_r176_is_on_the_watched_surface():
    """The live miss, verbatim from that run's LoginPage."""
    url = "/oauth/authorize?client_id=instagram-web&redirect_uri=%2F&response_type=code"
    assert any(seg in url for seg in SURFACE)


@pytest.mark.parametrize("url", ["/oauth/token", "/api/oauth/token", "/auth/login",
                                 "/api/auth/register"])
def test_every_served_auth_path_is_watched(url):
    assert any(seg in url for seg in SURFACE)


@pytest.mark.parametrize("url", ["/api/feed", "/health", "/.well-known/jwks.json",
                                 "/api/videos/1/comments"])
def test_nothing_else_is_watched(url):
    """Recording every request would make the no-request branch fire on any page."""
    assert not any(seg in url for seg in SURFACE)


def test_the_surface_is_not_re_derived_here():
    """One owner: the same tuple object the runner derived, not a second filter (#1032)."""
    tree = ast.parse(SRC)
    imported = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                for a in n.names if a.name == "_AUTH_OBSERVED_PREFIXES_1203G1"]
    assert imported, "the derived tuple is not imported — is it being re-filtered?"
    assert not any(isinstance(n, ast.Constant) and n.value == "well-known"
                   for n in ast.walk(_flow())), "the drop-well-known rule was copied in"


def test_the_import_is_not_swallowed():
    """#1203g1's scar: a guarded import left a hand-written copy silently in use."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.ImportFrom) and any(
                    a.name == "_AUTH_OBSERVED_PREFIXES_1203G1" for a in stmt.names):
                raise AssertionError("the surface import sits inside a try — make it loud")


# --- the call sites, not just the surface ------------------------------------------------------

@pytest.mark.parametrize("name", LISTENERS)
def test_each_listener_decides_with_the_shared_predicate(name):
    """A surface nothing consults is not a fix (#1202vk's lesson, and mine twice today)."""
    tests = [ast.unparse(n.test) for n in ast.walk(_listener(name)) if isinstance(n, ast.If)]
    assert tests, "%s records unconditionally" % name
    assert any("_is_auth_url_1203it" in s for s in tests), (name, tests)


@pytest.mark.parametrize("name", LISTENERS)
def test_no_listener_still_spells_the_surface_itself(name):
    """The three hand-written copies are what made them disagree with the framework."""
    strings = {n.value for n in ast.walk(_listener(name))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not any(s.strip("/").startswith(("auth", "oauth", "api/auth", "api/oauth"))
                   for s in strings), (name, sorted(strings))


def test_all_three_listeners_are_still_attached():
    """Positive control: the assertions above are vacuous if the listeners are gone."""
    body = ast.unparse(_flow())
    for name in LISTENERS:
        assert "page.on(" in body
        assert name in body


def test_the_predicate_reads_the_imported_name():
    """If it closed over something else, the import would guard nothing."""
    for node in ast.walk(_flow()):
        if isinstance(node, ast.FunctionDef) and node.name == "_is_auth_url_1203it":
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            assert "_AUTH_SURFACE_1203it" in names, sorted(names)
            return
    raise AssertionError("_is_auth_url_1203it is gone")


# --- provenance -------------------------------------------------------------------------------

def test_the_live_run_and_its_false_note_are_recorded():
    flat = " ".join(SRC.replace("#", " ").split())
    assert "instagram-core-r176" in flat
    assert "issued NO auth request" in flat
    assert "THAT IS NO LONGER TRUE" in flat


def test_the_seventh_relisting_is_named_as_such():
    """`lifecycle`'s own sentence is why one owner matters here."""
    flat = " ".join(SRC.replace("#", " ").split())
    assert "seventh" in flat and "THREE times" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
